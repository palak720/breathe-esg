# TRADEOFFS.md — Three Things Deliberately Not Built

---

## 1. Async task queue (Celery / RQ)

**What it is:** File parsing happens synchronously in the upload API view. For a large SAP export (10,000+ rows), this blocks the request thread for several seconds.

**Why not built:** Adding Celery requires a message broker (Redis or RabbitMQ), a worker process, and deployment configuration for all three. For the prototype, files are small and the parse time is under 2 seconds. The synchronous path is simpler, easier to debug, and easier to deploy to Railway.

**What breaks without it:** A 50,000-row SAP export (realistic for a large client) would take 30-60 seconds and likely hit a gunicorn timeout. The upload would appear to hang. The fix is exactly one step: move `parser.parse(...)` and the bulk_create into a Celery task, change the upload endpoint to return immediately with `job.status = "PENDING"`, and poll for completion.

**Decision:** Right call for a 4-day prototype. Wrong call for production.

---

## 2. Supplier / facility master data tables

**What they are:** A `Facility` table (with coordinates, NERC grid region, country, fuel types used) and a `Supplier` table (with disclosed emission factors for Scope 3 Category 1). These would turn the `facility_code` string field into a proper FK with lookup.

**Why not built:**
- **Facility table:** Would require either (a) the client to upload a facility master, or (b) us to manually map plant codes. Plant DE01 in SAP means nothing without a lookup. We store it as a string and surface it to the analyst. Adding the table would add a migration, a CRUD API, a UI page, and a client onboarding step — all before we've even proved the ingestion pipeline works.
- **Supplier factors:** Scope 3 Category 1 ideally uses supplier-disclosed emission factors (their Scope 1+2 per unit of product). In practice, <5% of suppliers have disclosed this. The fallback is always spend-based. Building the infrastructure for supplier factors before you have any supplier data is premature.

**What breaks without it:** Two things:
1. The electricity emission factor uses the US national average instead of the correct NERC subregion. This can be 2-3x off for clean-energy states. A Facility table with `nerc_region` would fix this.
2. Scope 3 procurement uses spend-based factors throughout, which is a recognized weakness in the GHG Protocol framework but unavoidable without supplier data.

---

## 3. Reporting / export layer

**What it is:** A "generate report" feature that produces a formatted Scope 1/2/3 summary table, a year-over-year comparison, and an export to CSV or PDF suitable for handing to an auditor or submitting to CDP.

**Why not built:** The assignment asks for ingestion and review. The reporting layer sits downstream of the review lock. Building it would require: (a) defining the reporting framework (GHG Protocol vs CDP vs ISO 14064 — each has different line items), (b) handling the billing period proration problem (utility bills don't align with calendar quarters), (c) deciding how to handle missing co2e_kg rows in totals (exclude? flag? impute?). Each of these is a meaningful product decision that should be validated with the client before building.

**What exists instead:** The dashboard summary view (`/api/records/summary/`) returns CO2e by scope and status counts. This is the minimum needed to answer "are we done reviewing?" It's not a report — it's a progress meter.

**What a real report needs that we don't have:** Period normalization (prorating cross-month utility bills into calendar quarters), handling of `null` co2e_kg rows, organizational boundary definition (operational control vs equity share), and a templated output format the auditor will accept.

---

## Honorable Mention: What else was cut

These are things I thought about but didn't start:

- **Re-ingestion / file diff:** If a client re-uploads a corrected SAP file, we have no deduplication logic. A second upload creates duplicate records. The right fix is a fingerprint on `(org, source_row_ref, job.source_type)` and an upsert. Not built because it requires defining what "same row" means across two versions of a file, which is source-specific.

- **Email notifications:** Analysts should get an email when a new job is ingested and waiting for review. Not built — adding Django email config and SMTP credentials is setup work that doesn't demonstrate judgment about the data model.

- **Fine-grained permissions:** The role system (ANALYST / ADMIN / AUDITOR) is enforced at the view level but not at the row level. An analyst at one org can't see another org's data (multi-tenancy enforced), but an analyst could technically approve records from a job they uploaded themselves. Segregation of duties (the person who uploads cannot approve) is a real audit control that we haven't implemented.
