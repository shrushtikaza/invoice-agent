"""
Tests for the invoice processing agent.

These test the validation logic (validator.py) directly, without calling
the Anthropic API — so they run fast and don't consume API credits.

For end-to-end tests that exercise the full pipeline including extraction,
run: python run.py --sample <name>
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import ExtractionResult, CheckResult, Flag, determine_verdict
from src.validator import run_checks
from src.reference_data import VENDOR_REGISTRY, OPEN_POS, PAID_INVOICES


def make_extraction(**kwargs):
    """Helper to build an ExtractionResult with sensible defaults."""
    defaults = dict(
        invoice_number="INV-TEST-001",
        vendor_name="Sharma Steel Traders",
        invoice_date="07 April 2025",
        due_date="07 May 2025",
        po_reference="PO-2025-0041",
        vendor_gstin="27AABCS1429B1ZP",
        line_items=[],
        subtotal_inr=450000,
        gst_rate_stated="18%",
        gst_inr=81000,
        total_inr=531000,
        bank_details_present=True,
        additional_notes=None,
    )
    defaults.update(kwargs)
    return ExtractionResult(**defaults)


def test_routine_invoice():
    """Known vendor, amount within PO, correct tax → APPROVE."""
    ext = make_extraction()
    checks, flags, avp = run_checks(ext, VENDOR_REGISTRY, OPEN_POS, PAID_INVOICES)
    verdict, conf, _, _ = determine_verdict(ext, checks, flags)
    assert verdict == "APPROVE", f"Expected APPROVE, got {verdict}"
    assert not any(f.severity == "danger" for f in flags)
    print("✓ test_routine_invoice")


def test_duplicate_invoice():
    """Invoice number already in payment history → HOLD."""
    ext = make_extraction(
        invoice_number="INV-2025-0712",
        vendor_name="Kapoor Maintenance Services",
        po_reference="PO-2025-0037",
        subtotal_inr=63500,
        gst_inr=11430,
        total_inr=74930,
    )
    checks, flags, _ = run_checks(ext, VENDOR_REGISTRY, OPEN_POS, PAID_INVOICES)
    verdict, _, _, _ = determine_verdict(ext, checks, flags)
    assert verdict == "HOLD", f"Expected HOLD, got {verdict}"
    assert any("duplicate" in f.message.lower() for f in flags)
    print("✓ test_duplicate_invoice")


def test_suspended_vendor():
    """Suspended vendor → HOLD regardless of amounts."""
    ext = make_extraction(vendor_name="Galaxy Chemicals", po_reference=None)
    checks, flags, _ = run_checks(ext, VENDOR_REGISTRY, OPEN_POS, PAID_INVOICES)
    verdict, _, _, _ = determine_verdict(ext, checks, flags)
    assert verdict == "HOLD", f"Expected HOLD, got {verdict}"
    assert any("suspended" in f.message.lower() for f in flags)
    print("✓ test_suspended_vendor")


def test_amount_over_po_flag():
    """Invoice 29% over PO balance → FLAG (between 10% and 40% thresholds)."""
    # PO-2025-0039 balance is ₹80,000 for FastMove Logistics
    ext = make_extraction(
        vendor_name="FastMove Logistics Pvt. Ltd.",
        po_reference="PO-2025-0039",
        subtotal_inr=92000,
        gst_inr=11040,
        total_inr=103040,
    )
    checks, flags, avp = run_checks(ext, VENDOR_REGISTRY, OPEN_POS, PAID_INVOICES)
    verdict, _, _, _ = determine_verdict(ext, checks, flags)
    assert verdict == "FLAG", f"Expected FLAG, got {verdict}"
    assert avp["variance_pct"] > 10, f"Expected >10% variance, got {avp['variance_pct']}"
    print("✓ test_amount_over_po_flag")


def test_tax_calculation_error():
    """GST amount doesn't match stated rate → FLAG."""
    # Rajput Power: subtotal ₹1,69,250, GST @5% should be ₹8,462 but invoice says ₹12,000
    ext = make_extraction(
        invoice_number="RPS-2025-0229",
        vendor_name="Rajput Power Systems",
        po_reference="PO-2025-0033",
        subtotal_inr=169250,
        gst_rate_stated="5%",
        gst_inr=12000,   # Wrong: should be ~8,462
        total_inr=181250,
    )
    checks, flags, _ = run_checks(ext, VENDOR_REGISTRY, OPEN_POS, PAID_INVOICES)
    verdict, _, _, _ = determine_verdict(ext, checks, flags)
    assert verdict in ("FLAG", "HOLD"), f"Expected FLAG or HOLD, got {verdict}"
    assert any("tax" in f.message.lower() or "gst" in f.message.lower() for f in flags)
    print("✓ test_tax_calculation_error")


def test_unknown_vendor():
    """Vendor not in registry → FLAG."""
    ext = make_extraction(vendor_name="Zenith Tooling Solutions", po_reference=None)
    checks, flags, _ = run_checks(ext, VENDOR_REGISTRY, OPEN_POS, PAID_INVOICES)
    verdict, _, _, _ = determine_verdict(ext, checks, flags)
    assert verdict == "FLAG", f"Expected FLAG, got {verdict}"
    assert any("unknown" in f.message.lower() for f in flags)
    print("✓ test_unknown_vendor")


def test_missing_fields():
    """Invoice missing several mandatory fields → FLAG or HOLD."""
    ext = make_extraction(
        invoice_number=None,
        vendor_name="Singh Packaging Co.",
        invoice_date=None,
        po_reference=None,
        subtotal_inr=48000,
        gst_inr=8640,
        total_inr=56640,
    )
    checks, flags, _ = run_checks(ext, VENDOR_REGISTRY, OPEN_POS, PAID_INVOICES)
    verdict, _, _, _ = determine_verdict(ext, checks, flags)
    assert verdict in ("FLAG", "HOLD"), f"Expected FLAG or HOLD, got {verdict}"
    print("✓ test_missing_fields")


def test_absolute_ceiling():
    """Any invoice above ₹10L → HOLD regardless of PO match."""
    ext = make_extraction(
        subtotal_inr=950000,
        gst_inr=171000,
        total_inr=1121000,   # > ₹10L
    )
    checks, flags, _ = run_checks(ext, VENDOR_REGISTRY, OPEN_POS, PAID_INVOICES)
    verdict, _, _, _ = determine_verdict(ext, checks, flags)
    assert verdict == "HOLD", f"Expected HOLD for >₹10L invoice, got {verdict}"
    print("✓ test_absolute_ceiling")


if __name__ == "__main__":
    print("Running invoice agent tests...\n")
    test_routine_invoice()
    test_duplicate_invoice()
    test_suspended_vendor()
    test_amount_over_po_flag()
    test_tax_calculation_error()
    test_unknown_vendor()
    test_missing_fields()
    test_absolute_ceiling()
    print("\nAll tests passed.")
