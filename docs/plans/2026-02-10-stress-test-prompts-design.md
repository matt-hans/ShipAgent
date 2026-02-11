# ShipAgent Stress Test Prompt Suite

**Date:** 2026-02-10
**Store:** matthansdev.myshopify.com
**Environment:** UPS Test (non-production)
**Total Orders Available:** 88 orders across 11 states, 20 product types, 61 unique customers

## Data Profile Summary

| Dimension | Coverage |
|-----------|----------|
| **States** | CA (22), NY (15), TX (14), FL (8), PA (7), MA (6), OH (5), IL (4), WA (4), NC (2), CO (1) |
| **Top Cities** | San Francisco (8), New York (7), Pittsburgh (5), Orlando (4), Chicago (4), Austin (3), San Antonio (3) |
| **Statuses** | paid/unfulfilled (54), pending/unfulfilled (12), paid/partial (10), refunded/unfulfilled (5), pending/partial (3), pending/fulfilled (2), refunded/fulfilled (2) |
| **Repeat Customers** | Arely Crooks (3), Cloyd Schultz (3), Garnet Reynolds-Miller (3), Luella Lockman (3), Nico Turcotte (3), Raoul Yost (3) |
| **Products** | 20 types: Wireless Mouse Ergonomic, Mechanical Keyboard RGB, External SSD 500GB, Webcam 1080p HD, etc. |
| **UPS Services** | Ground (03), 2nd Day Air (02), Next Day Air (01), 3 Day Select (12), Next Day Air Saver (13) |

## How to Use This Document

1. Open ShipAgent UI at `http://localhost:5173`
2. Ensure Shopify shows "Connected" in the sidebar
3. Enter each prompt exactly as written in the chat input
4. Follow the expected flow (preview → confirm → verify)
5. Record PASS/FAIL and any notes in the Result column

---

## Category 1: Core Happy Path

These validate the fundamental flow: filter → preview → confirm → ship → labels.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 1.1 | `Ship all unfulfilled Shopify orders using UPS Ground` | Fetches ~66 unfulfilled orders (paid + pending), shows preview with Ground rates | Preview shows 54+ rows, service = Ground, cost estimates present | |
| 1.2 | `Ship all California orders via Ground` | Filters to CA state (22 orders), shows preview | Preview shows ~22 rows, all recipients in CA cities (SF, LA, San Diego, etc.) | |
| 1.3 | `Ship orders going to San Francisco using 2nd Day Air` | Filters to SF city (8 orders), uses 2-Day service | Preview shows ~8 rows, service = 2nd Day Air, higher cost than Ground | |
| 1.4 | `Ship all orders for Noah Bode with overnight shipping` | Finds Noah Bode's order #1095 in SF, uses Next Day Air | Preview shows 1 row, recipient = Noah Bode, service = Next Day Air | |
| 1.5 | `Ship orders to Pittsburgh using 3 Day Select` | Filters to Pittsburgh PA (5 orders) | Preview shows 5 rows: Arely Crooks, Cloyd Schultz, Garnet Reynolds-Miller, Ericka Schowalter, Ryann Vandervort | |
| 1.6 | `Ship all New York orders via Next Day Air Saver` | Filters to NY state (15 orders), uses Saver service | Preview shows ~15 rows, cities include New York, Brooklyn, Buffalo, Bronx, Albany | |

---

## Category 2: Filter Complexity

Tests the NL engine's ability to parse complex, compound, and edge-case filters.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 2.1 | `Ship all California and Texas orders using Ground` | Compound OR filter: CA (22) + TX (14) = 36 orders | Preview shows ~36 rows, mix of CA and TX cities | |
| 2.2 | `Ship orders in Florida and Ohio via 2nd Day Air` | FL (8) + OH (5) = 13 orders | Preview shows ~13 rows, cities: Orlando, Tampa, Miami Beach, Mentor, Columbus, etc. | |
| 2.3 | `Ship all orders for Arely Crooks using Ground` | Name filter — Arely Crooks has 3 orders: #1064 (Pittsburgh PA), #1048 (SF CA), #1004 (Tacoma WA) | Preview shows 3 rows across PA, CA, WA | |
| 2.4 | `Ship all orders to Boston and Burlington via overnight` | City filter for Boston (3) + Burlington (3) in MA | Preview shows ~6 rows, all MA addresses | |
| 2.5 | `Ship paid unfulfilled orders in New York state using Ground` | Compound: status + state filter — paid/unfulfilled NY orders | Preview shows subset of 15 NY orders (only paid/unfulfilled ones) | |
| 2.6 | `Ship orders to Orlando, Florida via 3 Day Select` | City + state compound filter, Orlando FL (4 orders) | Preview shows 4 rows: Novella Gutkowski, Stephan Powlowski, Damien Anderson-Wisozk, Esta Russel | |
| 2.7 | `Ship all orders from the 94158 zip code with 2nd Day Air` | Postal code filter — 94158 covers some SF orders | Preview shows orders with postal code 94158 (Dayton Braun, Noah Bode, Zakary Watsica, Dan Connelly, Garnet Reynolds-Miller) | |
| 2.8 | `Ship Garnet Reynolds-Miller's orders using Next Day Air` | Hyphenated name — 3 orders: #1061 (Pittsburgh), #1045 (SF), #1001 (SF) | Preview shows 3 rows, tests hyphenated name parsing | |

---

## Category 3: Service Level Coverage

Validates all 5 UPS service types with different natural language alias phrasings.

| # | Prompt | Service Code | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------|-------------------|---------------------|--------|
| 3.1 | `Ship Benny Gerhold's order using UPS Ground` | 03 | Order #1019 to Boston MA | Service = Ground, 1 row | |
| 3.2 | `Ship Olaf Kilback's orders via two day air` | 02 | 2 orders: #1094 and #1016 (both Buffalo NY) | Service = 2nd Day Air, 2 rows | |
| 3.3 | `Ship Adah Morissette's order overnight` | 01 | Order #1015 to Denver CO | Service = Next Day Air, 1 row | |
| 3.4 | `Ship Mara Stoltenberg's order with three day select` | 12 | Order #1041 to New York NY | Service = 3 Day Select, 1 row | |
| 3.5 | `Ship Delilah Orn's order using NDA saver` | 13 | Order #1033 to San Francisco CA | Service = Next Day Air Saver, 1 row | |

---

## Category 4: Action Type Coverage

Tests actions beyond shipping: rating and address validation.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 4.1 | `Rate all Texas orders using Ground` | Rate-only action for 14 TX orders — no shipment creation | Returns cost estimates for each row, no tracking numbers generated | |
| 4.2 | `Get a shipping quote for Darian Ernser's orders via overnight` | Rate 2 orders: #1091 (NY) and #1014 (Santa Clara CA) | Cost estimates returned for both, higher than Ground | |
| 4.3 | `Validate addresses for all Pittsburgh orders` | Address validation for 5 Pittsburgh PA orders | Returns valid/ambiguous/invalid status for each address | |
| 4.4 | `Rate all Florida orders with 2nd Day Air` | Rate 8 FL orders across Orlando, Tampa, Miami Beach, Plantation, Coral Springs | Cost estimates vary by distance from shipper | |

---

## Category 5: Row Qualifiers & Batch Sizing

Tests the system's ability to process subsets of filtered results.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 5.1 | `Ship the first 5 California orders using Ground` | Applies row qualifier: first 5 of 22 CA orders | Preview shows exactly 5 rows, all CA addresses | |
| 5.2 | `Ship the first 3 New York orders via 2nd Day Air` | First 3 of 15 NY orders | Preview shows 3 rows, all NY state | |
| 5.3 | `Ship all Massachusetts orders using Ground` | All 6 MA orders (Boston + Burlington) | Preview shows 6 rows: Monroe Daugherty, Eva Christiansen, Fae Runte, Benny Gerhold, Cecile White, Luella Lockman | |
| 5.4 | `Ship the first 10 orders via Ground` | No state filter, first 10 of all unfulfilled orders | Preview shows 10 rows from mixed states | |

---

## Category 6: Edge Cases & Error Handling

Probes boundaries, error recovery, and unusual inputs.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 6.1 | `Ship all orders to Antarctica using Ground` | No orders match — empty result | System reports 0 matching orders, no preview generated | |
| 6.2 | `Ship all orders for Nonexistent Person via Ground` | No customer/recipient match | System reports 0 matching orders gracefully | |
| 6.3 | `Ship orders to zip code 99999 using overnight` | Invalid/non-matching postal code | 0 matching orders or UPS address validation catches bad zip | |
| 6.4 | `Ship all Colorado orders using Ground` | Only 1 order (Adah Morissette, Denver CO 80206) — single-row batch | Preview shows 1 row, full pipeline works for single order | |
| 6.5 | `Ship all orders` | Missing service — should trigger elicitation | System asks "Which shipping service should I use?" with options | |
| 6.6 | `Ship all refunded orders using Ground` | 5 refunded/unfulfilled orders — tests status filter edge case | System handles refunded status orders (may warn about shipping refunded orders) | |
| 6.7 | `Ship Simeon Schaefer-Halvorson's order via Ground` | Tests long hyphenated name parsing | Finds order #1021 to Miami Beach FL, preview shows 1 row | |

---

## Category 7: Multi-Turn Conversational Flows

Tests sequential commands in the same session, cancellation, and refinement.

| # | Prompt Sequence | Expected Behavior | Validation Criteria | Result |
|---|----------------|-------------------|---------------------|--------|
| 7.1 | **Turn 1:** `Ship all Ohio orders using Ground` | Preview shows 5 OH orders | Preview card appears | |
| | **Turn 2:** Cancel the preview | Job cancelled, input re-enables | No shipments created, can type next command | |
| | **Turn 3:** `Ship all Ohio orders using 2nd Day Air instead` | New preview with 2-Day service at higher cost | New preview replaces old, different cost estimates | |
| 7.2 | **Turn 1:** `Rate all Pennsylvania orders with Ground` | Rate-only for 7 PA orders | Cost estimates shown, no tracking | |
| | **Turn 2:** `Now ship those same Pennsylvania orders with Ground` | Ships the same 7 PA orders | Full execution pipeline produces tracking numbers | |
| 7.3 | **Turn 1:** `Ship all Illinois orders via Ground` | Preview shows 4 IL orders (all Chicago) | Preview with 4 rows | |
| | **Turn 2:** Confirm execution | Executes batch shipment | Tracking numbers generated, labels available, completion artifact | |
| | **Turn 3:** `Ship all Washington orders via overnight` | New command in same session — 4 WA orders (Seattle + Tacoma) | Second batch processes independently, new tracking numbers | |
| 7.4 | **Turn 1:** `Ship Nico Turcotte's orders using Ground` | 3 orders: #1072 (Chicago IL), #1056 (Seattle WA), #1006 (El Paso TX) | Preview shows 3 rows across 3 states | |
| | **Turn 2:** Confirm execution | Full batch execution | 3 tracking numbers, 3 labels, completion artifact with "View Labels" | |
| 7.5 | **Turn 1:** `Ship all San Francisco orders with 2nd Day Air` | Preview shows 8 SF orders | 8 rows with 2-Day costs | |
| | **Turn 2:** Cancel and say `Actually, ship just the first 3 San Francisco orders` | Cancels, re-processes with row qualifier | New preview with only 3 rows | |
| 7.6 | **Turn 1:** `Ship Dan Connelly's orders via overnight` | 2 orders: #1084 (San Diego) and #1012 (SF) | Preview with 2 rows | |
| | **Turn 2:** Confirm and complete | Full execution | Tracking + labels for both, write-back to Shopify | |

---

## Execution Checklist

Before running tests:
- [ ] Backend running: `./scripts/start-backend.sh`
- [ ] Frontend running: `cd frontend && npm run dev`
- [ ] Shopify connected: Sidebar shows "matthansdev" as connected
- [ ] UPS test credentials configured in `.env`
- [ ] Clear any previous test jobs from sidebar

After each test:
- [ ] Verify preview row count matches expected
- [ ] Verify correct UPS service appears in preview
- [ ] After confirmation: tracking numbers appear in completion card
- [ ] Labels downloadable via "View Labels" button
- [ ] Job appears in sidebar history with correct status

## Known Limitations to Watch For

1. **No date range filtering** — all 88 orders share the same creation date (2026-02-04), so temporal filters like "today's orders" or "this week" will match based on that date, not today's date
2. **No company names** — all `ship_to_company` fields are null, so company-based filters will return 0 results
3. **No address2 data** — secondary address lines are all null
4. **Phone formats vary** — some phones have extensions (e.g., "1-665-519-2459 x3217") which may need normalization
5. **Refunded orders** — 5 orders have `refunded` financial status; shipping these is technically valid in test env but unusual in production
6. **Partially fulfilled orders** — 13 orders have `partial` fulfillment status; system should handle these (ship remaining unfulfilled items)
