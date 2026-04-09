"""
Invoice Processing Agent — CoVector AI Assignment
Processes vendor invoices end-to-end: extraction → validation → routing decision.
"""

import json
import re
import os
from dataclasses import dataclass, field, asdict
from typing import Optional
from dotenv import load_dotenv
from google import genai  # Modern SDK 2.0

from .reference_data import VENDOR_REGISTRY, OPEN_POS, PAID_INVOICES, APPROVAL_THRESHOLDS
from .validator import run_checks

# 1. Load the .env file correctly
load_dotenv()

# 2. Configure Gemini Client
# Ensure your .env has: GOOGLE_API_KEY=your_key
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

SYSTEM_PROMPT = """You are an invoice extraction specialist for a mid-sized Indian manufacturing company.

Given raw invoice text, extract ALL available fields and return ONLY valid JSON in this exact schema:

{
  "invoice_number": "string or null",
  "vendor_name": "string or null",
  "invoice_date": "string or null",
  "due_date": "string or null",
  "po_reference": "string or null",
  "vendor_gstin": "string or null",
  "line_items": [{"description": "string", "amount": number}],
  "subtotal_inr": number or null,
  "gst_rate_stated": "string or null",
  "gst_inr": number or null,
  "total_inr": number or null,
  "bank_details_present": boolean,
  "additional_notes": "string or null"
}

Rules:
- All INR amounts as plain numbers (no commas, no currency symbols)
- If a field is genuinely absent, return null — never guess
- Compute nothing; extract only what is stated
- Return ONLY the JSON object, no preamble or explanation
"""

@dataclass
class ExtractionResult:
    invoice_number: Optional[str] = None
    vendor_name: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    po_reference: Optional[str] = None
    vendor_gstin: Optional[str] = None
    line_items: list = field(default_factory=list)
    subtotal_inr: Optional[float] = None
    gst_rate_stated: Optional[str] = None
    gst_inr: Optional[float] = None
    total_inr: Optional[float] = None
    bank_details_present: bool = False
    additional_notes: Optional[str] = None

@dataclass
class CheckResult:
    check: str
    result: str  # PASS | FAIL | WARN | SKIP
    detail: str

@dataclass
class Flag:
    severity: str  # danger | warn | info
    message: str

@dataclass
class ProcessingOutput:
    extracted: ExtractionResult
    checks: list[CheckResult]
    flags: list[Flag]
    verdict: str           # APPROVE | FLAG | HOLD
    confidence: float      # 0.0–1.0
    reasoning: str
    reviewer_action: str
    amount_vs_po: dict

def extract_fields(invoice_text: str) -> ExtractionResult:
    """Call Gemini to extract structured fields from raw invoice text."""
    # Updated syntax for google-genai 2.0
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"{SYSTEM_PROMPT}\n\nExtract fields from this invoice:\n\n{invoice_text}"
    )
    
    raw = response.text.strip()
    # Strip markdown fences
    raw = re.sub(r"```json|```", "", raw).strip()
    
    data = json.loads(raw)
    return ExtractionResult(**{k: data.get(k) for k in ExtractionResult.__dataclass_fields__})

def determine_verdict(
    extracted: ExtractionResult,
    checks: list[CheckResult],
    flags: list[Flag]
) -> tuple[str, float, str, str]:
    """Apply the approval policy and return (verdict, confidence, reasoning, reviewer_action)."""
    danger_flags = [f for f in flags if f.severity == "danger"]
    warn_flags   = [f for f in flags if f.severity == "warn"]

    hold_reasons = [f.message for f in danger_flags]
    flag_reasons = [f.message for f in warn_flags]

    if hold_reasons:
        verdict = "HOLD"
        confidence = 0.95
        reasoning = f"Critical issues found: {'; '.join(hold_reasons)}."
        reviewer_action = f"ESCALATE: {hold_reasons[0]}. Contact CFO."
    elif flag_reasons:
        verdict = "FLAG"
        confidence = 0.80
        reasoning = f"Review required: {'; '.join(flag_reasons)}."
        reviewer_action = f"REVIEW REQUIRED: {flag_reasons[0]}. Verify with vendor."
    else:
        verdict = "APPROVE"
        confidence = 0.93
        reasoning = "Invoice passes all validation checks."
        reviewer_action = "AUTO-APPROVE: Post to accounts payable."

    return verdict, confidence, reasoning, reviewer_action

def process_invoice(invoice_text: str) -> ProcessingOutput:
    """Full pipeline: extract → validate → route."""
    extracted = extract_fields(invoice_text)
    checks, flags, amount_vs_po = run_checks(extracted, VENDOR_REGISTRY, OPEN_POS, PAID_INVOICES)
    verdict, confidence, reasoning, reviewer_action = determine_verdict(extracted, checks, flags)

    return ProcessingOutput(
        extracted=extracted,
        checks=checks,
        flags=flags,
        verdict=verdict,
        confidence=confidence,
        reasoning=reasoning,
        reviewer_action=reviewer_action,
        amount_vs_po=amount_vs_po,
    )

def format_output(result: ProcessingOutput) -> dict:
    """Serialise to plain dict for JSON output or API response."""
    return {
        "verdict": result.verdict,
        "confidence": round(result.confidence, 2),
        "reasoning": result.reasoning,
        "reviewer_action": result.reviewer_action,
        "extracted": asdict(result.extracted),
        "flags": [asdict(f) for f in result.flags],
        "checks": [asdict(c) for c in result.checks],
        "amount_vs_po": result.amount_vs_po,
    }