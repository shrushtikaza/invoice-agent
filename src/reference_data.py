"""
Reference data for the invoice agent.

Design rationale:
  These three datasets — vendor registry, open POs, and payment history — are the minimum
  needed to make meaningful routing decisions. Vendor registry tells us whether a supplier is
  known and trusted. Open POs tell us what we agreed to pay. Payment history lets us detect
  duplicates. Everything else (line-item matching, GL coding, budget checks) is valuable but
  requires ERP integration beyond the scope of this prototype.

  In production these would be fetched from an ERP (SAP, Tally, Zoho Books) or a finance
  data warehouse. Here they're in-memory dicts that are straightforward to swap out.
"""

# ---------------------------------------------------------------------------
# VENDOR REGISTRY
# ---------------------------------------------------------------------------
# status: "approved" | "watch" | "new" | "suspended"
# typical_range_inr: (min, max) — used for anomaly detection
# category: drives GST rate expectations
VENDOR_REGISTRY = {
    "sharma steel traders": {
        "canonical_name": "Sharma Steel Traders",
        "status": "approved",
        "category": "raw_materials",
        "typical_range_inr": (200_000, 800_000),
        "gstin": "27AABCS1429B1ZP",
    },
    "fastmove logistics": {
        "canonical_name": "FastMove Logistics Pvt. Ltd.",
        "status": "approved",
        "category": "logistics",
        "typical_range_inr": (50_000, 300_000),
        "gstin": "29AACFL9873C1ZR",
    },
    "fastmove logistics pvt. ltd.": {
        "canonical_name": "FastMove Logistics Pvt. Ltd.",
        "status": "approved",
        "category": "logistics",
        "typical_range_inr": (50_000, 300_000),
        "gstin": "29AACFL9873C1ZR",
    },
    "kapoor maintenance": {
        "canonical_name": "Kapoor Maintenance Services",
        "status": "approved",
        "category": "maintenance",
        "typical_range_inr": (20_000, 150_000),
        "gstin": "27AACKM4421F1ZT",
    },
    "kapoor maintenance services": {
        "canonical_name": "Kapoor Maintenance Services",
        "status": "approved",
        "category": "maintenance",
        "typical_range_inr": (20_000, 150_000),
        "gstin": "27AACKM4421F1ZT",
    },
    "anand office supplies": {
        "canonical_name": "Anand Office Supplies",
        "status": "approved",
        "category": "office",
        "typical_range_inr": (5_000, 40_000),
        "gstin": None,
    },
    "rajput power systems": {
        "canonical_name": "Rajput Power Systems",
        "status": "watch",
        "category": "utilities",
        "typical_range_inr": (100_000, 400_000),
        "gstin": "27AACRP2291G1ZV",
    },
    "singh packaging co.": {
        "canonical_name": "Singh Packaging Co.",
        "status": "approved",
        "category": "packaging",
        "typical_range_inr": (30_000, 200_000),
        "gstin": None,
    },
    "singh packaging": {
        "canonical_name": "Singh Packaging Co.",
        "status": "approved",
        "category": "packaging",
        "typical_range_inr": (30_000, 200_000),
        "gstin": None,
    },
    "galaxy chemicals": {
        "canonical_name": "Galaxy Chemicals",
        "status": "suspended",
        "category": "raw_materials",
        "typical_range_inr": (0, 0),
        "gstin": None,
    },
    "metro catering services": {
        "canonical_name": "Metro Catering Svcs.",
        "status": "new",
        "category": "canteen",
        "typical_range_inr": (15_000, 50_000),
        "gstin": None,
    },
    "metro catering svcs.": {
        "canonical_name": "Metro Catering Svcs.",
        "status": "new",
        "category": "canteen",
        "typical_range_inr": (15_000, 50_000),
        "gstin": None,
    },
}

# ---------------------------------------------------------------------------
# OPEN PURCHASE ORDERS
# ---------------------------------------------------------------------------
# balance_inr: remaining unmatched amount
OPEN_POS = {
    "PO-2025-0041": {
        "vendor_key": "sharma steel traders",
        "po_amount_inr": 500_000,
        "balance_inr": 500_000,
        "description": "HR Steel Coils, April batch",
        "status": "open",
    },
    "PO-2025-0039": {
        "vendor_key": "fastmove logistics",
        "po_amount_inr": 120_000,
        "balance_inr": 80_000,
        "description": "Road freight services, Q1",
        "status": "partial",
    },
    "PO-2025-0037": {
        "vendor_key": "kapoor maintenance",
        "po_amount_inr": 75_000,
        "balance_inr": 75_000,
        "description": "Quarterly preventive maintenance",
        "status": "open",
    },
    "PO-2025-0035": {
        "vendor_key": "singh packaging",
        "po_amount_inr": 95_000,
        "balance_inr": 95_000,
        "description": "Corrugated boxes, Q1",
        "status": "open",
    },
    "PO-2025-0033": {
        "vendor_key": "rajput power systems",
        "po_amount_inr": 250_000,
        "balance_inr": 250_000,
        "description": "Electricity supply, Q1",
        "status": "open",
    },
    "PO-2025-0031": {
        "vendor_key": "anand office supplies",
        "po_amount_inr": 22_000,
        "balance_inr": 12_000,
        "description": "Stationery and printer supplies",
        "status": "partial",
    },
}

# ---------------------------------------------------------------------------
# RECENTLY PAID INVOICES (duplicate detection window: 90 days)
# ---------------------------------------------------------------------------
PAID_INVOICES = {
    "INV-2025-0712": {
        "vendor_key": "kapoor maintenance",
        "amount_inr": 74_930,
        "payment_date": "2025-03-25",
    },
    "INV-2025-0652": {
        "vendor_key": "fastmove logistics",
        "amount_inr": 95_200,
        "payment_date": "2025-03-10",
    },
    "STP-2025-089": {
        "vendor_key": "singh packaging",
        "amount_inr": 88_400,
        "payment_date": "2025-02-28",
    },
    "RPS-2025-0195": {
        "vendor_key": "rajput power systems",
        "amount_inr": 165_000,
        "payment_date": "2025-03-05",
    },
    "AOS-2025-041": {
        "vendor_key": "anand office supplies",
        "amount_inr": 10_200,
        "payment_date": "2025-02-20",
    },
}

# ---------------------------------------------------------------------------
# APPROVAL THRESHOLDS
# ---------------------------------------------------------------------------
# These encode the CFO's implicit policy. Documented explicitly here so they
# are transparent and auditable rather than buried in code logic.
APPROVAL_THRESHOLDS = {
    # Auto-approve if invoice amount is within this % of PO (accounts for freight, rounding)
    "po_tolerance_pct": 0.10,

    # Flag (finance review) if variance between invoice and PO is above this
    "po_warn_pct": 0.10,

    # Hold (CFO review) if variance is above this — or if absolute amount exceeds cap
    "po_hold_pct": 0.40,

    # Absolute cap: any invoice above this goes to CFO regardless of PO match
    "absolute_hold_inr": 1_000_000,  # ₹10 lakh

    # Tax tolerance: flag if computed vs stated GST differs by more than this %
    "tax_tolerance_pct": 0.02,

    # GST rates by vendor category (approximate; actual depends on HSN code)
    "expected_gst_rates": {
        "raw_materials": 0.18,
        "logistics": 0.12,
        "maintenance": 0.18,
        "office": 0.12,
        "utilities": 0.05,
        "packaging": 0.12,
        "canteen": 0.05,
    },
}
