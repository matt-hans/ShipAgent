# ShipAgent Demo Guide

**Natural Language Batch Shipping — Live Demo Prompts**

This document contains curated prompts designed to showcase ShipAgent's ability to parse complex natural language commands and execute batch shipments across multiple data sources. Every prompt below has been verified against real data with 100% row selection accuracy.

---

## Prerequisites

1. Start the backend: `./scripts/start-backend.sh`
2. Start the frontend: `cd frontend && npm run dev`
3. Open `http://localhost:5173`

---

## Demo 1: CSV Data Source

**Setup:** Click the CSV upload button in the sidebar and upload `test_data/sample_shipments.csv` (100 rows, 18 columns covering all 50 US states + PR + DC).

### Prompt 1 — Multi-State with Weight and Value Filters

> Ship all orders going to California, Texas, or Florida where the weight is over 10 pounds and the declared value is above $200 — use Ground for everything

**What it demonstrates:** Triple-state OR filter combined with numeric threshold conditions on two different columns. The agent generates a compound SQL WHERE clause with `state IN ('CA', 'TX', 'FL') AND weight_lbs > 10 AND declared_value > 200`.

**Expected result:** 5 shipments

---

### Prompt 2 — Service-Based Filtering with Override

> Find all orders that are currently set to Next Day Air but weigh less than 2 pounds, and ship them using Ground instead to save on cost

**What it demonstrates:** The agent reads the existing `service` column value, applies a weight filter, then overrides the original service with a cheaper option. Shows the system's ability to reason about cost optimization.

**Expected result:** 4 shipments switched from Next Day Air to Ground

---

### Prompt 3 — Keyword Search Across Descriptions

> Ship all orders where the description mentions food or drink related items like spice, coffee, cheese, BBQ, or crawfish — use Ground for everything

**What it demonstrates:** Substring matching across a free-text description column using multiple ILIKE clauses with OR logic. Tests the agent's ability to parse a list of semantic keywords and generate the corresponding SQL.

**Expected result:** 7 shipments (coffee beans, Cajun spice blends, artisan cheese wheels, BBQ competition supplies, crawfish boil equipment)

---

### Prompt 4 — Business vs Personal with Geography

> Ship all orders going to companies in the Northeast — that means New York, Massachusetts, Connecticut, Pennsylvania, New Jersey, and Maine — use 2nd Day Air

**What it demonstrates:** The agent must understand "companies" means rows where the `company` column is NOT NULL, combine that with a 6-state geographic filter, and apply the correct UPS service code (02). Tests both null-checking and regional geography knowledge.

**Expected result:** 5 shipments to business recipients in the Northeast

---

### Prompt 5 — Dimensional Weight Logic

> Ship all orders where any single dimension exceeds 24 inches — those are oversized packages and should go Ground

**What it demonstrates:** The agent generates a compound OR across three dimension columns (`length_in > 24 OR width_in > 24 OR height_in > 24`). Tests understanding of physical package attributes and the concept of oversized shipments.

**Expected result:** 10 shipments with at least one oversized dimension

---

### Prompt 6 — Negative Filter with Value Threshold

> Ship everything except orders going to California or New York, but only if the declared value is under $100 — use 3 Day Select

**What it demonstrates:** Exclusion filter (`state NOT IN ('CA', 'NY')`) combined with a ceiling value threshold. Tests the agent's ability to parse negation ("except") in natural language and combine it with additional conditions.

**Expected result:** 22 shipments to non-CA/NY states under $100 declared value

---

## Demo 2: Excel Data Source

**Setup:** Click the Excel upload button and upload `test_data/sample_shipments.xlsx`. This is the same dataset as the CSV, demonstrating source-agnostic processing.

### Prompt 7 — Regional Exclusion with Weight Band

> Ship all orders from New England states — Connecticut, Massachusetts, Vermont, New Hampshire, Maine, and Rhode Island — but only packages between 2 and 15 pounds, use Ground

**What it demonstrates:** 6-state inclusion filter combined with a weight band (BETWEEN or double inequality). Tests geographic knowledge and range-based filtering from an Excel source.

**Expected result:** 3 shipments within the 2-15 lb weight band from New England

---

### Prompt 8 — Semantic Product Search from Excel

> Ship all orders where the description mentions food or drink related items like spice, coffee, cheese, BBQ, or crawfish — use Ground for everything

**What it demonstrates:** Identical prompt to CSV Demo Prompt 3, but run against the Excel adapter. Proves the agent produces the same correct results regardless of whether the data comes from CSV or Excel — true source-agnostic processing.

**Expected result:** 7 shipments (identical to CSV result)

---

## Demo 3: Shopify Live Data

**Setup:** Click "Use Shopify" in the sidebar. The agent auto-detects environment credentials and connects to your Shopify store. No manual configuration needed.

### Prompt 9 — Order Status + Weight with Type Casting

> Ship all Texas orders that are paid and unfulfilled, but only the ones heavier than 1 pound — use Ground

**What it demonstrates:** Triple-condition filter combining state geography, financial status, fulfillment status, AND a weight threshold that requires type casting (Shopify stores `total_weight_grams` as VARCHAR). The agent must also convert "1 pound" to 453 grams. If the initial query fails on type mismatch, the agent self-corrects with a CAST expression.

**Expected result:** 5 shipments from Texas cities (Houston, San Antonio, Dallas, Austin, El Paso)

---

### Prompt 10 — Compound OR with Mixed Column Types

> Ship all California orders that either have more than 5 items or cost more than $200 — use 2nd Day Air

**What it demonstrates:** State filter combined with an OR condition across two different column types — integer (`item_count`) and currency (`total_price`). Tests the agent's ability to parse "either...or" as SQL OR logic rather than AND. Against a live Shopify store with 88 orders.

**Expected result:** 11 shipments from California meeting either threshold

---

## Demo Flow Tips

**For maximum impact during a live demo:**

1. **Start with CSV Prompt 1** — shows multi-condition filtering right away
2. **Follow with Prompt 3** — keyword search across descriptions is visually impressive
3. **Switch to Excel Prompt 8** — same prompt, same results, different source = "wow" moment
4. **End with Shopify Prompt 10** — live data with compound OR logic is the strongest closer

**Key talking points at each step:**

- **Preview step**: Point out the row count, total cost estimate, and zero warnings — the system got it right on the first try
- **Confirm step**: Emphasize the safety gate — nothing ships without explicit confirmation
- **Completion artifact**: Show the inline label access — labels are immediately available, no separate download step
- **Sidebar**: Note the job appears in history with full audit trail

**If asked "what happens under the hood":**

The user's natural language is parsed by the Claude agent, which generates a SQL WHERE clause against the connected data source schema. Deterministic tools execute the query — the LLM never touches row data directly. Each row is independently rated via the UPS API, costs are aggregated, and the preview is shown for confirmation before any shipment is created.

---

## Verified Results Summary

| Source | Prompts | Total Shipments | Accuracy |
|--------|---------|-----------------|----------|
| CSV | 6 prompts | 53 shipments | 100% |
| Excel | 2 prompts | 10 shipments | 100% |
| Shopify | 2 prompts | 16 shipments | 100% |
| **Total** | **10 prompts** | **79 shipments** | **100%** |

Every result was independently verified against the raw data source before and after execution.
