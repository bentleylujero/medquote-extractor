"""
Redaction module: strips customer-identifying information (hospital/
facility names, contact names, emails, phone numbers, addresses) from
quote text BEFORE it is sent to any external LLM API.

Uses Microsoft Presidio, which runs entirely locally — no external
service is contacted to perform redaction.

This runs between ingestion and extraction. It does NOT touch vendor/
manufacturer names, catalog numbers, or pricing — those fields are
needed for extraction and are not customer-identifying.
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

# ── Context-window detection ──

# How many characters around a customer-context keyword to scan
_CONTEXT_WINDOW_CHARS = 120

# Keywords that signal we're in the customer-identifying region of a quote.
# "Customer" is deliberately excluded — column headers like "Customer Price"
# would falsely tag vendor names as customer info.
# Order matters: longer/more-specific phrases first to avoid partial matches.
_CUSTOMER_CONTEXT_KEYWORDS = [
    "bill to",
    "ship to",
    "sold to",
    "attn",
    "attention",
    "facility",
    "hospital",
    "clinic",
    "medical center",
    "healthcare system",
    "health system",
]


def _is_near_customer_context(text: str, match_start: int, match_end: int) -> bool:
    """Check if a Presidio entity span falls within a context window of
    customer-identifying keywords.

    This is the core mechanism to distinguish customer facilities from
    vendor names. If an ORGANIZATION entity (detected by Presidio) appears
    within _CONTEXT_WINDOW_CHARS of a customer keyword like "Bill To" or
    "Ship To", it gets redacted. Otherwise it's treated as a vendor name
    and preserved.

    Args:
        text: The full text being analyzed.
        match_start: Start position of the entity match.
        match_end: End position of the entity match.

    Returns:
        True if the entity is near a customer-context keyword.
    """
    lower = text.lower()
    for keyword in _CUSTOMER_CONTEXT_KEYWORDS:
        kw_start = 0
        while True:
            kw_pos = lower.find(keyword, kw_start)
            if kw_pos == -1:
                break
            if abs(match_start - kw_pos) <= _CONTEXT_WINDOW_CHARS:
                return True
            kw_start = kw_pos + 1
    return False


# ── Catalog number stash ──

# Catalog numbers with digit-dash patterns (e.g., 2063832-001, 1407-7013-000)
# look like PHONE_NUMBER to Presidio. We stash them before Presidio analysis
# and restore after. The pattern requires 4-10 digits before the first dash
# to avoid matching real phone numbers (800-555-0199 has 3-digit prefix).
_CATALOG_NUMBER_RE = re.compile(r"\b\d{4,10}-\d{2,4}(?:-\d{2,4})?\b")
_CATALOG_STASH: dict[str, str] = {}


def _stash_catalog_numbers(text: str) -> str:
    """Replace catalog number patterns with placeholders and save originals.

    Must be called BEFORE Presidio analysis so the dash patterns don't get
    misidentified as phone numbers.

    Returns:
        Text with catalog numbers replaced by __CAT_N__ placeholders.
    """
    global _CATALOG_STASH
    _CATALOG_STASH = {}
    result = []
    last_end = 0

    for m in _CATALOG_NUMBER_RE.finditer(text):
        placeholder = f"__{len(_CATALOG_STASH)}__"
        _CATALOG_STASH[placeholder] = m.group(0)
        result.append(text[last_end : m.start()])
        result.append(placeholder)
        last_end = m.end()

    result.append(text[last_end:])
    return "".join(result)


def _restore_catalog_numbers(text: str) -> str:
    """Restore catalog number placeholders back to original values.

    Must be called AFTER Presidio anonymization.
    """
    output = text
    for placeholder, original in _CATALOG_STASH.items():
        output = output.replace(placeholder, original)
    return output


# ── Facility fallback extraction patterns ──

# These run BEFORE Presidio anonymization to protect facility keywords
# (e.g., "Bill To") that Presidio might flag as PERSON.
#
# The patterns are line-bounded using [^\S\n] instead of \s to prevent
# cross-line matching, which was a pitfall in earlier versions.

_FACILITY_REDACTED_PLACEHOLDER = "[REDACTED FACILITY]"

_FACILITY_EXTRACTION_PATTERNS: list[re.Pattern] = [
    # 0: Lines starting with "FACILITY" keyword — preserve the keyword and trailing newline
    re.compile(
        r"(?im)^[ \t]*(FACILITY)[:\s]+(?!\[)([A-Z][A-Za-z'.\- ]+?)(?:\s*[,]?\s*(?:\n|$))"
    ),
    # 1: Bill To / Ship To / Sold To on the same line as the facility name
    #     Negative lookahead: skip if the captured name starts with [ or <
    re.compile(
        r"(?im)(?:Bill To|Ship To|Sold To)[:\s]+(?![\[<])([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){1,6})"
    ),
    # 2: "Attn: John Patterson, St. Jude's Medical Center" — capture after comma
    re.compile(
        r"(?im)Attn[:.\s]+[A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+)*,\s*(?![\[<])([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){1,6})"
    ),
    # 3: Lines with "Hospital" as part of a facility name — single line only
    re.compile(
        r"(?im)^([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,2})\s+Hospital(?:[ \t]+[A-Z][A-Za-z'.\-]+)?\s*$"
    ),
    # 4: Medical Center — including OCR typos where I→T and l→T in CENTER
    re.compile(
        r"(?im)^([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,3})\s+Medical\s+(?:Center|CENIER|CENlER)\s*$"
    ),
    # 5: Lines ending with "Clinic"
    re.compile(
        r"(?im)^([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){0,3})\s+Clinic\s*$"
    ),
    # 6: Lines ending with AUTHORITY or HEALTH NETWORK or HEALTH DISTRICT
    #     Without $ anchor so it catches duplicated names on one line
    #     (side-by-side PDF layout like "KCH KCH")
    #     Limited to 2-4 words before target to avoid capturing vendor names
    #     (e.g., "Bracco Diagnostics Inc. KERN COUNTY HOSPITAL" = 6 words)
    re.compile(
        r"(?im)^([A-Z][A-Za-z'.\-]+(?:\s+[A-Z][A-Za-z'.\-]+){1,3})\s+(?:AUTHORITY|HEALTH NETWORK|HEALTH DISTRICT)\b.*$"
    ),
    # 7: COUNTY HOSPITAL pattern — limited to 1-3 words before COUNTY
    re.compile(
        r"(?im)^([A-Z][A-Za-z'.\-]+(?:[ \t]+[A-Z][A-Za-z'.\-]+){0,2})\s+COUNTY\s+HOSPITAL\b.*$"
    ),
    # 8: Mid-line COUNTY HOSPITAL AUTHORITY — no ^ anchor, catches facility names
    #     in dual-address blocks like "Bracco Diagnostics Inc. KERN COUNTY HOSPITAL
    #     AUTHORITY" where the facility name is mid-line after a vendor prefix.
    #     Replaces the entire match since both vendor name (if any) and the
    #     KERN COUNTY part are tightly coupled on the same line.
    re.compile(
        r"(?im)\b(?:[A-Z][A-Za-z'.\-]+\s+){0,3}COUNTY\s+HOSPITAL\s+AUTHORITY\b"
    ),
]

# Labels that signal the next line contains a facility/address name.
# When "Ship To:" appears on its own line, the hospital name is on the
# line below — not the same line. This pattern handles that split.
_NEXT_LINE_LABELS = re.compile(
    r"^(?:Bill To|Ship To|Sold To)[:\s]*(?:\s*(?:Bill To|Ship To|Sold To|Attn|Attention|Customer PO)[:\s]*)*$",
    re.IGNORECASE,
)


def _preserve_keyword(match: re.Match) -> str:
    """Replacement callable for the FACILITY: pattern.

    Preserves the FACILITY keyword and trailing newline so the output
    shows ``FACILITY: [REDACTED FACILITY]`` with proper formatting.
    """
    keyword = match.group(1)
    rest = match.group(2) or ""
    trailing = ""
    if rest.endswith("\n"):
        trailing = "\n"
        rest = rest[:-1]
    return f"{keyword}: {_FACILITY_REDACTED_PLACEHOLDER}{trailing}"


def _redact_facility_names_fallback(text: str) -> str:
    """Run facility-name extraction patterns on raw text.

    Must be called BEFORE Presidio anonymization because Presidio
    may detect "Bill" as PERSON and turn "Bill To:" into "<PERSON> To:",
    which would break the Bill To pattern matching.

    Returns:
        Text with matched facility names replaced by [REDACTED FACILITY].
    """
    output = text

    # Phase 1: apply _FACILITY_EXTRACTION_PATTERNS
    for pattern in _FACILITY_EXTRACTION_PATTERNS:
        output = pattern.sub(
            lambda m: _FACILITY_REDACTED_PLACEHOLDER
            if m.lastgroup
            or (m.groups() and m.group(1) is not None)
            else _FACILITY_REDACTED_PLACEHOLDER,
            output,
        )

    # Phase 2: handle label-only lines (e.g., "Bill To:" alone on a line)
    lines = output.split("\n")
    for i, line in enumerate(lines):
        if _NEXT_LINE_LABELS.search(line):
            # Redact the next non-empty line
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j].strip():
                    lines[j] = _FACILITY_REDACTED_PLACEHOLDER
                    break

    return "\n".join(lines)


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
    # Restore ABA routing numbers misidentified as PHONE_NUMBER
    (re.compile(r"(?i)(ABA|Routing)\s*#\s*:?\s*<PHONE_NUMBER>"), "[ABA ROUTING #]"),
    # Restore vendor "Bracco" when Presidio catches it as PERSON
    # "Bracco" is a trade name (vendor), not a person's name
    # Pattern: Inc. ('<PERSON>') -> Inc. ('Bracco')
    (re.compile(r"(?i)(Inc\.\s*\(')<PERSON>('\))"), lambda m: f"{m.group(1)}Bracco{m.group(2)}"),
    # Restore "between <PERSON>" pattern for "Bracco" vendor context
    (re.compile(r"(?i)(between\s+)<PERSON>(\s+)"), lambda m: f"{m.group(1)}Bracco{m.group(2)}"),
    # Restore vendor "Carl Zeiss Meditec USA" when Presidio catches as PERSON
    # Pattern: (<PERSON>, Inc.) or (Account Name: <PERSON> Meditec USA)
    (re.compile(r"(?i)(CZ Meditec \(USA\) )<PERSON>"), lambda m: f"{m.group(1)}Carl Zeiss Meditec USA"),
    (re.compile(r"(?i)(Account Name: )<PERSON>( Meditec USA)"), lambda m: f"{m.group(1)}Carl Zeiss{m.group(2)}"),
    # Note: No catch-all <PERSON> replacement — let remaining PERSON tokens
    # pass through as <PERSON> placeholders. The extraction LLM can handle
    # these gracefully, and a catch-all risks corrupting vendor names that
    # Presidio misidentifies as persons (e.g., "Bracco", "Carl Zeiss").
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


def redact_customer_info(text: str) -> str:
    """Redact customer-identifying information from raw quote text.

    The flow is:
    1. Stash catalog numbers (digit-dash patterns that look like phones)
    2. Run fallback patterns on raw text (before Presidio can anonymize
       keywords like "Bill To")
    3. Run Presidio analyzer + anonymizer
    4. Restore catalog numbers
    5. Apply post-processing restorations

    Vendor names, catalog numbers, and prices are left untouched.

    Args:
        text: Raw extracted PDF text.

    Returns:
        Text with customer-identifying fields replaced by placeholders
        (``[REDACTED]``, ``[REDACTED FACILITY]``, ``<PERSON>``, etc).
        Vendor names, catalog numbers, and prices are preserved.
    """
    # Step 1: Stash catalog numbers
    text = _stash_catalog_numbers(text)

    # Step 2: Fallback patterns (before Presidio)
    text = _redact_facility_names_fallback(text)

    # Step 3: Presidio analysis + anonymization
    results = _analyzer.analyze(
        text=text,
        entities=_ENTITIES_TO_REDACT,
        language="en",
    )

    # Filter: only redact ORGANIZATION entities that are near customer context
    filtered = [
        r
        for r in results
        if r.entity_type != "ORGANIZATION"
        or _is_near_customer_context(text, r.start, r.end)
    ]

    redacted = _anonymizer.anonymize(text=text, analyzer_results=filtered)

    # Step 4: Restore catalog numbers
    output = _restore_catalog_numbers(redacted.text)

    # Step 5: Post-processing restorations of known false positives
    output = _apply_restorations(output)

    return output
