# SOURCES.md — Research Behind Each Data Source

---

## Source 1: SAP — Fuel & Procurement

### What I researched

SAP's data extraction landscape has several layers:
- **IDocs** (Intermediate Documents): SAP's native EDI format. Structured, typed, versioned. Used for system-to-system integration. Requires WE20 partner profile configuration.
- **BAPIs** (Business Application Programming Interfaces): RFC-callable function modules for specific business operations. Read-only BAPIs exist for most master data.
- **OData / SAP Gateway**: RESTful APIs exposed via SAP NetWeaver Gateway. Modern approach, well-documented, but requires BASIS team setup.
- **SE16 / ALV Grid export**: Transaction SE16 is the SAP table browser. Any user with S_TABU_DIS authorization can browse a table and export it as CSV, spreadsheet, or text. This is how sustainability teams actually get data.

Key tables:
- **MSEG**: Material document segments — every goods movement (goods receipt, goods issue, transfer)
- **MKPF**: Material document headers
- **EKPO/EKKO**: Purchase order line items and headers
- **FAGLL03**: G/L account line item display — every financial posting by GL account
- **MARA/MAKT**: Material master (descriptions, material groups)
- **LFA1**: Vendor master

### What I learned

1. **SAP unit codes (MEINS) are not ISO.** SAP has its own internal unit of measure table (T006). Key gotchas:
   - `TO` = metric ton (not "TO" as in "to")
   - `M3` = cubic meters (used for both liquids and gas — ambiguous for natural gas vs diesel)
   - `KWH` = kilowatt-hour (SAP spells it without the dash)
   - `GAL` = US gallon (SAP also has `GL` in some locales)
   - `ST` = Stück (piece) — common in German, unmappable to energy units

2. **Date format depends on SAP user locale.** German: DD.MM.YYYY. English: MM/DD/YYYY. SAP internal format (used in IDoc and some reports): YYYYMMDD.

3. **Column headers depend on logon language.** German installation exports "Menge" (quantity), "Werk" (plant), "Buchungsdatum" (posting date). English installation exports English headers. Some installations export German headers even with English logon if the report was created in German.

4. **GL account categorization is client-specific.** There is no universal SAP chart of accounts. German companies often use DATEV SKR04, which assigns fuel accounts in the 4000-4299 range. US companies use their own. We use a common German convention as default and flag unmapped accounts.

5. **Plant codes mean nothing without a lookup table.** "DE01" is meaningful only to the client. A real deployment needs the client to provide a plant-to-facility mapping.

### What our sample data looks like and why

```
Posting Date, Plant, G/L Account, Cost Center, Material Group, Quantity, ME, Net Value, WAERS, Vendor, Short Text, Belegnummer
20240115, DE01, 4030, CC-FLEET, 002, 1250.000, L, 1875.00, EUR, SHELL-DE, Diesel fleet refuel Jan, 5000012301
20240115, DE01, 4021, CC-FACIL, 001, 8.500, TO, 8075.00, EUR, HEIZOEL-AG, Heating oil Jan boiler room, 5000012302
20240201, US02, 4031, CC-FLEET, 002, 840.000, GAL, 3024.00, USD, CHEVRON-US, Petrol fleet Feb US site, 5000012310
```

- **English headers** (not German) — most exports from a multinational SAP client with English as system language
- **Mixed units** (L, TO, GAL) — realistic; SAP doesn't enforce unit consistency across plants or countries
- **Two plants** (DE01, US02) — realistic for a company with EU and US operations
- **Two currencies** (EUR, USD) — realistic; spend normalization not in scope for this prototype
- **One procurement row** (GL 5001) — tests the PROCUREMENT category fallback
- **One intentionally bad date row** — tests error handling
- **One outlier quantity row** — tests the VALUE_OUTLIER_HIGH flag

### What would break in a real deployment

1. **The GL→category mapping would be wrong** for any client not using the German SKR04 chart of accounts. First thing to do: get the client's chart of accounts and rebuild the mapping.
2. **M3 for gas is ambiguous.** M3 of natural gas ≠ M3 of diesel. The parser converts M3 to liters (1000:1), which is correct for liquids but wrong for gas (natural gas in M3 needs a density factor and a heat value conversion). We flag nothing here, which is a bug.
3. **Currency not normalized.** SAP rows have a WAERS (currency) field. If a US plant pays in USD and a German plant pays in EUR, spend-based CO2e comparisons require FX normalization at a specific reporting date. We don't do this.
4. **Plant codes without a master table** mean facility_name is always blank and country_code is always blank. Location-based electricity factors require knowing the country.

---

## Source 2: Utility — Electricity

### What I researched

US utility data access has three tiers:
- **Green Button Connect (GBC)**: NAESB REQ.21 standard. OAuth2-based API access to interval meter data. Supported by PG&E, SCE, SDG&E, and ~50 others. Requires registering as a "Third Party" with each utility and completing a data-sharing agreement.
- **Direct utility APIs**: Some large utilities (ConEd, National Grid) have proprietary APIs. Each requires separate integration.
- **Portal CSV export**: Every major US utility offers "Download Usage" or "Export Data" in their account portal. No API credentials needed.

I looked at:
- PG&E's Green Button Download format (XML, interval data)
- PG&E's portal CSV export ("Usage Details" tab)
- Con Edison's "Energy Usage Summary" CSV
- ComEd's "Usage Data" export
- National Grid's "Account History" CSV

### What I learned

1. **Billing periods straddle calendar months.** Meter reads happen on a fixed day of the month (often not the 1st). A "January bill" might be Dec 20 – Jan 19. This matters for quarterly reporting — you can't just use the billing month.

2. **Column names are not standardized across utilities.** PG&E uses "Usage (kWh)". Con Edison uses "Net Usage kWh". ComEd uses "kWh Used". Our parser has aliases for all common variants.

3. **Demand charges (kW) are separate from consumption (kWh).** Emission calculations use kWh only. The kW column is often present and must not be confused with kWh.

4. **Some utilities prepend account info before the CSV header.** PG&E's export has 2-3 lines of account information before the actual column headers start. The parser skips these.

5. **Estimated reads produce anomalous billing periods.** When a utility can't access a meter, they estimate the bill. This sometimes produces a double-length period the next month (when they read the actual meter and reconcile). We flag periods > 35 days.

6. **Demand charge credits and solar export show as negative kWh.** A facility with rooftop solar may export to the grid and receive a credit that appears as negative usage. We flag these rather than error on them.

### What our sample data looks like and why

```
Account Number, Meter ID, Service Address, Billing Start Date, Billing End Date, Usage (kWh), Peak Demand (kW), Amount ($), Rate Schedule
ACC-004821, MTR-A1023, 1 Market St San Francisco CA, 12/17/2023, 01/17/2024, 142500, 285, 18525.00, E-19
ACC-004821, MTR-A1023, 1 Market St San Francisco CA, 01/17/2024, 02/17/2024, 138200, 276, 17966.00, E-19
ACC-004821, MTR-A1023, 1 Market St San Francisco CA, 02/17/2024, 02/24/2024, 32000, 280, 4160.00, E-19
ACC-004821, MTR-B2041, 500 Howard St San Francisco CA, 12/20/2023, 02/05/2024, 298000, 410, 38740.00, E-20
```

- **Two meters** (A1023, B2041) — two buildings, realistic for a company with multiple locations
- **Billing dates on the 17th / 20th** — deliberately not the 1st; tests the period handling
- **One short-period row** (7 days) — simulates a mid-cycle correction read; triggers PERIOD_SHORT_CHECK_READ
- **One long-period row** (47 days) — simulates an estimated bill; triggers PERIOD_LONG_ESTIMATED_OR_COMBINED
- **Rate schedule E-19/E-20** — PG&E's medium and large commercial rates; realistic

### What would break in a real deployment

1. **US national average emission factor.** We use EPA eGRID 2022 national average (0.1749 kg CO2e/kWh). The correct factor depends on the meter's NERC subregion. California (WECC CAMX) is ~0.10 kg CO2e/kWh. Midwest (MRO) is ~0.38. Using the national average understates California emissions and overstates Midwest — the opposite of what you'd want from a facility-level perspective.
2. **Non-US utilities.** European utilities use different export formats. UK utilities often export in the energy industry's standard MDB format. We handle none of this.
3. **Multiple tariff structures.** TOU (time-of-use) rates split usage into peak/off-peak. Some exports have separate rows for each TOU period. Our parser sums the kWh; it doesn't handle split-period rows.

---

## Source 3: Corporate Travel — Flights, Hotels, Ground Transport

### What I researched

I looked at:
- **Concur Travel**: SAP Concur has a REST API (v4) and a legacy SOAP API. The Travel Itinerary API returns itinerary objects with segments. The platform also supports "Standard Reports" — pre-built CSV exports available from the Reports module. The most relevant: "Travel Itinerary Detail" and "Trip Summary" reports.
- **Navan (formerly TripActions)**: Has a Travel Data API and an expense API. Also exports CSV from the Reporting tab.
- **Expensify, Brex**: Simpler expense tools; less structured travel data.

For flight emission factors, I read:
- DEFRA 2023 Greenhouse Gas Conversion Factors (Section 6: Business Travel)
- ICAO Carbon Emissions Calculator methodology
- GHG Protocol Scope 3 Technical Guidance (Chapter 7: Employee commuting and business travel)

### What I learned

1. **Segment type naming is inconsistent.** Concur uses "AIR", "HOTEL", "CAR". Some exports say "Flight", "Lodging", "Ground Transportation". Navan uses different values. Parser normalizes all of these.

2. **Distances are rarely provided.** The Concur export gives origin/destination as city names or airport codes. Distance is not standard. We compute it from IATA codes using Haversine.

3. **Cabin class is often missing.** Concur records it when the booker specifies it. Many hotel and ground segments have no class field at all. We assume Economy when missing and flag it.

4. **Hotel nights are sometimes derivable.** If "Nights" is blank but check-in and check-out dates are present, we compute `(check_out - check_in).days`.

5. **Ground transport distance is almost never provided.** Taxi/rideshare bookings have an amount but no distance. Without distance, we cannot compute a CO2e figure. We flag these rows and leave CO2e null rather than inventing a number.

6. **Flight emission factors vary by distance.** DEFRA uses different factors for short-haul (<3700 km) and long-haul (≥3700 km), and multiplied by class-of-service factors (Business = 2.9x Economy).

7. **RFI (Radiative Forcing Index):** DEFRA 2023 provides factors "with RF" and "without RF". We use "with RF" since DEFRA recommends it for UK Streamlined Energy and Carbon Reporting. ICAO and GHG Protocol allow reporting without RF.

### What our sample data looks like and why

```
Employee Name, Segment Type, Origin, Destination, Departure Date, Return Date, Vendor, Class of Service, Nights, Distance (km), Amount, Currency
Sarah Chen, AIR, SFO, JFK, 02/05/2024, 02/05/2024, United Airlines, Economy, , , 487.00, USD
Sarah Chen, HOTEL, New York, New York, 02/05/2024, 02/07/2024, Marriott Midtown, , 2, , 620.00, USD
Sarah Chen, CAR, JFK Airport, Midtown Manhattan, 02/05/2024, 02/05/2024, Lyft, , , 22, 45.00, USD
Marcus Weber, Flight, FRA, SIN, 03/10/2024, 03/10/2024, Lufthansa, Business Class, , , 4200.00, EUR
Marcus Weber, AIR, XYZ, SIN, 03/17/2024, 03/17/2024, Regional Air, Economy, , , 380.00, SGD
```

- **Mixed segment type naming** ("AIR", "Flight", "CAR", "HOTEL") — tests normalization
- **SFO→JFK**: Known airport codes, short-haul, Economy — baseline clean case
- **FRA→SIN**: Long-haul, Business Class — tests 2.9x multiplier and long-haul factor
- **XYZ→SIN**: Unknown origin airport code — triggers AIRPORT_UNKNOWN flag
- **Ground with distance (22 km)**: Tests distance-based CO2e calculation
- **Ground without distance (taxi)**: Tests MISSING_DISTANCE flag
- **Hotel with explicit nights**: Tests direct nights field
- **Hotel without nights field**: Tests date-derivation fallback

### What would break in a real deployment

1. **Our IATA airport table covers ~200 airports.** There are ~9,000 airports with IATA codes. A flight from YYC (Calgary) to YEG (Edmonton) would trigger AIRPORT_UNKNOWN. Production needs a full IATA database (OurAirports.com provides one under CC0).
2. **No deduplication.** If an analyst uploads the same Concur export twice, every row doubles. Deduplication requires a stable unique ID per booking — Concur has a "Trip ID" field, but it's not always present in exports.
3. **Currency not normalized.** The sample has amounts in USD, EUR, and SGD. Spend-based ground transport fallback would need FX normalization.
4. **Personal vs business travel.** Concur exports include all booked trips, including personal travel booked through the corporate travel portal. There is no flag in the export to distinguish. In practice, the client's travel policy defines what's in-scope.
