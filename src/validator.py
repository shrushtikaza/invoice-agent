"""
Validation checks for invoice processing.

Each check is independent and explicit. The intent is that a finance reviewer
can read this file and understand exactly what the agent tested — no black box.

Check results:
  PASS  — no issue
  FAIL  — hard failure (typically drives a HOLD)
  WARN  — soft warning (typically drives a FLAG)
  SKIP  — check could not be performed (e.g. missing data)
"""

from .reference_data import APPROVAL_THRESHOLDS


def _fuzzy_vendor_key(vendor_name: str) -> str:
    """Normalise vendor name for registry lookup."""
    if not vendor_name:
        return ""
    return vendor_name.lower().strip().rstrip(".")


def run_checks(extracted, vendor_registry, open_pos, paid_invoices):
    """
    Run all validation checks and return (checks, flags, amount_vs_po).
    """
    checks = []
    flags = []
    amount_vs_po = {"po_amount": None, "invoice_amount": None, "variance_pct": None}

    thresholds = APPROVAL_THRESHOLDS
    vendor_key = _fuzzy_vendor_key(extracted.vendor_name or "")
    vendor_data = vendor_registry.get(vendor_key)

    # ------------------------------------------------------------------
    # CHECK 1: Mandatory fields present
    # ------------------------------------------------------------------
    mandatory = {
        "invoice_number": extracted.invoice_number,
        "vendor_name": extracted.vendor_name,
        "invoice_date": extracted.invoice_date,
        "total_amount": extracted.total_inr,
    }
    missing = [k for k, v in mandatory.items() if not v]
    if not missing:
        checks.append(Check("Mandatory fields", "PASS", "All mandatory fields present"))
    elif len(missing) <= 2:
        checks.append(Check("Mandatory fields", "WARN", f"Missing: {', '.join(missing)}"))
        flags.append(Flag("warn", f"Incomplete invoice — missing fields: {', '.join(missing)}"))
    else:
        checks.append(Check("Mandatory fields", "FAIL", f"Missing: {', '.join(missing)}"))
        flags.append(Flag("danger", f"Too many missing fields ({', '.join(missing)}) — cannot process"))

    # ------------------------------------------------------------------
    # CHECK 2: Vendor in registry
    # ------------------------------------------------------------------
    if not vendor_key:
        checks.append(Check("Vendor registry", "SKIP", "No vendor name extracted"))
    elif vendor_data is None:
        checks.append(Check("Vendor registry", "WARN", f"'{extracted.vendor_name}' not in registry"))
        flags.append(Flag("warn", f"Unknown vendor '{extracted.vendor_name}' — no prior history"))
    elif vendor_data["status"] == "suspended":
        checks.append(Check("Vendor registry", "FAIL", f"Vendor is SUSPENDED"))
        flags.append(Flag("danger", f"Vendor '{vendor_data['canonical_name']}' is suspended — do not pay"))
    elif vendor_data["status"] == "watch":
        checks.append(Check("Vendor registry", "WARN", "Vendor is on watch list"))
        flags.append(Flag("warn", f"Vendor '{vendor_data['canonical_name']}' is on the watch list — verify before approving"))
    elif vendor_data["status"] == "new":
        checks.append(Check("Vendor registry", "WARN", "New/probationary vendor"))
        flags.append(Flag("warn", f"'{vendor_data['canonical_name']}' is a new vendor with no payment history"))
    else:
        checks.append(Check("Vendor registry", "PASS", f"Approved vendor — {vendor_data['category']}"))

    # ------------------------------------------------------------------
    # CHECK 3: Duplicate invoice number
    # ------------------------------------------------------------------
    inv_num = (extracted.invoice_number or "").strip()
    if not inv_num:
        checks.append(Check("Duplicate check", "SKIP", "No invoice number to check"))
    elif inv_num in paid_invoices:
        paid = paid_invoices[inv_num]
        checks.append(Check("Duplicate check", "FAIL",
            f"Invoice {inv_num} was already paid on {paid['payment_date']} — ₹{paid['amount_inr']:,.0f}"))
        flags.append(Flag("danger",
            f"Duplicate invoice: {inv_num} was paid on {paid['payment_date']} (₹{paid['amount_inr']:,.0f})"))
    else:
        checks.append(Check("Duplicate check", "PASS", "Invoice number not found in payment history"))

    # ------------------------------------------------------------------
    # CHECK 4: PO reference and amount match
    # ------------------------------------------------------------------
    po_ref = (extracted.po_reference or "").strip().upper()
    if not po_ref:
        checks.append(Check("PO match", "WARN", "No PO reference on invoice"))
        flags.append(Flag("warn", "Invoice has no PO reference — cannot verify against approved order"))
    elif po_ref not in open_pos:
        checks.append(Check("PO match", "WARN", f"PO {po_ref} not found in open POs"))
        flags.append(Flag("warn", f"Referenced PO '{po_ref}' not found in open PO register"))
    else:
        po = open_pos[po_ref]
        po_balance = po["balance_inr"]
        invoice_total = extracted.total_inr or 0

        amount_vs_po = {
            "po_amount": po_balance,
            "invoice_amount": invoice_total,
            "variance_pct": None,
        }

        if invoice_total > 0 and po_balance > 0:
            variance = (invoice_total - po_balance) / po_balance
            amount_vs_po["variance_pct"] = round(variance * 100, 1)

            if abs(variance) <= thresholds["po_tolerance_pct"]:
                checks.append(Check("PO amount match", "PASS",
                    f"Invoice ₹{invoice_total:,.0f} within 10% tolerance of PO balance ₹{po_balance:,.0f}"))
            elif variance > thresholds["po_hold_pct"]:
                checks.append(Check("PO amount match", "FAIL",
                    f"Invoice {variance*100:+.1f}% over PO balance — exceeds 40% threshold"))
                flags.append(Flag("danger",
                    f"Invoice amount is {variance*100:+.1f}% above PO balance (₹{po_balance:,.0f})"))
            elif variance > thresholds["po_warn_pct"]:
                checks.append(Check("PO amount match", "WARN",
                    f"Invoice {variance*100:+.1f}% over PO balance"))
                flags.append(Flag("warn",
                    f"Invoice amount is {variance*100:+.1f}% above PO balance — verify with vendor"))
            elif variance < -0.30:
                checks.append(Check("PO amount match", "WARN",
                    f"Invoice is significantly under PO balance — possible partial delivery"))
                flags.append(Flag("info",
                    f"Invoice amount is {variance*100:.1f}% below PO balance — may be a partial delivery"))
            else:
                checks.append(Check("PO amount match", "PASS",
                    f"Invoice amount within acceptable range of PO balance"))

    # ------------------------------------------------------------------
    # CHECK 5: Absolute value ceiling
    # ------------------------------------------------------------------
    invoice_total = extracted.total_inr or 0
    if invoice_total >= thresholds["absolute_hold_inr"]:
        checks.append(Check("Value ceiling", "FAIL",
            f"₹{invoice_total:,.0f} exceeds ₹10L auto-approval ceiling"))
        flags.append(Flag("danger",
            f"Invoice total ₹{invoice_total:,.0f} exceeds ₹10L — requires CFO approval"))
    elif invoice_total > 0:
        checks.append(Check("Value ceiling", "PASS",
            f"₹{invoice_total:,.0f} within auto-approval ceiling"))

    # ------------------------------------------------------------------
    # CHECK 6: Tax calculation
    # ------------------------------------------------------------------
    if extracted.subtotal_inr and extracted.gst_inr and extracted.gst_rate_stated:
        gst_rate_str = extracted.gst_rate_stated.replace("%", "").replace("@", "").strip()
        try:
            gst_rate = float(gst_rate_str) / 100.0
            expected_gst = extracted.subtotal_inr * gst_rate
            actual_gst = extracted.gst_inr
            diff_pct = abs(expected_gst - actual_gst) / expected_gst if expected_gst else 0

            if diff_pct <= thresholds["tax_tolerance_pct"]:
                checks.append(Check("Tax calculation", "PASS",
                    f"GST ₹{actual_gst:,.0f} matches stated rate ({extracted.gst_rate_stated})"))
            else:
                checks.append(Check("Tax calculation", "WARN",
                    f"GST ₹{actual_gst:,.0f} differs from expected ₹{expected_gst:,.0f} by {diff_pct*100:.1f}%"))
                flags.append(Flag("warn",
                    f"Tax calculation error: stated GST ₹{actual_gst:,.0f}, expected ₹{expected_gst:,.0f} "
                    f"at {extracted.gst_rate_stated} — verify with vendor"))
        except (ValueError, ZeroDivisionError):
            checks.append(Check("Tax calculation", "SKIP", "Could not parse GST rate"))
    elif extracted.subtotal_inr and extracted.total_inr:
        # Can't verify without stated rate, but check if total > subtotal at least
        if extracted.total_inr >= extracted.subtotal_inr:
            checks.append(Check("Tax calculation", "SKIP", "GST rate not stated — arithmetic check skipped"))
        else:
            checks.append(Check("Tax calculation", "FAIL", "Total is less than subtotal — arithmetic error"))
            flags.append(Flag("danger", "Invoice arithmetic error: total is less than subtotal"))
    else:
        checks.append(Check("Tax calculation", "SKIP", "Insufficient amount data to verify tax"))

    # ------------------------------------------------------------------
    # CHECK 7: Amount within vendor's typical range
    # ------------------------------------------------------------------
    if vendor_data and vendor_data.get("status") not in ("suspended",) and invoice_total > 0:
        lo, hi = vendor_data["typical_range_inr"]
        if hi > 0 and invoice_total > hi * 2.5:
            checks.append(Check("Historical range", "WARN",
                f"₹{invoice_total:,.0f} is well above vendor's typical range ₹{lo:,.0f}–₹{hi:,.0f}"))
            flags.append(Flag("warn",
                f"Unusual amount: ₹{invoice_total:,.0f} significantly above this vendor's historical range"))
        elif hi > 0 and invoice_total > hi:
            checks.append(Check("Historical range", "WARN",
                f"₹{invoice_total:,.0f} above vendor's typical max ₹{hi:,.0f}"))
        elif lo > 0 and invoice_total < lo * 0.5:
            checks.append(Check("Historical range", "WARN",
                f"₹{invoice_total:,.0f} is unusually low for this vendor"))
        else:
            checks.append(Check("Historical range", "PASS",
                f"Amount within historical range for {vendor_data['canonical_name']}"))

    return checks, flags, amount_vs_po


# Convenience constructors so the body of run_checks stays readable
def Check(check: str, result: str, detail: str):
    from .agent import CheckResult
    return CheckResult(check=check, result=result, detail=detail)

def Flag(severity: str, message: str):
    from .agent import Flag as FlagDC
    return FlagDC(severity=severity, message=message)
