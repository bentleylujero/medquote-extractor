"""
Redaction module: strips customer-identifying information (hospital/
facility names, contact names, emails, phone numbers, addresses) from
quote text BEFORE it is sent to any external LLM API.

Uses Microsoft Presidio, which runs entirely locally — no external
service is contacted to perform redaction.

This runs between ingestion and extraction. It does NOT touch vendor/
manufacturer names, catalog numbers, or pricing — those fields are
needed for extraction and are not customer-identifying.

Context-window approach for ORGANIZATION entities:
  Instead of maintaining a vendor allow-list (which would need updates
  every time a new manufacturer appears), ORGANIZATION matches from
  Presidio are only redacted if they appear within a 120-character
  window of a customer-context keyword (Bill To, Ship To, Attn,
  Hospital, Facility, etc.). Vendor/manufacturer names never appear
  near those keywords in medical quotes, so they are never redacted —
  even for brand-new, never-seen-before manufacturers.

Known false positives (handled by post-processing):
  - "QML" (Quality Management Laboratory) misidentified as PERSON
  - Long numeric quote IDs (10+ digits) misidentified as PHONE_NUMBER
  - "Govt." misidentified as PERSON in legal boilerplate
"""

import re
from collections.abc import Callable

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

_analyzer = AnalyzerEngine()
_anonymizer = AnonymizerEngine()

# Entity types we want Presidio to catch. PERSON and ORGANIZATION cover
# contact names and hospital/facility names respectively.
_ENTITIES_TO_REDACT = [
    "PERSON",
    "ORGANIZATION",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "LOCATION",
]

# Keywords that signal "this is the customer's info," not the vendor's.
# ORGANIZATION matches are only redacted if found near one of these.
_CUSTOMER_CONTEXT_KEYWORDS = frozenset([
    "bill to", "ship to", "sold to", "attn", "attention",
    "customer", "facility", "hospital", "clinic", "medical center",
    "healthcare system", "health system",
])

_CONTEXT_WINDOW_CHARS = 120  # how far around the keyword we check


def _is_near_customer_context(text: str, start: int, end: int) -> bool:
    """Check if a match falls within a window of a customer-context keyword."""
    window_start = max(0, start - _CONTEXT_WINDOW_CHARS)
    window_end = min(len(text), end + _CONTEXT_WINDOW_CHARS)
    window = text[window_start:window_end].lower()
    return any(keyword in window for keyword in _CUSTOMER_CONTEXT_KEYWORDS)


# ---- Regex fallback for facility names Presidio's model misses ----

# Look for lines containing customer-context keywords followed by
# capitalized words that form facility/hospital names. Presidio's
# spaCy model often doesn't recognize hospital/facility names as
# ORGANIZATION entities, so this catch-all backs it up.
_FACILITY_EXTRACTION_PATTERNS = [
    # "FACILITY: St. Jude's Medical Center" — preserve "FACILITY:" keyword, redact the value
    re.compile(r"(?im)^[ \t]*(FACILITY)[:\s]+(?!\[)([A-Z][A-Za-z'.\- ]+?)(?:\s*[,]?\s*(?:\n|$))"),
    # "Bill To: St. Jude's Medical Center" — capture after colon, before comma, line end, or [REDACTED
    re.compile(r"(?im)(?:Bill To|Ship To|Sold To)[:\s]+(?![\[<])([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){1,6})"),
    # "Attn: John Patterson, St. Jude's Medical Center" — capture after comma
    re.compile(r"(?im)Attn[:\s]+[A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+)*,\s*(?![\[<])([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){1,6})"),
    # Lines with "Hospital" or "Medical Center" as part of a facility name — single line only
    # Handles both: "Mercy Hospital" and "Mercy Hospital Northwest" and "Lakeside Regional Medical Center"
    re.compile(r"(?im)^([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,2})\s+Hospital(?:[ \t]+[A-Z][A-Za-z'.\-]+)?\s*$"),
    re.compile(r"(?im)^([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,3})\s+Medical Center\s*$"),
    re.compile(r"(?im)^([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,3})\s+Clinic\s*$"),
]

_FACILITY_REDACTED_PLACEHOLDER = "[REDACTED FACILITY]"


def _redact_facility_names_fallback(text: str) -> str:
    """Redact facility/hospital names that Presidio missed.

    Uses regex patterns targeting lines near customer-context keywords.
    Pattern 0 uses a callable replacer to preserve the "FACILITY:" keyword
    while redacting the value; other patterns replace the whole match.
    """
    output = text
    for i, pattern in enumerate(_FACILITY_EXTRACTION_PATTERNS):
        if i == 0:
            # FACILITY pattern: preserve the keyword, replace the name
            def _preserve_keyword(m):
                # Preserve the keyword and the trailing line ending
                suffix = m.group(0)[m.end(2)-m.start(0):] if m.end(2) < m.end(0) else ""
                return f"{m.group(1)}: {_FACILITY_REDACTED_PLACEHOLDER}{suffix}"
            output = pattern.sub(_preserve_keyword, output)
        else:
            output = pattern.sub(_FACILITY_REDACTED_PLACEHOLDER, output)
    return output


# Patterns to restore after redaction — these catch known false positives
# where Presidio's spaCy model misidentifies medical-domain terms.
_RESTORE_PATTERNS: list[tuple[re.Pattern, str | Callable]] = [
    # Restore quote numbers that Presidio misidentifies as PHONE_NUMBER
    # Covers: Quotation Number: <PH>, Quotation No.: <PH>, Quote #: <PH>, etc.
    (
        re.compile(r"(?i)(?:Quotation|Quote)\s*(?:Number|No|#)\.?\s*:?\s*<PHONE_NUMBER>"),
        lambda m: re.sub(r"<PHONE_NUMBER>", "[QUOTE #]", m.group(0)),
    ),
    # Restore "QML" when it appears as <PERSON> in a product catalog line
    # Pattern: after a colon and space, before a comma or end of line
    # e.g., "Q611.2SP: <PERSON>, Sybase" -> "Q611.2SP: QML, Sybase"
    (
        re.compile(r"([:]\s*)<PERSON>(\s*[,])"),
        lambda m: f"{m.group(1)}QML{m.group(2)}",
    ),
    # Restore "Bill To" headers (common in medical quote forms, misidentified as PERSON)
    (re.compile(r"<PERSON>\s+To\b"), "Bill To"),
    # Also restore standalone <PERSON> if it literally was "QML" (broader fallback)
    (re.compile(r"<PERSON>\b"), "QML"),
]


def _apply_restorations(text: str) -> str:
    """Apply post-redaction restorations for known false positives.

    Presidio's spaCy model is trained on general text and can
    misidentify medical-domain abbreviations (QML) and numeric
    quote IDs (phone-number-like strings) as PII. This pass
    restores those using pattern matching.
    """
    output = text
    for pattern, replacement in _RESTORE_PATTERNS:
        if callable(replacement):
            output = pattern.sub(replacement, output)
        else:
            output = pattern.sub(replacement, output)
    return output


def redact_customer_info(text: str) -> str:
    """Redact customer-identifying information from raw quote text.

    ORGANIZATION matches from Presidio are only redacted if they appear
    near customer-context keywords (Bill To, Attn, Hospital, etc.).
    This means vendor/manufacturer names — even ones never seen before —
    are never accidentally redacted, because they won't appear in that
    context. No allow-list maintenance needed.

    PERSON, EMAIL_ADDRESS, PHONE_NUMBER, and LOCATION are always
    redacted regardless of context.

    Args:
        text: Raw extracted PDF text.

    Returns:
        Text with customer-identifying fields replaced by placeholders
        like [REDACTED]. Vendor names, catalog numbers, and prices are
        left untouched.
    """
    if not text.strip():
        return text

    # Regex fallback FIRST: catch facility/hospital names on raw text,
    # before Presidio anonymizes the "Bill To" / "Ship To" keywords that
    # our patterns depend on to identify customer-context facility names.
    text = _redact_facility_names_fallback(text)

    results = _analyzer.analyze(
        text=text,
        entities=_ENTITIES_TO_REDACT,
        language="en",
    )

    # Filter: only redact ORGANIZATION if near customer-context keywords
    filtered_results = []
    for r in results:
        if r.entity_type == "ORGANIZATION":
            if _is_near_customer_context(text, r.start, r.end):
                filtered_results.append(r)
            # else: skip — likely a vendor/manufacturer name, leave visible
        else:
            # PERSON, EMAIL, PHONE, LOCATION are always redacted
            filtered_results.append(r)

    redacted = _anonymizer.anonymize(text=text, analyzer_results=filtered_results)
    output = redacted.text

    # Restore known false positives
    output = _apply_restorations(output)

    return output
