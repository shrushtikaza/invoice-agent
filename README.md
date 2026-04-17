# Invoice Processing Agent

An AI agent that processes vendor invoices end-to-end: extracts structured fields, validates against reference data, and routes to approve, flag, or hold - with enough context that a finance reviewer can act immediately rather than re-examine the invoice from scratch.

Built for the CoVector AI take-home assignment.

---

## Quick start

```bash
git clone https://github.com/your-username/invoice-agent
cd invoice-agent
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here

# Run a sample scenario
python run.py --sample duplicate
python run.py --sample taxerror
python run.py --sample overage

# Process your own invoice
python run.py path/to/invoice.txt

# JSON output for downstream use
python run.py --sample routine --json

# Run validation tests (no API key required)
python tests/test_agent.py
```

There is also a browser-based UI (a React artifact) included in this repo. See `ui/README.md`.

---

## Architecture

```
invoice text
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Extraction  (Gemini API)         │
│  Extract fields into typed schema. Do not compute anything. │
└────────────────────────────┬────────────────────────────────┘
                             │ ExtractionResult
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: Validation  (rule-based, deterministic)            │
│  7 explicit checks against reference data.                  │
│  Each check is PASS / FAIL / WARN / SKIP.                   │
└────────────────────────────┬────────────────────────────────┘
                             │ checks[], flags[]
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: Routing  (priority-ordered policy)                 │
│  HOLD if any danger flags. FLAG if any warn flags.          │
│  APPROVE if all checks pass.                                │
└────────────────────────────┬────────────────────────────────┘
                             │ ProcessingOutput
                             ▼
                  Structured output for reviewer
```

The two roles are intentionally separated. Claude extracts; rules decide. This makes the decision logic auditable - a finance reviewer, or the CFO, can read `validator.py` and understand exactly what the agent is checking. There is no black box in the routing decision.

---

## Reference data: what the agent has access to, and why

I gave the agent three datasets:

**1. Vendor registry** - name, status (approved / watch / new / suspended), category, GSTIN, and the typical billing range for each vendor.

The typical range check is the one people often skip. It catches something the PO check misses: a vendor who has an open PO for ₹3L billing ₹7L is flagged by the PO check. But a vendor with no PO reference billing ₹7L when their typical invoices run ₹50K–2L - that only gets caught if you know what normal looks like. That pattern matters.

I didn't add contract terms, payment terms, or SLA data. Those would be valuable for a more sophisticated version, but they require ERP integration and are unnecessary for the core routing decision.

**2. Open purchase orders** - PO number, vendor, total amount, remaining balance, and status.

The balance field matters more than the total. A PO for ₹5L that's already had ₹4L invoiced against it has a balance of ₹1L - that's the comparison number. Using total instead of balance would cause false approvals on partially-consumed POs.

**3. Payment history (90-day window)** - invoice numbers that have already been paid.

This is the duplicate detection dataset. The window is 90 days because the realistic scenario isn't an invoice submitted twice in a week - it's an invoice submitted weeks or months after the original was paid, with the vendor claiming non-receipt. A longer window would increase false positives; 90 days covers the vast majority of real duplicate attempts.

I deliberately excluded: GL codes, budget headings, bank account details. Each of those adds value but also adds failure modes. The agent I've built will give a confident, well-reasoned answer with three clean datasets. Adding five more datasets with partial coverage would introduce more ambiguity, not less.

---

## Approval logic: where the line sits, and why

There are four routing outcomes:

| Decision | Trigger | Reasoning |
|----------|---------|-----------|
| **APPROVE** | Known vendor, amount ≤ PO+10%, correct tax, no duplicate | Routine. The finance team shouldn't touch it. |
| **FLAG** | Amount 10–40% over PO; new/watch-list vendor; tax error; missing fields | Needs human eyes but probably fine. Give the reviewer the specific issue. |
| **HOLD** | Amount >40% over PO or >₹10L; suspended vendor; duplicate invoice number | Do not pay until a human clears it. |

**The 10% tolerance** on PO matching accounts for freight charges, loading/unloading fees, and GST rounding - all of which can legitimately push an invoice slightly over the PO value without indicating a problem.

**The 40% threshold for HOLD** (versus FLAG) was set to distinguish "vendor added line items I should verify" from "something is materially wrong here." A 15% variance is worth a look. A 45% variance - like receiving a ₹1.2L invoice against a ₹0.8L PO balance - needs an explanation before any payment proceeds.

**The ₹10L absolute ceiling** is independent of PO matching. Even a perfectly clean invoice for ₹12L from a known, approved vendor should have a human sign off on it. At ₹200Cr annual revenue, 300 invoices/month, the average invoice is around ₹55K–60K. A ₹10L+ invoice is unusual by an order of magnitude and warrants attention regardless of what the PO says.

**New vendors are flagged, not held.** The agent cannot verify a new vendor's bank account, GST registration, or legitimacy. But it also shouldn't block all new vendor invoices - the company presumably vetted them during onboarding. Flagging gives the finance team a nudge to verify, without treating every new vendor as a suspect.

**Suspended vendors are held, always.** There is no legitimate reason to pay a suspended vendor. The agent does not try to be clever about this; it stops the invoice immediately.

---

## Ambiguity handling

**Missing fields:** The agent distinguishes between invoices missing one or two fields (FLAG - can often be obtained from the vendor) and invoices missing most mandatory fields (HOLD - cannot process). An invoice with no number, no date, and no vendor name is not an invoice the agent can route at all.

**No PO reference:** Flagged with a clear message. Some invoices legitimately arrive without PO references (recurring services, small purchases). The agent doesn't block them - it asks a human to verify.

**Unknown vendor:** Flagged for verification. The agent cannot distinguish a legitimate new vendor from a fraudulent one. It doesn't pretend to.

**Ambiguous amounts:** If the agent cannot parse the total (non-standard formatting, mixed currencies, OCR artifacts), it sets the field to null and skips all amount-dependent checks with SKIP rather than FAIL. A SKIP triggers a flag explaining what couldn't be verified.

**Tax errors:** The agent computes expected GST from the stated rate and subtotal. A 2% tolerance accounts for paise rounding on large invoices. Above 2%, it flags with the specific discrepancy - not just "tax error" but "stated GST ₹12,000, expected ₹8,462 at 5% - verify with vendor." The reviewer has the numbers; they don't need to redo the arithmetic.

---
 
## One thing I observed that I did not expect
 
When I ran the tax error scenario (the Rajput Power Systems invoice), the agent correctly flagged the discrepancy - but it also flagged the vendor's watch-list status in the same output. Two separate flags, both accurate. What I hadn't expected was how the *combination* felt different from either flag alone.
 
A tax calculation error on a routine invoice from a trusted vendor reads as probably a clerical mistake. A tax calculation error on a watch-list vendor reads as something worth taking seriously. The agent produces both flags independently and lets the reviewer see them together - but it doesn't synthesise them into a single escalated concern. That's probably correct behaviour for a prototype, but it made me notice that the severity of a flag is context-dependent in ways that a flat flag list doesn't capture.

## Project structure

```
invoice-agent/
├── src/
│   ├── agent.py          # Main pipeline: extract → validate → route
│   ├── validator.py      # 7 explicit rule-based checks
│   ├── reference_data.py # Vendor registry, open POs, payment history
│   └── __init__.py
├── tests/
│   └── test_agent.py     # 8 unit tests (no API calls required)
├── run.py                # CLI entry point
├── requirements.txt
└── README.md
```
