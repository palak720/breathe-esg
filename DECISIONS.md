# DECISIONS.md — Every Ambiguity Resolved

Each section describes an ambiguity I encountered, what I chose, and why.
At the end: what I'd ask the PM before building this in production.

---

## SAP: Which export format?

**Options considered:**
1. **IDoc** — SAP's native EDI format. Machine-readable, structured, complete. But requires an active SAP WE20 partner profile pointing at an external endpoint. A sustainability lead cannot configure this in a week. The SAP BASIS team has to be involved.
2. **OData (SAP Gateway)** — RESTful API, good for real-time. Requires RFC destination setup, Gateway activation, and service exposure. Again, BASIS team required. Not something you get in a 4-day client onboarding.
3. **BAPI** — Requires SAP RFC connectivity and credential management. Same problem.
4. **Flat file (SE16/ALV Grid export)** — The user runs SE16, hits Export → Spreadsheet, sends a CSV or XLSX. Zero IT involvement beyond giving the sustainability lead read access to the relevant tables.

**Chose: Flat file.** Not because it's technically superior (IDoc is) but because it matches how this data actually moves in practice at the onboarding stage. Every other format requires infrastructure we don't have yet.

**What I'd ask the PM:** "Does Acme Corp have a SAP BASIS team who can set up an IDoc partner profile or OData service? If yes, which tables or function modules do they expose? If no, who runs the SE16 export and how often?"

---

## SAP: Which table / report?

**Options:** MSEG (material documents / goods movements), EKPO+EKKO (purchase order line items), FAGLL03 (G/L account line items).

**Chose: FAGLL03 / general ledger approach** as the primary model, with MSEG as fallback.

**Rationale:** The G/L account is the most reliable signal for emission categorization. Every fuel purchase hits a specific G/L account regardless of how it was procured (purchase order, petty cash, credit card). Material documents (MSEG) only cover inventory-managed procurement. A company might buy diesel on a credit card — that never touches MSEG but always touches the G/L.

**Limitation:** G/L account mapping is client-specific. Our default mapping (GL 4030 = mobile fuel, 4020 = stationary fuel) uses a common German chart-of-accounts convention. A real client would need us to map their specific accounts.

---

## SAP: German vs English column headers?

SAP's default logon language is the user's system language. A German SAP installation will export "Menge" not "Quantity", "Buchungsdatum" not "Posting Date", "Werk" not "Plant".

**Chose:** Support both. The parser tries both German and English aliases for each column and records which language it detected in `job.metadata`. If neither matches, the column is simply absent and flagged.

---

## Utility: Which data acquisition method?

**Options:** PDF bill parsing, direct utility API (Green Button / ESPI), portal CSV export.

**Chose: Portal CSV export.**

- PDF: Varies enormously by utility. PG&E's PDF looks nothing like Con Edison's. Table extraction is brittle; OCR errors propagate silently into emission figures.
- Green Button / ESPI API: The standard exists (NAESB REQ.21) but adoption is incomplete. Requires OAuth2 setup with each utility individually, and a formal data-sharing agreement in some states. Not something you complete in a client onboarding sprint.
- Portal CSV: Every major US utility offers it. The facilities team already does this manually. We just formalize the handoff.

**What I'd ask the PM:** "Does Acme Corp have facilities in the EU? EU utilities rarely offer the same CSV exports — many require EDI or meter data management (MDM) system integration."

---

## Utility: How to handle billing periods ≠ calendar months?

Most reporting frameworks (CDP, GHG Protocol) want data by calendar year or calendar quarter. Utility bills run meter-read to meter-read (e.g. Feb 17 – Mar 17).

**Options:**
1. Prorate each bill into calendar months
2. Store exact billing period dates and let the reporting layer handle proration
3. Force the user to enter a "reporting period" date

**Chose: Option 2** — store exact dates, push proration to the reporting layer.

**Rationale:** Proration at ingestion time is irreversible. If we split a Feb 17–Mar 17 bill into "13 days of Feb + 17 days of Mar", we've made an assumption baked into the record. The raw data said Feb 17–Mar 17. The analyst should be able to see that. The reporting layer (not built in this prototype) can prorate at query time with full visibility into the assumption.

---

## Travel: Concur vs Navan?

Both have APIs. Both have CSV exports.

**Chose: CSV export** (same reasoning as utility — avoids OAuth2 setup during client onboarding).

**For format:** Targeted Concur's "Travel Itinerary Detail Export" because Concur has ~70% market share in enterprise travel management. Navan's export is structurally similar; the column aliases in the parser cover both.

---

## Travel: Radiative Forcing Index (RFI) for flights?

Aviation emissions at altitude have warming effects beyond CO2 (contrails, NOx, water vapor). Some frameworks apply an RFI multiplier of 1.9–3.0x to CO2 to account for this. Others (GHG Protocol Scope 3 standard) use CO2-only.

**Chose: No RFI multiplier.** Reason: DEFRA 2023 factors already include a "radiative forcing" uplift baked into their "with RF" factors. If we also apply an external RFI, we'd be double-counting. Since we use DEFRA factors, we get RF included automatically.

**What I'd ask the PM:** "Which reporting framework is Acme Corp reporting under? If they're using the GHG Protocol Scope 3 standard they can choose to exclude RF. If they're reporting to DEFRA/UK government they should include it. This changes the number."

---

## Travel: Flight distance — Haversine vs lookup table?

Flight distance is needed to compute passenger-km. The travel export gives IATA airport codes.

**Options:**
1. Great-circle distance (Haversine formula) from airport coordinates
2. Pre-built flight distance lookup table (OAG, ICAO)
3. Third-party distance API

**Chose: Haversine with detour factor (1.09x ICAO).** A lookup table of every city-pair would be 50MB+ and goes stale. A third-party API adds a runtime dependency and cost. Haversine is accurate to ±5% for most routes, which is acceptable for Scope 3 estimation (the GHG Protocol acknowledges activity data uncertainty of ±20-30% is normal).

The 1.09x detour factor is ICAO's standard allowance for non-great-circle routing.

---

## Review: Row-level vs batch approval?

**Options:** Approve individual rows, approve whole jobs at once, mixed.

**Chose: Both.** The UI supports:
- Individual row approval (expand row → Approve / Flag / Reject)
- Bulk approval via checkbox selection
- Lock all approved rows in a job (admin only)

**Rationale:** In practice, an analyst reviews flagged rows individually and approves clean rows in bulk. The flagged-only filter makes this workflow fast.

---

## Emission Factors: DEFRA vs EPA vs client-specific?

**Chose DEFRA 2023** as the default for all categories.

**Rationale:** DEFRA publishes annually, is widely accepted in UK/EU sustainability reporting, and covers all three source types (fuel, electricity, travel) in a single document. EPA eGRID is used for US electricity specifically (more accurate for US grid than DEFRA's UK grid average).

**Limitation:** The electricity factor we use (0.1749 kg CO2e/kWh) is the US national average. The correct factor depends on the NERC subregion of the meter. A meter in California (WECC) has a much lower factor than one in the Midwest (MRO). We flag this in SOURCES.md.

---

## Authentication: JWT vs session?

**Chose: JWT** (via djangorestframework-simplejwt).

**Rationale:** React frontend is decoupled from Django. Session auth requires cookie handling and same-origin setup. JWT works naturally across origins and is stateless — no session table needed. The 8-hour access token lifetime is appropriate for a day-shift analyst.

---

## What I'd ask the PM before building this for real

1. **Which reporting framework?** GHG Protocol Corporate Standard? CDP? TCFD? ISO 14064? Each has different boundary rules and materiality thresholds.
2. **What's Acme Corp's fiscal year?** Reporting periods may not be calendar years.
3. **Which SAP tables does Acme's team have SE16 access to?** MSEG, EKPO, FAGLL03 — each requires different authorization objects.
4. **Does Acme have non-US facilities?** Changes grid emission factors, travel factors, and may require EU Taxonomy compliance.
5. **Do they have an existing chart of accounts mapping?** The GL→category mapping is completely client-specific.
6. **What's the audit deadline?** Determines whether we need a "lock" mechanism at all in the first sprint.
7. **Is there a previous year's data?** Year-over-year comparison is often the first thing auditors ask for.
