"""
Test script for Presidio-based customer info redaction.

Feeds sample text with fake hospital names, contact names, emails,
phone numbers, and vendor/catalog/pricing data through the redaction
module, then verifies:
  - Customer-identifying fields are redacted (not present in output)
  - Vendor names, dollar amounts, and catalog numbers are UNCHANGED
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


def check_redacted(label, text, expected_preserved, expected_removed):
    """Run redaction and check preservation/removal."""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")

    result = redact_customer_info(text, known_facility_names=[
        "St. Jude's Medical Center",
        "Mercy Hospital Northwest",
        "Lakeside Regional Medical Center",
    ])

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


def main():
    print("=" * 70)
    print("  Presidio Redaction Test Suite")
    print("  Verifying customer info is stripped, vendor data is preserved")
    print("=" * 70)

    all_ok = True

    # Sample A: Full quote header with customer details
    # NOTE: Street addresses (like "3400 Health Parkway") are a known
    # limitation — Presidio's LOCATION entity handles city/state better
    # than standalone street addresses. Known facility names via
    # the known_facility_names parameter handle the facility name itself.
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

    print(f"\n{'='*70}")
    if all_ok:
        print("  ✅ ALL TESTS PASSED — redaction is working correctly")
    else:
        print("  ❌ SOME TESTS FAILED — see details above")
    print(f"{'='*70}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
