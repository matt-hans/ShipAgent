# ShipAgent CSV/Excel Stress Test Prompt Suite

**Date:** 2026-02-14
**Data File:** `test_data/sample_shipments.csv` (also available as `sample_shipments.xlsx`)
**Environment:** UPS Test (non-production)
**Total Rows:** 100 shipments (ORD-1001 through ORD-1100)

## Data Profile Summary

| Dimension | Coverage |
|-----------|----------|
| **Columns** | order_number, recipient_name, company, phone, address_line_1, address_line_2, city, state, zip_code, country, weight_lbs, length_in, width_in, height_in, service, packaging_type, description, declared_value |
| **States** | All 50 US states + PR + DC (every state represented at least once) |
| **Weight Range** | 0.4 lbs (UPS Letter) to 68.0 lbs (irrigation pump parts) |
| **Declared Value** | $0.00 (documents) to $5,500.00 (rocket propulsion components) |
| **Service Mix** | Ground (~50), Next Day Air (~12), 2nd Day Air (~20), 3 Day Select (~10) |
| **Packaging Types** | Customer Supplied (~90), UPS Letter (~6), PAK (~1) |
| **Companies** | ~30 business recipients (company field populated), ~70 personal (NULL company) |
| **Dimensions** | Most rows have L/W/H; UPS Letter rows have NULL dimensions |

### Key Recipients for Name-Based Tests

| Recipient | Order | City, State | Weight | Service | Company | Declared Value |
|-----------|-------|------------|--------|---------|---------|----------------|
| Sarah Mitchell | ORD-1001 | Austin, TX | 2.3 | Ground | — | $45.99 |
| James Thornton | ORD-1002 | New York, NY | 0.8 | Next Day Air | Thornton Legal Group | $0 |
| Maria Rodriguez | ORD-1003 | Miami, FL | 15.7 | Ground | — | $189.50 |
| David Kim | ORD-1004 | San Francisco, CA | 4.2 | 2nd Day Air | Kim Electronics LLC | $275.00 |
| Troy Bennett | ORD-1084 | Huntsville, AL | 5.5 | Next Day Air | Bennett Aerospace Corp | $5,500.00 |
| Monica Sanchez | ORD-1065 | San Juan, PR | 2.0 | 2nd Day Air | Sanchez Floral Design | $145.00 |
| Peter Phillips | ORD-1060 | Anchorage, AK | 18.0 | 2nd Day Air | — | $310.00 |
| Tyler Flores | ORD-1052 | Austin, TX | 42.0 | Ground | Flores Landscaping Inc | $340.00 |

---

## How to Use This Document

1. Open ShipAgent UI at `http://localhost:5173`
2. Connect CSV via sidebar: upload `test_data/sample_shipments.csv`
3. Verify sidebar shows "CSV connected" with 100 rows
4. Enter each prompt exactly as written in the chat input
5. Follow the expected flow (preview → confirm or cancel)
6. Record PASS/FAIL and notes in the Result column
7. For multi-turn tests, execute prompts sequentially in the same session

**Important:** This CSV uses `recipient_name` (not `customer_name`/`ship_to_name`), `weight_lbs` (not `total_weight_grams`), and `state` as 2-letter codes. The agent must adapt its SQL generation to the actual schema columns.

---

## Category 1: Single-Column Filters (Baseline)

Validates that the agent correctly generates SQL WHERE clauses against each filterable column individually.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 1.1 | `Ship all Texas orders using Ground` | Filters `state = 'TX'` — 4 orders: ORD-1001 (Austin), ORD-1033 (San Antonio), ORD-1052 (Austin), ORD-1082 (McAllen), ORD-1093 (Austin) | Preview shows 5 rows, all TX addresses | |
| 1.2 | `Ship all orders going to San Francisco via 2nd Day Air` | Filters `city = 'San Francisco'` or ILIKE — ORD-1004 | Preview shows 1 row, David Kim in SF | |
| 1.3 | `Ship the order for Sarah Mitchell with Ground` | Name filter on `recipient_name` — ORD-1001 Austin TX | Preview shows 1 row, Sarah Mitchell | |
| 1.4 | `Ship all California orders using Ground` | Filters `state = 'CA'` — ORD-1004 (SF), ORD-1013 (San Diego), ORD-1025 (Sacramento), ORD-1043 (San Diego), ORD-1049 (LA), ORD-1062 (San Diego), ORD-1095 (Napa) | Preview shows 7 rows, all CA cities | |
| 1.5 | `Ship all orders with weight over 30 pounds via Ground` | Numeric filter `weight_lbs > 30` — ORD-1006 (32.5), ORD-1016 (68.0), ORD-1024 (52.0), ORD-1036 (38.0), ORD-1054 (65.0), ORD-1066 (35.0), ORD-1078 (40.0), ORD-1086 (33.0), ORD-1092 (55.0) | Preview shows 9 rows, all heavyweight | |
| 1.6 | `Ship all orders to zip code 33131 via overnight` | ZIP filter — ORD-1003 Maria Rodriguez, Miami FL | Preview shows 1 row, Next Day Air service | |
| 1.7 | `Ship all orders from companies using 3 Day Select` | NULL exclusion: `company IS NOT NULL` — ~30 rows with business recipients | Preview shows ~30 rows, all have company names | |
| 1.8 | `Ship orders with declared value over $1000 using Next Day Air` | Numeric filter `declared_value > 1000` — ORD-1011 ($1250), ORD-1018 ($2100), ORD-1049 ($1850), ORD-1056 ($4200), ORD-1062 ($1500), ORD-1078 ($1650), ORD-1084 ($5500), ORD-1099 ($2200), ORD-1044 ($3500) | Preview shows 9 rows, high-value items | |

---

## Category 2: Compound Filters (AND/OR Logic)

Tests the agent's ability to generate multi-condition WHERE clauses with correct AND/OR precedence.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 2.1 | `Ship all California and Texas orders using Ground` | OR compound: `state = 'CA' OR state = 'TX'` or `state IN ('CA', 'TX')` — CA (7) + TX (5) = 12 orders | Preview shows 12 rows mixing CA and TX cities | |
| 2.2 | `Ship all orders in Florida that weigh over 10 pounds via Ground` | AND compound: `state = 'FL' AND weight_lbs > 10` — ORD-1003 (15.7, Miami), ORD-1063 (15.2, Jacksonville) | Preview shows 2 rows, both FL heavyweight | |
| 2.3 | `Ship all Next Day Air orders going to Alabama using overnight` | AND compound: `state = 'AL' AND service = 'Next Day Air'` — ORD-1084 (Huntsville, Bennett Aerospace) | Preview shows 1 row, already marked NDA in data | |
| 2.4 | `Ship orders to Portland or Seattle with 2nd Day Air` | City-based OR: `city = 'Portland' OR city = 'Seattle'` — ORD-1006 (Portland OR), ORD-1037 (Portland OR), ORD-1009 (Seattle WA), ORD-1091 (Eugene — should NOT match) | Preview shows 3 rows (2 Portland + 1 Seattle) | |
| 2.5 | `Ship all orders between 5 and 15 pounds in the Northeast via 3 Day Select` | Compound: weight range + multi-state — `weight_lbs BETWEEN 5 AND 15 AND state IN ('NY','MA','CT','NJ','NH','VT','ME','RI','PA')` | Preview shows matching rows from northeastern states within weight range | |
| 2.6 | `Ship all business orders in California with declared value over $200 using 2nd Day Air` | Triple AND: `state = 'CA' AND company IS NOT NULL AND declared_value > 200` — ORD-1004 (Kim Electronics, $275), ORD-1049 (Cox Media, $1850), ORD-1062 (Parker Biotech, $1500), ORD-1095 (Patterson Organic, $290) | Preview shows 4 rows, all CA companies with high values | |
| 2.7 | `Ship all UPS Letter orders using Next Day Air` | Packaging filter: `packaging_type = 'UPS Letter'` — ORD-1002, ORD-1008, ORD-1021, ORD-1034, ORD-1073, ORD-1089 | Preview shows 6 rows, all lightweight document shipments | |
| 2.8 | `Ship orders to Ohio or Wisconsin that have a company name via Ground` | OR states + NOT NULL company: `(state = 'OH' OR state = 'WI') AND company IS NOT NULL` — ORD-1026 (Robinson Publishing, Cleveland OH), ORD-1047 (Rogers Veterinary, Madison WI) | Preview shows 2 rows | |

---

## Category 3: Service Code Resolution & Overrides

Tests every UPS service alias and verifies the agent correctly resolves natural language service names. Also tests service override behavior (command service vs. per-row service in the CSV).

| # | Prompt | Service Expected | Expected Behavior | Validation Criteria | Result |
|---|--------|-----------------|-------------------|---------------------|--------|
| 3.1 | `Ship ORD-1001 using UPS Ground` | 03 | Sarah Mitchell, Austin TX, 2.3 lbs | Service = Ground, 1 row | |
| 3.2 | `Ship ORD-1002 via two day air` | 02 | James Thornton, New York NY, 0.8 lbs (UPS Letter override to 2-Day) | Service = 2nd Day Air, overrides original NDA | |
| 3.3 | `Ship Maria Rodriguez's order overnight` | 01 | ORD-1003, Miami FL, 15.7 lbs | Service = Next Day Air, 1 row | |
| 3.4 | `Ship David Kim's order with three day select` | 12 | ORD-1004, San Francisco CA, 4.2 lbs | Service = 3 Day Select, overrides original 2-Day | |
| 3.5 | `Ship ORD-1005 using NDA saver` | 13 | Emily Watson, Scottsdale AZ, 1.1 lbs | Service = Next Day Air Saver, 1 row | |
| 3.6 | `Ship all Florida orders using the cheapest ground shipping` | 03 | All FL orders with Ground service | Service = Ground for all 8 FL rows | |
| 3.7 | `Ship all Connecticut orders express` | 01 | "express" → Next Day Air — ORD-1028 (Hartford), ORD-1044 (East Hartford), ORD-1078 (Stamford) | Service = Next Day Air, 3 rows | |
| 3.8 | `Ship order ORD-1073 using standard delivery` | 03 or 11 | Jenna Washington, DC — "standard" could resolve to UPS Standard (11) or Ground (03); system should clarify or default to Ground | Service resolves to Ground (domestic) or asks for clarification | |

---

## Category 4: Weight & Dimension Queries

Tests numeric range filtering, unit conversions, and dimension-aware queries that exercise the data's weight/size spectrum.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 4.1 | `Ship all orders under 1 pound using Ground` | `weight_lbs < 1` — ORD-1002 (0.8), ORD-1008 (0.5), ORD-1021 (0.7), ORD-1034 (0.6), ORD-1043 (0.9), ORD-1073 (0.4), ORD-1089 (0.6) | Preview shows 7 rows, all lightweight documents/letters | |
| 4.2 | `Ship all orders over 50 pounds via Ground` | `weight_lbs > 50` — ORD-1016 (68.0), ORD-1024 (52.0), ORD-1054 (65.0), ORD-1092 (55.0) | Preview shows 4 rows, industrial/heavy items | |
| 4.3 | `Ship all heavy packages between 20 and 40 pounds with 3 Day Select` | `weight_lbs BETWEEN 20 AND 40` — ORD-1006 (32.5), ORD-1011 (22.0), ORD-1032 (25.0), ORD-1036 (38.0), ORD-1044 (29.0), ORD-1050 (20.5), ORD-1066 (35.0), ORD-1070 (28.0), ORD-1074 (22.0), ORD-1086 (33.0), ORD-1090 (25.0) | Preview shows ~11 rows in weight range | |
| 4.4 | `Ship the heaviest order in the dataset using Ground` | Should identify ORD-1016 (68.0 lbs, irrigation pump parts, Des Moines IA) | Agent may need to query `ORDER BY weight_lbs DESC LIMIT 1` or filter for max weight | |
| 4.5 | `Ship all orders with no package dimensions using Ground` | NULL dimensions: `length_in IS NULL` — ORD-1002, ORD-1008, ORD-1021, ORD-1034, ORD-1073, ORD-1089 (all UPS Letter) | Preview shows 6 rows, all letters/PAK with no dimensions | |
| 4.6 | `Ship all orders where the longest dimension exceeds 24 inches via Ground` | `length_in > 24` — ORD-1014 (30"), ORD-1016 (36"), ORD-1024 (28"), ORD-1036 (28"), ORD-1054 (36"), ORD-1066 (28"), ORD-1078 (30"), ORD-1086 (28"), ORD-1087 (40"), ORD-1092 (32") | Preview shows 10 rows, large packages | |

---

## Category 5: Declared Value & Insurance Queries

Tests value-based filtering and high-value shipment handling.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 5.1 | `Ship all orders with zero declared value using Ground` | `declared_value = 0` — all document/letter shipments (ORD-1002, ORD-1008, ORD-1021, ORD-1034, ORD-1043, ORD-1073, ORD-1089) | Preview shows 7 rows, all $0 declared value | |
| 5.2 | `Ship the most expensive order via Next Day Air` | Identify ORD-1084 ($5,500 — rocket propulsion, Huntsville AL) | Preview shows 1 row, Troy Bennett, declared value $5,500 | |
| 5.3 | `Ship all orders worth between $500 and $1000 using 2nd Day Air` | `declared_value BETWEEN 500 AND 1000` — ORD-1005 ($520), ORD-1016 ($625), ORD-1024 ($575), ORD-1028 ($890), ORD-1036 ($720), ORD-1047 ($680), ORD-1049 ($1850 — should NOT match), ORD-1015 ($699), ORD-1076 ($680), ORD-1077 ($875), ORD-1087 ($850), ORD-1092 ($780), ORD-1070 ($535), ORD-1097 ($950) | Preview shows rows with values $500-$1000 only | |
| 5.4 | `Ship all orders with insurance value over $2000 overnight` | `declared_value > 2000` — ORD-1018 ($2100), ORD-1044 ($3500), ORD-1056 ($4200), ORD-1084 ($5500), ORD-1099 ($2200) | Preview shows 5 rows, all extremely high-value | |

---

## Category 6: Company/Business vs Personal Recipient Queries

Tests NULL handling and the distinction between business and personal shipments.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 6.1 | `Ship all personal orders in Florida using Ground` | `state = 'FL' AND company IS NULL` — personal FL recipients without a company | Preview shows only FL individuals (no company field) | |
| 6.2 | `Ship all business orders using 2nd Day Air` | `company IS NOT NULL` — ~30 rows with company names | Preview shows ~30 rows, all with company names visible | |
| 6.3 | `Ship all orders for companies with "Medical" or "Dental" in the name via overnight` | `company ILIKE '%Medical%' OR company ILIKE '%Dental%'` — ORD-1011 (FosterCare Medical Supplies), ORD-1031 (King Dental Practice), ORD-1076 (Perry Dental Lab), ORD-1081 (James Veterinary Hospital — should NOT match) | Preview shows 3 rows (Medical + Dental companies) | |
| 6.4 | `Ship all orders from law firms and legal companies using Next Day Air` | `company ILIKE '%Legal%' OR company ILIKE '%Law%' OR company ILIKE '%CPA%' OR company ILIKE '%Associates%'` — ORD-1002 (Thornton Legal), ORD-1034 (Hill & Associates CPA), ORD-1089 (Cooper Legal Associates), possibly ORD-1008 (Brown & Associates Consulting) | Preview shows legal/professional services firms | |

---

## Category 7: Description & Product-Based Queries

Tests text pattern matching against the description column — a common real-world query pattern.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 7.1 | `Ship all orders containing coffee or tea using Ground` | `description ILIKE '%coffee%' OR description ILIKE '%tea%'` — ORD-1012 (coffee sampler, Charlotte NC), ORD-1025 (tea sampler, Sacramento CA), ORD-1071 (Kona coffee, HI) | Preview shows 3 rows | |
| 7.2 | `Ship all medical and pharmaceutical orders via overnight` | `description ILIKE '%medical%' OR description ILIKE '%pharmaceutical%' OR description ILIKE '%surgical%' OR description ILIKE '%dental%' OR description ILIKE '%veterinary%' OR description ILIKE '%vaccine%' OR description ILIKE '%specimen%' OR description ILIKE '%tissue%'` | Preview shows medical/pharma items (ORD-1011, ORD-1031, ORD-1038, ORD-1047, ORD-1062, ORD-1081, ORD-1099, etc.) | |
| 7.3 | `Ship all jewelry orders using 2nd Day Air` | `description ILIKE '%jewelry%'` — ORD-1005 ($520, Scottsdale AZ), ORD-1023 ($320, Honolulu HI), ORD-1048 ($275, Tucson AZ), ORD-1077 ($875, Little Rock AR) | Preview shows 4 rows, all jewelry items | |
| 7.4 | `Ship all orders with "equipment" in the description via Ground` | `description ILIKE '%equipment%'` — ORD-1009 (camping), ORD-1049 (camera), ORD-1056 (aircraft avionics — may not match), ORD-1068 (fly fishing), ORD-1074 (hunting), ORD-1086 (potato farming), ORD-1090 (ice fishing) | Preview shows multiple equipment orders | |
| 7.5 | `Ship all food and beverage orders using Ground` | Pattern matching for food items: `description ILIKE '%sampler%' OR description ILIKE '%coffee%' OR description ILIKE '%tea%' OR description ILIKE '%spice%' OR description ILIKE '%cheese%' OR description ILIKE '%wine%' OR description ILIKE '%maple%' OR description ILIKE '%bourbon%' OR description ILIKE '%crawfish%'` | Preview includes ORD-1012, ORD-1020, ORD-1025, ORD-1030, ORD-1050, ORD-1071, ORD-1079, ORD-1088, ORD-1093, ORD-1095, ORD-1098 | |

---

## Category 8: Geographic Edge Cases

Tests unusual geographic scenarios — territories, remote states, multi-city states.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 8.1 | `Ship all Hawaii orders using 2nd Day Air` | `state = 'HI'` — ORD-1023 (Honolulu), ORD-1071 (Kailua-Kona), ORD-1100 (Haleiwa) | Preview shows 3 rows, all HI addresses | |
| 8.2 | `Ship all Alaska orders via 2nd Day Air` | `state = 'AK'` — ORD-1060 (Anchorage), ORD-1090 (Anchorage) | Preview shows 2 rows, both Anchorage | |
| 8.3 | `Ship the Puerto Rico order with 2nd Day Air` | `state = 'PR'` — ORD-1065 (San Juan, Monica Sanchez, Sanchez Floral Design) | Preview shows 1 row, PR territory | |
| 8.4 | `Ship all orders to Washington DC using overnight` | `state = 'DC'` — ORD-1073 (Jenna Washington, Washington PR Agency) | Preview shows 1 row, DC address | |
| 8.5 | `Ship all orders to Portland using Ground` | City filter: `city = 'Portland'` — ORD-1006 (Portland OR), ORD-1037 (Portland OR), ORD-1070 (Portland ME) — tests same city name in different states | Preview shows 3 rows: 2 in Oregon, 1 in Maine | |
| 8.6 | `Ship all orders to Charleston using 3 Day Select` | `city = 'Charleston'` — ORD-1036 (Charleston SC), ORD-1069 (Charleston WV), ORD-1081 (Charleston SC) — same city in 2 states | Preview shows 3 rows: 2 SC + 1 WV | |
| 8.7 | `Ship all orders in the Pacific Northwest via Ground` | Agent must interpret "Pacific Northwest" → WA, OR (possibly ID, MT) — ORD-1006 (Portland OR), ORD-1009 (Seattle WA), ORD-1037 (Portland OR), ORD-1091 (Eugene OR) + optionally ID/MT orders | Preview shows WA + OR orders (4+ rows) | |
| 8.8 | `Ship all orders in New England states using 3 Day Select` | Agent must interpret "New England" → CT, ME, MA, NH, RI, VT — ORD-1028 (Hartford CT), ORD-1041 (Providence RI), ORD-1044 (East Hartford CT), ORD-1067 (Concord NH), ORD-1070 (Portland ME), ORD-1078 (Stamford CT), ORD-1088 (Concord NH), ORD-1098 (Montpelier VT) | Preview shows 8 rows across 5-6 NE states | |

---

## Category 9: Packaging Type Queries

Tests filtering and handling of different UPS packaging types.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 9.1 | `Ship all UPS Letter shipments using Next Day Air` | `packaging_type = 'UPS Letter'` — 6 orders (ORD-1002, ORD-1008, ORD-1021, ORD-1034, ORD-1073, ORD-1089) | Preview shows 6 rows, all lightweight letters | |
| 9.2 | `Ship the PAK order via 2nd Day Air` | `packaging_type = 'PAK'` — ORD-1043 (Danielle Rivera, San Diego CA, legal correspondence) | Preview shows 1 row | |
| 9.3 | `Ship all non-letter, non-PAK orders in New York state using Ground` | `state = 'NY' AND packaging_type = 'Customer Supplied'` — ORD-1051 (Rochester) | Preview shows NY orders with Customer Supplied packaging only | |

---

## Category 10: Row Qualifiers & Batch Sizing

Tests LIMIT, OFFSET, and row subset selection.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 10.1 | `Ship the first 10 orders using Ground` | Fetches first 10 rows (ORD-1001 through ORD-1010), applies Ground service | Preview shows exactly 10 rows | |
| 10.2 | `Ship the first 5 California orders via 2nd Day Air` | Filters CA (7 orders), then takes first 5 | Preview shows 5 rows, all CA | |
| 10.3 | `Ship just one order to test — pick the lightest one and use Ground` | Agent should find ORD-1073 (0.4 lbs, Jenna Washington, DC) | Preview shows 1 row, lightest package | |
| 10.4 | `Ship the first 3 orders over $500 declared value using overnight` | Filter `declared_value > 500`, take first 3 | Preview shows 3 rows, all > $500 value | |
| 10.5 | `Ship all 100 orders using Ground` | Full dataset, 100 rows, all Ground override | Preview shows 100 rows (or warns about batch size), Ground service applied | |

---

## Category 11: Ambiguous & Clarification-Required Prompts

Tests whether the agent correctly identifies ambiguity and asks clarifying questions instead of guessing.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 11.1 | `Ship all orders` | Missing service — should ask which UPS service to use or default to each row's existing service | Agent asks for service preference or uses per-row service | |
| 11.2 | `Ship the heavy ones` | Ambiguous "heavy" — no clear threshold; agent should ask what weight qualifies as "heavy" | Agent asks "What weight threshold defines heavy?" or similar | |
| 11.3 | `Ship everything to the West Coast fast` | "West Coast" and "fast" are ambiguous — which states? which service? | Agent clarifies: CA/OR/WA? And asks about service level (NDA vs 2-Day) | |
| 11.4 | `Ship the expensive stuff overnight` | "Expensive" has no threshold — agent should ask what value qualifies | Agent asks for declared value threshold or clarifies intent | |
| 11.5 | `Ship Mitchell's order` | Name ambiguity: Sarah Mitchell (ORD-1001) vs Chad Mitchell (ORD-1056) — same last name, different first names | Agent asks which Mitchell or shows both matches | |
| 11.6 | `Ship all orders to the Midwest using Ground` | "Midwest" is subjective — could be 8-12 states depending on definition | Agent either uses a standard Midwest definition (IL, IN, IA, KS, MI, MN, MO, NE, ND, OH, SD, WI) or asks for clarification | |

---

## Category 12: Complex Natural Language Patterns

Tests sophisticated, real-world phrasing that goes beyond simple filter syntax — the kind of prompts a busy logistics manager would actually type.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 12.1 | `Ship everything going to the Southeast except Florida using Ground` | Interprets "Southeast" (AL, GA, SC, NC, TN, VA, etc.) minus FL | Preview shows SE-state orders excluding FL rows | |
| 12.2 | `Ship all the small packages — anything under 3 pounds — to the East Coast via 2nd Day Air` | Weight < 3 lbs AND East Coast states (NY, NJ, CT, MA, PA, VA, NC, SC, GA, FL, ME, NH, VT, RI, DE, MD, DC) | Preview shows lightweight East Coast orders | |
| 12.3 | `Rush ship everything for medical and veterinary companies via overnight` | Description or company ILIKE '%medical%' OR '%veterinary%' OR '%dental%' OR '%pharmaceutical%' — ORD-1011 (FosterCare Medical), ORD-1031 (King Dental), ORD-1047 (Rogers Veterinary), ORD-1081 (James Veterinary Hospital) | Preview shows 4 medical/vet company orders, NDA service | |
| 12.4 | `Ship all orders in the $100-$300 range that are going to states west of the Mississippi using Ground` | Compound: declared_value BETWEEN 100 AND 300 AND state IN western states | Preview shows mid-value orders to western US | |
| 12.5 | `Send all the document shipments — letters and PAK items — using Next Day Air` | `packaging_type IN ('UPS Letter', 'PAK')` — 7 orders total | Preview shows all letter/PAK rows with NDA service | |
| 12.6 | `Ship the Austin, Texas orders but skip the heavy one — just the light packages under 5 lbs` | `city = 'Austin' AND state = 'TX' AND weight_lbs < 5` — ORD-1001 (2.3 lbs), ORD-1093 (1.6 lbs); excludes ORD-1052 (42.0 lbs) | Preview shows 2 rows, both light Austin packages | |
| 12.7 | `I need to get all the orders with suite or apartment numbers shipped Ground` | `address_line_2 IS NOT NULL AND address_line_2 != ''` — orders with secondary address lines | Preview shows ~30 rows with Apt/Suite/Floor/Unit in address_line_2 | |
| 12.8 | `Ship all the art and craft orders — anything with art, craft, print, or design in the description — using 3 Day Select` | Description ILIKE patterns for art-related items: ORD-1042 (Native art prints), ORD-1051 (Photography prints), ORD-1087 (Framed art prints), ORD-1096 (Glass art pieces) | Preview shows art/craft description matches | |
| 12.9 | `Ship only the orders that already have Ground as their service — don't change the service, just process them` | `service = 'Ground'` — uses existing service assignments (~50 rows) | Preview shows ~50 rows all with Ground service matching the data | |
| 12.10 | `Find all orders to Connecticut and ship them via the service that's already assigned to each one` | `state = 'CT'` — ORD-1028 (Next Day Air), ORD-1044 (Next Day Air), ORD-1078 (Ground) — preserves per-row service | Preview shows 3 rows with mixed services (NDA + Ground as in source data) | |

---

## Category 13: Negation & Exclusion Filters

Tests NOT, exclusion, and negative filtering patterns.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 13.1 | `Ship all orders that are NOT going to California or Texas using Ground` | `state NOT IN ('CA', 'TX')` — excludes CA (7) and TX (5) = 88 remaining | Preview shows ~88 rows, no CA/TX addresses | |
| 13.2 | `Ship all orders except the ones with zero declared value via Ground` | `declared_value > 0` or `declared_value != 0` — excludes 7 document orders | Preview shows ~93 rows, all with positive declared values | |
| 13.3 | `Ship all non-business orders in the South using Ground` | `company IS NULL AND state IN ('TX','FL','AL','GA','LA','MS','SC','NC','TN','VA','AR','KY')` | Preview shows personal (non-company) orders from Southern states | |
| 13.4 | `Ship everything except orders over 50 pounds using 2nd Day Air` | `weight_lbs <= 50` — excludes 4 heavyweight orders | Preview shows ~96 rows, max weight 50 lbs or under | |

---

## Category 14: Order Number Queries

Tests direct order number reference — the most precise filter type.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 14.1 | `Ship order ORD-1001 using Ground` | Direct order lookup — Sarah Mitchell, Austin TX | Preview shows 1 row, exact order match | |
| 14.2 | `Ship orders ORD-1001, ORD-1002, and ORD-1003 via 2nd Day Air` | Multi-order: `order_number IN ('ORD-1001','ORD-1002','ORD-1003')` | Preview shows 3 specific rows | |
| 14.3 | `Ship orders ORD-1010 through ORD-1020 using Ground` | Range query — 11 orders from ORD-1010 to ORD-1020 | Preview shows 11 rows in order number range | |
| 14.4 | `Ship the last order in the spreadsheet using overnight` | ORD-1100 (Ivan Howard, Haleiwa HI, surfboard wax) — last row | Preview shows 1 row, ORD-1100 | |

---

## Category 15: Multi-Turn Conversational Flows

Tests sequential commands, cancellation, refinement, and session continuity with CSV data.

| # | Prompt Sequence | Expected Behavior | Validation Criteria | Result |
|---|----------------|-------------------|---------------------|--------|
| 15.1 | **Turn 1:** `Ship all Florida orders using Ground` | Preview shows 8 FL orders | Preview card appears with FL addresses | |
| | **Turn 2:** `Cancel that — ship just the Miami ones instead` | Cancels preview, re-filters to `city ILIKE '%Miami%' AND state = 'FL'` — ORD-1003 (Miami), ORD-1099 (Key Biscayne — may or may not match "Miami") | New preview with 1-2 Miami area rows | |
| 15.2 | **Turn 1:** `Ship all Oregon orders via Ground` | Preview: ORD-1006 (Portland), ORD-1037 (Portland), ORD-1091 (Eugene) — 3 rows | Preview shows 3 OR rows | |
| | **Turn 2:** Confirm execution | Full batch execution — 3 tracking numbers, 3 labels | Completion artifact with "View Labels" | |
| | **Turn 3:** `Now ship all Washington state orders via 2nd Day Air` | New command in same session — ORD-1009 (Seattle) | New preview, independent batch | |
| 15.3 | **Turn 1:** `Rate all California orders using Ground` | Rate-only action for 7 CA orders — no shipment creation | Cost estimates returned, no tracking numbers | |
| | **Turn 2:** `Those rates look good — now actually ship them` | Ships same 7 CA orders with Ground | Full execution, 7 tracking numbers generated | |
| 15.4 | **Turn 1:** `Ship all orders over 40 pounds with Ground` | Preview: ORD-1014 (45.0), ORD-1016 (68.0), ORD-1024 (52.0), ORD-1052 (42.0), ORD-1054 (65.0), ORD-1092 (55.0) — 6 rows | Preview shows 6 heavyweight rows | |
| | **Turn 2:** `Actually, remove the one going to Iowa — it's too heavy for Ground. Ship the rest.` | Cancel, re-filter excluding IA (ORD-1016, Des Moines) — 5 remaining rows | New preview with 5 rows, no IA order | |
| 15.5 | **Turn 1:** `Ship all New Hampshire orders via 3 Day Select` | ORD-1067 (Concord, Barnes Educational), ORD-1088 (Concord, Anton Brooks) | Preview shows 2 rows | |
| | **Turn 2:** `Upgrade the service to overnight instead` | Cancel, re-preview same 2 rows with Next Day Air service | New preview with NDA, higher cost estimates | |
| | **Turn 3:** Confirm execution | Execute 2 shipments via NDA | Tracking numbers + labels for both | |
| 15.6 | **Turn 1:** `How many orders do we have per state?` | Exploratory query — agent may use `query_data` for GROUP BY | Returns state distribution (TX:5, CA:7, FL:8, etc.) | |
| | **Turn 2:** `Great, ship all the states with only 1 order each using Ground` | Complex filter: states with exactly 1 order (AZ→2, so excluded; CO, DC, DE, etc.) | Agent figures out single-order states and previews them | |

---

## Category 16: Excel-Specific Tests

Tests that the Excel (.xlsx) adapter produces identical behavior to the CSV adapter.

| # | Prompt | Prerequisite | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------|-------------------|---------------------|--------|
| 16.1 | `Ship all Texas orders using Ground` | Connect `test_data/sample_shipments.xlsx` instead of CSV | Same 5 TX rows as CSV test 1.1 | Results match CSV exactly | |
| 16.2 | `Ship all orders over 30 pounds via Ground` | Excel connected | Same 9 heavyweight rows as CSV test 1.5 | Weight filtering works identically | |
| 16.3 | `Ship all UPS Letter orders overnight` | Excel connected | Same 6 letter rows as CSV test 9.1 | Packaging type filter works | |
| 16.4 | `Ship orders for David Kim using 3 Day Select` | Excel connected | ORD-1004, San Francisco CA | Name filter works against Excel source | |
| 16.5 | `Ship all business orders to Connecticut via overnight` | Excel connected | ORD-1028 (Hall Precision), ORD-1044 (Collins Aerospace), ORD-1078 (Long Precision) | Company NOT NULL + state filter against Excel | |

---

## Category 17: Stress & Scale Tests

Tests system behavior at scale, with large result sets and edge conditions.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 17.1 | `Ship every single order in the file using Ground` | All 100 rows, Ground override | Preview shows 100 rows (may cap preview at 50 and extrapolate costs) | |
| 17.2 | `Ship all orders with declared value of exactly $0 and all orders with declared value over $3000 in one batch using overnight` | OR extreme: `declared_value = 0 OR declared_value > 3000` — 7 zero-value + 3 high-value = 10 orders | Preview shows 10 rows mixing documents and expensive items | |
| 17.3 | `Ship all orders where the recipient name starts with the letter S using Ground` | `recipient_name ILIKE 'S%'` — Sarah Mitchell, Stephanie Nguyen, Steven Hall, Samantha Lewis, Sean Collins, Shannon Evans, Seth Peterson | Preview shows ~7 rows starting with S | |
| 17.4 | `Ship all orders to cities that start with "San" using 2nd Day Air` | `city ILIKE 'San%'` — San Francisco, San Diego (x2), San Antonio, San Juan | Preview shows ~5 rows from "San" cities | |
| 17.5 | `Ship all orders to states with a 2-letter code starting with N using Ground` | `state LIKE 'N%'` — NY, NV, NJ, NM, NC, NH, ND, NE (various counts) | Preview shows orders from all N-states | |

---

## Category 18: Error Recovery & Resilience

Tests how the system handles errors gracefully without crashing.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 18.1 | `Ship all orders to Atlantis using Ground` | Zero results — no city matches | Agent reports 0 matching orders, no preview generated | |
| 18.2 | `Ship all orders for Elon Musk via overnight` | No matching recipient name | Agent reports 0 matching results gracefully | |
| 18.3 | `Ship all orders where the foobar column equals 5` | Non-existent column reference | Agent reports column doesn't exist, lists available columns | |
| 18.4 | `Ship order ORD-9999 using Ground` | Non-existent order number | Agent reports 0 matching orders | |
| 18.5 | `Ship all orders using FedEx Express` | Wrong carrier — system is UPS only | Agent clarifies that only UPS services are available, suggests UPS alternatives | |

---

## Category 19: Chained Logic & Derived Queries

Tests prompts that require the agent to perform intermediate reasoning or multiple logical steps.

| # | Prompt | Expected Behavior | Validation Criteria | Result |
|---|--------|-------------------|---------------------|--------|
| 19.1 | `Ship all orders that are going to the same city as David Kim using Ground` | Agent must first find David Kim → San Francisco, CA, then filter `city = 'San Francisco'` | Preview shows SF orders (at minimum ORD-1004) | |
| 19.2 | `Ship all the lightweight orders — under 5 lbs — that are currently set to Ground, but upgrade them to 2nd Day Air` | `weight_lbs < 5 AND service = 'Ground'` then override to 2nd Day Air | Preview shows lightweight Ground orders with 2nd Day Air service override | |
| 19.3 | `Ship all orders where the package volume exceeds 3000 cubic inches via Ground` | Agent computes `length_in * width_in * height_in > 3000` — need to calculate for each row | Preview shows orders exceeding 3000 cu in (e.g., ORD-1016: 36*24*20=17280, ORD-1054: 36*24*20=17280, etc.) | |
| 19.4 | `Ship the 3 most expensive orders that haven't been shipped yet using overnight` | `ORDER BY declared_value DESC LIMIT 3` — ORD-1084 ($5500), ORD-1056 ($4200), ORD-1044 ($3500) | Preview shows 3 rows: Bennett Aerospace, Mitchell Aviation, Collins Aerospace | |
| 19.5 | `Ship all the aerospace and aviation company orders overnight` | Company or description ILIKE '%aerospace%' OR '%aviation%' — ORD-1044 (Collins Aerospace Tech), ORD-1056 (Mitchell Aviation LLC), ORD-1084 (Bennett Aerospace Corp) | Preview shows 3 rows, all aviation/aerospace | |

---

## Execution Checklist

### Before Running Tests

- [ ] Backend running: `./scripts/start-backend.sh`
- [ ] Frontend running: `cd frontend && npm run dev`
- [ ] CSV connected: Upload `test_data/sample_shipments.csv` via sidebar
- [ ] Sidebar shows "CSV connected" with 100 rows
- [ ] UPS test credentials configured in `.env`
- [ ] Clear any previous test jobs from sidebar

### For Excel Tests (Category 16)

- [ ] Disconnect CSV first
- [ ] Upload `test_data/sample_shipments.xlsx` via sidebar
- [ ] Verify schema shows same 18 columns

### After Each Test

- [ ] Preview row count matches expected
- [ ] Correct UPS service appears in preview
- [ ] Cost estimates are present and reasonable
- [ ] For confirmed batches: tracking numbers appear in completion card
- [ ] Labels downloadable via "View Labels" button
- [ ] Job appears in sidebar history with correct status
- [ ] No console errors in browser DevTools

---

## Known Limitations

1. **Column names differ from Shopify** — this CSV uses `recipient_name`, `weight_lbs`, `declared_value` instead of Shopify's `customer_name`, `total_weight_grams`, `financial_status`. The agent must adapt SQL generation to the actual connected schema.
2. **No status columns** — unlike Shopify data, this CSV has no `financial_status` or `fulfillment_status` columns. Status-based filters will return errors.
3. **No date column** — there is no created_at or order_date column, so temporal filters ("today's orders", "this week") won't work.
4. **No tags column** — tag-based filtering is not applicable to this dataset.
5. **Service column contains text names** — values like "Ground", "Next Day Air" rather than numeric codes. Filters must use text matching.
6. **Puerto Rico address** — ORD-1065 (San Juan, PR) may require special UPS handling for territory shipping.
7. **Dimension NULLs** — UPS Letter rows have NULL dimensions; the payload builder should handle this gracefully.
8. **High declared values** — values like $5,500 (ORD-1084) may trigger special insurance requirements in production but should pass in test env.
9. **Duplicate cities** — Portland (OR + ME) and Charleston (SC + WV) appear in multiple states; city-only filters will return cross-state results.
