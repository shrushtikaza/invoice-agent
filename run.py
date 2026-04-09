#!/usr/bin/env python3
"""
CLI for the invoice processing agent.

Usage:
  python run.py invoice.txt
  python run.py --sample duplicate
  cat invoice.txt | python run.py -
"""

import sys
import json
import argparse

from src.agent import process_invoice, format_output

SAMPLES = {
    "routine": """INVOICE
Invoice No: INV-2025-1042
Date: 07 April 2025
Due Date: 07 May 2025

Vendor: Sharma Steel Traders
GSTIN: 27AABCS1429B1ZP

Description: HR Steel Coils (IS 2062 Grade A) — 10 MT
Rate: ₹45,000/MT × 10 MT = ₹4,50,000
GST @18%: ₹81,000
Total: ₹5,31,000

Reference PO: PO-2025-0041""",

    "overage": """INVOICE
Invoice No: INV-2025-0781
Date: 06 April 2025

Vendor: FastMove Logistics Pvt. Ltd.
GSTIN: 29AACFL9873C1ZR

Road freight, April batch 1: ₹42,000
Additional loading charges: ₹18,000
Fuel surcharge: ₹22,000
Handling: ₹10,000
Subtotal: ₹92,000
GST @12%: ₹11,040
Total: ₹1,03,040

Reference PO: PO-2025-0039""",

    "duplicate": """INVOICE
Invoice No: INV-2025-0712
Date: 06 April 2025

Vendor: Kapoor Maintenance Services
GSTIN: 27AACKM4421F1ZT

Quarterly preventive maintenance — compressors × 3:
Labour: ₹35,000  Spares: ₹28,500
Subtotal: ₹63,500  GST @18%: ₹11,430
Total: ₹74,930

Reference PO: PO-2025-0037""",

    "taxerror": """INVOICE
Invoice No: RPS-2025-0229
Date: 04 April 2025

Vendor: Rajput Power Systems
GSTIN: 27AACRP2291G1ZV

Monthly electricity — March 2025
18,500 kWh @ ₹8.50 = ₹1,57,250
Fixed charges: ₹12,000
Subtotal: ₹1,69,250
GST @5%: ₹12,000
Total: ₹1,81,250

Reference PO: PO-2025-0033""",

    "newvendor": """INVOICE
Invoice No: ZEN-2025-104
Date: 05 April 2025

Vendor: Zenith Tooling Solutions
GSTIN: 27AABCZ0011D1ZQ

Precision cutting tools (carbide inserts, 5 sets): ₹1,25,000
GST @18%: ₹22,500
Total: ₹1,47,500""",

    "incomplete": """INVOICE

Vendor: Singh Packaging Co.

Corrugated boxes, March order — 2,000 units
Price: ₹48,000
GST: ₹8,640
Total: ₹56,640""",
}


def main():
    parser = argparse.ArgumentParser(description="Invoice Processing Agent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("file", nargs="?", help="Path to invoice text file (use - for stdin)")
    group.add_argument("--sample", choices=list(SAMPLES.keys()), help="Run a built-in sample invoice")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted report")
    args = parser.parse_args()

    if args.sample:
        invoice_text = SAMPLES[args.sample]
        print(f"[Using sample: {args.sample}]\n")
    elif args.file == "-":
        invoice_text = sys.stdin.read()
    else:
        with open(args.file, "r", encoding="utf-8") as f:
            invoice_text = f.read()

    print("Processing invoice...\n")
    result = process_invoice(invoice_text)
    output = format_output(result)

    if args.json:
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    # Pretty-print report
    v = output["verdict"]
    v_emoji = {"APPROVE": "✅", "FLAG": "⚠️ ", "HOLD": "🔴"}.get(v, "")
    ext = output["extracted"]

    print("=" * 60)
    print(f"  {v_emoji} VERDICT: {v}  (confidence: {output['confidence']*100:.0f}%)")
    print("=" * 60)
    print()
    print(f"  Vendor:   {ext.get('vendor_name') or '—'}")
    print(f"  Invoice:  {ext.get('invoice_number') or '—'}")
    print(f"  Date:     {ext.get('invoice_date') or '—'}")
    print(f"  PO ref:   {ext.get('po_reference') or '—'}")
    print(f"  Total:    ₹{ext.get('total_inr'):,.0f}" if ext.get('total_inr') else "  Total:    —")
    print()

    avp = output.get("amount_vs_po", {})
    if avp.get("variance_pct") is not None:
        sign = "+" if avp["variance_pct"] > 0 else ""
        print(f"  PO variance: {sign}{avp['variance_pct']:.1f}%")
        print()

    print("CHECKS:")
    for c in output["checks"]:
        sym = {"PASS": "✓", "FAIL": "✗", "WARN": "!", "SKIP": "—"}.get(c["result"], "?")
        print(f"  [{sym}] {c['check']}: {c['detail']}")
    print()

    if output["flags"]:
        print("FLAGS:")
        for f in output["flags"]:
            icon = {"danger": "🔴", "warn": "🟡", "info": "🔵"}.get(f["severity"], "•")
            print(f"  {icon} {f['message']}")
        print()

    print(f"REASONING:\n  {output['reasoning']}")
    print()
    print(f"ACTION REQUIRED:\n  {output['reviewer_action']}")
    print()


if __name__ == "__main__":
    main()
