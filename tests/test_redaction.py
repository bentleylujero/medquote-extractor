"""
Test script for Presidio-based customer info redaction.

Feeds sample text with fake hospital names, contact names, emails,
phone numbers, and vendor/catalog/pricing data through the redaction
module, then verifies:
  - Customer-identifying fields are redacted (not present in output)
  - Vendor names, dollar amounts, and catalog numbers are UNCHANGED
  - ORGANIZATION matches are only redacted near customer-context keywords
    (Bill To, Ship To, Attn, Hospital, etc.) — not everywhere
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from medquote.redaction import redact_customer_info


SAMPLE_A = """\
QUOTE #: Q-2025-0042
DATE: 2025-03-15
PREPARED FOR: Dr. Sarah Mitchell, Chief of Surgery
FACILITY: St. Jude's Medical Center
ADDRESS: 3400 Health Parkway, Suite 200
CITY: San Francisco, CA 94115
PHONE: (415) 555-0199
EMAIL: sarah.mitchell@stjudes.org

VENDOR: GE Healthcare
CATALOG #: 45-982-1-V2
DESCRIPTION: LOGIQ E10 Ultrasound System
QTY: 1
UNIT PRICE: $149,500.00
NET PRICE: $127,000.00
"""

SAMPLE_B = """\
Attn: John Patterson
Purchasing Department
Mercy Hospital Northwest
john.patterson@mercyhospital.org
Direct: 612-555-0142

Item: 7300-04-A
Siemens Healthineers SOMATOM go.All
Quantity: 2
List each: $89,750.00
Total: $179,500.00
"""

SAMPLE_C = """\
Ship To:
Jane Williamson, RN
Administrative Director
Lakeside Regional Medical Center
2000 Lakeshore Drive
Chicago, IL 60614
Phone: 312-555-0293
j.williamson@lakesidermc.org

Reference #: RFQ-2025-0881

Zimmer Biomet Catalog #: 43-1067-001-00
Description: G7 Acetabular Shell System
Each: $3,450.00
"""

# --- New test texts for context-window behavior ---

CONTEXT_VENDOR_TEXT = "GE Healthcare Quote #12345\nItem: 45-982-1-V2, $149,500.00"

CONTEXT_NEW_MFR_TEXT = (
    "Acme Surgical Devices Corp Quote #99887\nItem: X-100, $5,000.00"
)

CONTEXT_BILL_TO_TEXT = "Bill To: St. Jude's Medical Center, 123 Main St"

CONTEXT_SHIP_TO_TEXT = (
    "Ship To: Mercy Hospital Northwest, Attn: Receiving Dept"
)


def check_redacted(label, text, expected_preserved, expected_removed):
    """Run redaction and check preservation/removal."""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")

    result = redact_customer_info(text)

    print("\n  --- BEFORE (excerpt) ---")
    print(f"  {text.strip()}")

    print("\n  --- AFTER (excerpt) ---")
    print(f"  {result.strip()}")

    # Check preservation
    preserved_ok = True
    for phrase in expected_preserved:
        if phrase not in result:
            print(f"  ❌ FALSE NEGATIVE: '{phrase}' was redacted but should have been kept!")
            preserved_ok = False
    if preserved_ok:
        print(f"  ✅ All vendor/catalog/pricing data preserved")

    # Check removal
    removed_ok = True
    for phrase in expected_removed:
        if phrase in result:
            print(f"  ❌ FALSE POSITIVE: '{phrase}' was NOT redacted (still present in output)")
            removed_ok = False
    if removed_ok:
        print(f"  ✅ All customer-identifying info redacted")

    return preserved_ok, removed_ok


def test_vendor_name_survives_when_not_near_customer_context():
    text = "GE Healthcare Quote #12345\nItem: 45-982-1-V2, $149,500.00"
    result = redact_customer_info(text)
    assert "GE Healthcare" in result, (
        f"GE Healthcare was redacted! Result:\n{result}"
    )


def test_new_unlisted_manufacturer_survives():
    """A manufacturer never seen before should NOT be redacted, proving
    we don't rely on a hardcoded list."""
    text = "Acme Surgical Devices Corp Quote #99887\nItem: X-100, $5,000.00"
    result = redact_customer_info(text)
    assert "Acme Surgical Devices Corp" in result, (
        f"Unknown manufacturer was redacted! Result:\n{result}"
    )


def test_hospital_near_bill_to_is_redacted():
    text = "Bill To: St. Jude's Medical Center, 123 Main St"
    result = redact_customer_info(text)
    assert "St. Jude's" not in result, (
        f"Hospital near Bill To was NOT redacted! Result:\n{result}"
    )


def test_hospital_near_ship_to_is_redacted():
    text = "Ship To: Mercy Hospital Northwest, Attn: Receiving Dept"
    result = redact_customer_info(text)
    assert "Mercy Hospital Northwest" not in result, (
        f"Hospital near Ship To was NOT redacted! Result:\n{result}"
    )


def test_catalog_numbers_preserved():
    """All digit-dash catalog numbers must survive redaction, even if
    Presidio would normally tag them as PHONE_NUMBER."""
    text = (
        "Catalog items:\n"
        "2063832-001 AISYS CS2 PC SERVICE\n"
        "1407-7013-000 ASSY-MSN, TOOL LEAK TEST\n"
        "1011-8004-000 CASSETTE TEST VAPORIZER\n"
        "1503-3236-000 COUPLING INLINE\n"
        "1503-3119-000 COUPLING BODY IN-LINE\n"
        "800-345-2700 should be real phone"
    )
    result = redact_customer_info(text)
    for cat_num in [
        "2063832-001", "1407-7013-000", "1011-8004-000",
        "1503-3236-000", "1503-3119-000",
    ]:
        assert cat_num in result, (
            f"Catalog number {cat_num} was destroyed by redaction! "
            f"Result excerpt: ...{result[result.find(cat_num[:3]):result.find(cat_num[:3])+30] if cat_num[:3] in result else 'NOT FOUND'}..."
        )
    # Real phone number should still be redacted
    assert "800-345-2700" not in result, (
        f"Real phone number survived redaction! Result:\n{result}"
    )


def test_authority_facility_redacted():
    """KERN COUNTY HOSPITAL AUTHORITY uses 'AUTHORITY' suffix, not
    'Hospital' or 'Medical Center'. Should still be redacted."""
    text = "Bill To:\nKERN COUNTY HOSPITAL AUTHORITY\n1700 MT VERNON AVE"
    result = redact_customer_info(text)
    assert "KERN COUNTY HOSPITAL AUTHORITY" not in result, (
        f"AUTHORITY-suffix facility was NOT redacted! Result:\n{result}"
    )


def test_ship_to_next_line_redacted():
    """Ship To label on its own line, facility name on the next line."""
    text = "Ship To:\nKERN COUNTY HOSPITAL AUTHORITY\n1700 MT VERNON AVE"
    result = redact_customer_info(text)
    assert "KERN COUNTY HOSPITAL AUTHORITY" not in result, (
        f"Next-line Ship To facility was NOT redacted! Result:\n{result}"
    )


def main():
    print("=" * 70)
    print("  Presidio Redaction Test Suite — Context-Window Edition")
    print("  Verifying: PII stripped, vendor preserved, context rule works")
    print("=" * 70)

    all_ok = True

    # --- Original 3 samples ---

    # Sample A: Full quote header with customer details
    # "FACILITY:" is a customer-context keyword -> hospital name redacted
    p_ok, r_ok = check_redacted(
        "Sample A — Full Quote Header",
        SAMPLE_A,
        expected_preserved=[
            "GE Healthcare",
            "45-982-1-V2",
            "$149,500.00",
            "$127,000.00",
            "LOGIQ E10 Ultrasound System",
        ],
        expected_removed=[
            "Dr. Sarah Mitchell",
            "Sarah Mitchell",
            "St. Jude's Medical Center",
            "sarah.mitchell@stjudes.org",
            "(415) 555-0199",
        ],
    )
    all_ok = all_ok and p_ok and r_ok

    # Sample B: Short contact + vendor
    # "Attn:" and "Hospital" are customer-context keywords
    p_ok, r_ok = check_redacted(
        "Sample B — Contact Block + Vendor",
        SAMPLE_B,
        expected_preserved=[
            "Siemens Healthineers",
            "7300-04-A",
            "$89,750.00",
            "$179,500.00",
            "SOMATOM go.All",
        ],
        expected_removed=[
            "John Patterson",
            "Mercy Hospital Northwest",
            "john.patterson@mercyhospital.org",
            "612-555-0142",
        ],
    )
    all_ok = all_ok and p_ok and r_ok

    # Sample C: Name, facility, address + pricing
    # "Ship To:" + "Medical Center" are customer-context keywords
    p_ok, r_ok = check_redacted(
        "Sample C — Full Contact + Medical Device Catalog",
        SAMPLE_C,
        expected_preserved=[
            "Zimmer Biomet",
            "43-1067-001-00",
            "$3,450.00",
            "G7 Acetabular Shell System",
        ],
        expected_removed=[
            "Jane Williamson",
            "Lakeside Regional Medical Center",
            "j.williamson@lakesidermc.org",
            "312-555-0293",
            "Lakeshore Drive",
            "Chicago, IL 60614",
        ],
    )
    all_ok = all_ok and p_ok and r_ok

    # --- New context-window tests ---

    print(f"\n{'='*70}")
    print("  Context-Window Rule Tests")
    print(f"{'='*70}")

    test_vendor_name_survives_when_not_near_customer_context()
    print("  ✅ test_vendor_name_survives_when_not_near_customer_context")

    test_new_unlisted_manufacturer_survives()
    print("  ✅ test_new_unlisted_manufacturer_survives")

    test_hospital_near_bill_to_is_redacted()
    print("  ✅ test_hospital_near_bill_to_is_redacted")

    test_hospital_near_ship_to_is_redacted()
    print("  ✅ test_hospital_near_ship_to_is_redacted")

    # --- New tests for catalog number protection & KERN COUNTY ---

    print(f"\n{'='*70}")
    print("  Catalog Number & Facility Name Tests")
    print(f"{'='*70}")

    test_catalog_numbers_preserved()
    print("  ✅ test_catalog_numbers_preserved")

    test_authority_facility_redacted()
    print("  ✅ test_authority_facility_redacted")

    test_ship_to_next_line_redacted()
    print("  ✅ test_ship_to_next_line_redacted")

    print(f"\n{'='*70}")
    if all_ok:
        print("  ✅ ALL TESTS PASSED — redaction is working correctly")
    else:
        print("  ❌ SOME TESTS FAILED — see details above")
    print(f"{'='*70}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
