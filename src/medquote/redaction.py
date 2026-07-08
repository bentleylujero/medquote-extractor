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

Protection layers (in order):
  1. Catalog number stash — digit-dash catalog numbers (2063832-001)
     are stashed BEFORE Presidio so they don't get misidentified as
     phone numbers.
  2. Regex facility fallback — catches hospital/facility names
     Presidio's model misses (e.g., "St. Jude's Medical Center").
  3. Presidio analysis — detects PERSON, EMAIL, PHONE, LOCATION, ORG.
  4. Context-window filter — ORGANIZATION only redacted near keywords.
  5. Presidio anonymization — replaces detected entities.
  6. Post-processing — restores known false positives (QML, quote
     numbers, Bill To) and unstashes catalog numbers.

Known false positives (handled by post-processing):
  - "QML" (Quality Management Laboratory) misidentified as PERSON
  - Long numeric quote IDs (10+ digits) misidentified as PHONE_NUMBER
  - Catalog/part numbers (digit-dash patterns) misidentified as
    PHONE_NUMBER — handled by stashing before Presidio runs
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
    "facility", "hospital", "clinic", "medical center",
    "healthcare system", "health system",
])

_CONTEXT_WINDOW_CHARS = 120  # how far around the keyword we check


def _is_near_customer_context(text: str, start: int, end: int) -> bool:
    """Check if a match falls within a window of a customer-context keyword."""
    window_start = max(0, start - _CONTEXT_WINDOW_CHARS)
    window_end = min(len(text), end + _CONTEXT_WINDOW_CHARS)
    window = text[window_start:window_end].lower()
    return any(keyword in window for keyword in _CUSTOMER_CONTEXT_KEYWORDS)


# ── Protection layer 1: stash catalog/part numbers before Presidio ──

# Catalog numbers in medical equipment quotes follow digit-dash patterns.
# Common formats: 2063832-001 (7-3), 1407-7013-000 (4-4-3), 1011-8004-000 (4-4-3).
# These look like phone numbers to Presidio and get misidentified as PHONE_NUMBER.
# We stash them before analysis and restore after anonymization.
_CATALOG_NUMBER_RE = re.compile(r"\b\d{4,10}-\d{2,4}(?:-\d{2,4})?\b")


def _stash_catalog_numbers(text: str) -> tuple[str, dict[str, str]]:
    """Replace catalog numbers with safe placeholders before Presidio."""
    placeholders: dict[str, str] = {}

    def _stash(match: re.Match) -> str:
        key = f"__CAT_{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    protected_text = _CATALOG_NUMBER_RE.sub(_stash, text)
    return protected_text, placeholders


def _restore_catalog_numbers(text: str, placeholders: dict[str, str]) -> str:
    """Restore catalog numbers from placeholders."""
    for key, original in placeholders.items():
        text = text.replace(key, original)
    return text


# ── Protection layer 2: regex fallback for facility names ──

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
    re.compile(r"(?im)^([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,2})\s+Hospital(?:[ \t]+[A-Z][A-Za-z'.\-]+)?\s*$"),
    re.compile(r"(?im)^([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,3})\s+Medical Center\s*$"),
    re.compile(r"(?im)^([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,3})\s+Clinic\s*$"),
    # Lines ending with AUTHORITY or COUNTY HOSPITAL (e.g., "KERN COUNTY HOSPITAL AUTHORITY")
    # Without $ anchor so it catches "KERN COUNTY HOSPITAL AUTHORITY KERN COUNTY HOSPITAL AUTHORITY"
    # With word boundary after target so "AUTHORITY" alone matches
    re.compile(r"(?im)^([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){1,5})\s+(?:AUTHORITY|HEALTH NETWORK|HEALTH DISTRICT)\b.*$"),
    re.compile(r"(?im)^([A-Z][A-Za-z'.\-]+(?:[ \t]+[A-Z][A-Za-z'.\-]+){0,3})\s+COUNTY\s+HOSPITAL\b.*$"),
]

_FACILITY_REDACTED_PLACEHOLDER = "[REDACTED FACILITY]"

# Labels that signal the next line contains a facility/address name.
# When "Ship To:" appears on its own line, the hospital name is on the
# line below — not the same line. This pattern handles that split.
_NEXT_LINE_LABELS = re.compile(
    r"^(?:Bill To|Ship To|Sold To)[:\s]*(?:\s*(?:Bill To|Ship To|Sold To|Attn|Attention|Customer PO)[:\s]*)*$",
    re.IGNORECASE,
)


def _redact_facility_names_fallback(text: str) -> str:
    """Redact facility/hospital names that Presidio missed.

    Two approaches:
    1. Regex patterns that match facility names on the same line as
       keywords (FACILITY:, Bill To: same-line, etc.).
    2. Next-line redaction: when a label (Ship To:) appears on its own
       line, redact the next non-empty line (the facility name).

    Pattern 0 uses a callable replacer to preserve the "FACILITY:"
    keyword while redacting the value; other patterns replace the
    entire match.
    """
    output = text

    # Approach 1: same-line regex patterns
    for i, pattern in enumerate(_FACILITY_EXTRACTION_PATTERNS):
        if i == 0:
            # FACILITY pattern: preserve the keyword, replace the name
            def _preserve_keyword(m):
                # Preserve the keyword and the trailing line ending
                suffix = m.group(0)[m.end(2) - m.start(0):] if m.end(2) < m.end(0) else ""
                return f"{m.group(1)}: {_FACILITY_REDACTED_PLACEHOLDER}{suffix}"
            output = pattern.sub(_preserve_keyword, output)
        else:
            output = pattern.sub(_FACILITY_REDACTED_PLACEHOLDER, output)

    # Approach 2: next-line redaction for labels on their own line
    lines = output.split('\n')
    next_line_facility = False
    result_lines = []
    for line in lines:
        if next_line_facility:
            if line.strip():
                result_lines.append(_FACILITY_REDACTED_PLACEHOLDER)
                next_line_facility = False
                continue
            # blank line after label: skip and keep looking
            result_lines.append(line)
            continue
        if _NEXT_LINE_LABELS.match(line):
            result_lines.append(line)
            next_line_facility = True
            continue
        result_lines.append(line)

    return '\n'.join(result_lines)


# ── Post-processing: restore known false positives ──

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
    """Apply post-redaction restorations for known false positives."""
    output = text
    for pattern, replacement in _RESTORE_PATTERNS:
        if callable(replacement):
            output = pattern.sub(replacement, output)
        else:
            output = pattern.sub(replacement, output)
    return output


# ── Main entry point ──


def redact_customer_info(text: str) -> str:
    """Redact customer-identifying information from raw quote text.

    ORGANIZATION matches from Presidio are only redacted if they appear
    near customer-context keywords (Bill To, Attn, Hospital, etc.).
    This means vendor/manufacturer names — even ones never seen before —
    are never accidentally redacted, because they won't appear in that
    context. No allow-list maintenance needed.

    PERSON, EMAIL_ADDRESS, PHONE_NUMBER, and LOCATION are always
    redacted regardless of context.

    Protection order:
      1. Stash catalog/part numbers (digit-dash patterns)
      2. Regex facility fallback (before Presidio, catches model misses)
      3. Presidio analysis
      4. Context-window ORGANIZATION filter
      5. Presidio anonymization
      6. Restore known false positives
      7. Unstash catalog numbers

    Args:
        text: Raw extracted PDF text.

    Returns:
        Text with customer-identifying fields replaced by placeholders
        like [REDACTED]. Vendor names, catalog numbers, and prices are
        left untouched.
    """
    if not text.strip():
        return text

    # 1. Stash catalog/part numbers before Presidio sees them
    text, catalog_placeholders = _stash_catalog_numbers(text)

    # 2. Regex fallback: catch facility/hospital names on raw text,
    #    before Presidio anonymizes the "Bill To" / "Ship To" keywords
    #    that our patterns depend on.
    text = _redact_facility_names_fallback(text)

    # 3. Presidio analysis
    results = _analyzer.analyze(
        text=text,
        entities=_ENTITIES_TO_REDACT,
        language="en",
    )

    # 4. Filter: only redact ORGANIZATION if near customer-context keywords
    filtered_results = []
    for r in results:
        if r.entity_type == "ORGANIZATION":
            if _is_near_customer_context(text, r.start, r.end):
                filtered_results.append(r)
            # else: skip — likely a vendor/manufacturer name, leave visible
        else:
            # PERSON, EMAIL, PHONE, LOCATION are always redacted
            filtered_results.append(r)

    # 5. Presidio anonymization
    redacted = _anonymizer.anonymize(text=text, analyzer_results=filtered_results)
    output = redacted.text

    # 6. Restore known false positives
    output = _apply_restorations(output)

    # 7. Unstash catalog numbers
    output = _restore_catalog_numbers(output, catalog_placeholders)

    return output
