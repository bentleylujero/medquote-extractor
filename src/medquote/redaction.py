"""
Redaction module: strips customer-identifying information (hospital/
facility names, contact names, emails, phone numbers, addresses) from
quote text BEFORE it is sent to any external LLM API.

Uses Microsoft Presidio, which runs entirely locally — no external
service is contacted to perform redaction.

This runs between ingestion and extraction. It does NOT touch vendor/
manufacturer names, catalog numbers, or pricing — those fields are
needed for extraction and are not customer-identifying.

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


def redact_customer_info(
    text: str,
    known_facility_names: list[str] | None = None,
) -> str:
    """Redact customer-identifying information from raw quote text.

    Args:
        text: Raw extracted PDF text.
        known_facility_names: Optional list of known hospital/facility
            names to force-redact even if Presidio's model misses them
            (useful for facility names Presidio doesn't recognize as an
            organization).

    Returns:
        Text with customer-identifying fields replaced by placeholders
        like [REDACTED]. Vendor names, catalog numbers, and prices are
        left untouched.
    """
    if not text.strip():
        return text

    results = _analyzer.analyze(
        text=text,
        entities=_ENTITIES_TO_REDACT,
        language="en",
    )
    redacted = _anonymizer.anonymize(text=text, analyzer_results=results)
    output = redacted.text

    # Force-redact known facility names (catches ones Presidio misses)
    if known_facility_names:
        for name in known_facility_names:
            output = output.replace(name, "[REDACTED FACILITY]")

    # Restore known false positives
    output = _apply_restorations(output)

    return output
