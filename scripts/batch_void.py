#!/usr/bin/env python3
"""Batch void UPS shipments via UPS MCP client.

Usage:
    cd /Users/matthewhans/Desktop/Programming/ShipAgent
    set -a && source .env && set +a
    python scripts/batch_void.py
"""

import asyncio
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.keyring_store import KeyringStore
from src.services.ups_mcp_client import UPSMCPClient
from src.services.errors import UPSServiceError

# All tracking numbers extracted from user's list.
# Some entries had two tracking numbers concatenated — split manually.
TRACKING_NUMBERS: list[str] = [
    # 02/23/2026
    "1Z129D9Y0324240161",
    "1Z129D9Y0319773515",
    "1Z129D9Y0315447107",
    "1Z129D9Y0318380898",
    "1Z129D9Y0324160953",
    "1Z129D9Y0302330882",
    "1Z129D9Y0314733077",
    "1Z129D9Y0321151147",
    "1Z129D9Y0307103467",
    "1Z129D9Y0317438051",
    "1Z129D9Y0328294730",
    "1Z129D9Y0304612841",
    "1Z129D9Y0314783835",
    "1Z129D9Y0319787028",
    "1Z129D9Y0307538417",
    "1Z129D9Y0334915726",
    "1Z129D9Y0332978118",
    "1Z129D9Y0304434007",
    "1Z129D9Y0327485900",
    "1Z129D9Y0309749794",
    "1Z129D9Y0330883090",
    "1Z129D9Y0302041784",
    "1Z129D9Y0321453688",
    "1Z129D9Y0325721676",
    # Javonte Heaney 02/23 — two tracking numbers
    "1Z129D9Y0317545971",
    "1Z129D9Y0300578360",
    "1Z129D9Y0305934957",
    "1Z129D9Y0324851064",
    "1Z129D9Y0313291743",
    "1Z129D9Y0325045853",
    # 02/18/2026
    "1Z129D9Y6627135107",
    "1Z129D9Y6830044295",
    "1Z129D9Y0432446888",
    "1Z129D9Y0105348460",
    "1Z129D9Y0316783055",
    "1Z129D9Y0336066873",
    "1Z129D9Y0203057848",
    "1Z129D9Y0310328834",
    "1Z129D9Y1229268268",
    "1Z129D9Y0310432024",
    "1Z129D9Y0311283416",
    "1Z129D9Y0337455058",
    "1Z129D9Y0337471245",
    "1Z129D9Y1236000836",
    "1Z129D9Y0119279009",
    "1Z129D9Y0313694791",
    "1Z129D9Y0113086782",
    "1Z129D9Y0113690977",
    "1Z129D9Y0131967822",
    # James Thornton 02/18 — two tracking numbers
    "1Z129D9Y0122936211",
    "1Z129D9Y0335510009",
    "1Z129D9Y0319823363",
    "1Z129D9Y0306279959",
    "1Z129D9Y0339733191",
    "1Z129D9Y0327489782",
    "1Z129D9Y0312736747",
    "1Z129D9Y0310149733",
    "1Z129D9Y0334903775",
    "1Z129D9Y0319154925",
    "1Z129D9Y0300468318",
    "1Z129D9Y0317285903",
    "1Z129D9Y0328739161",
    "1Z129D9Y0336799957",
    "1Z129D9Y0322330148",
    "1Z129D9Y0322413737",
    "1Z129D9Y0330374729",
    "1Z129D9Y0322177118",
    "1Z129D9Y0326824901",
    "1Z129D9Y0309683695",
    "1Z129D9Y0301017688",
    "1Z129D9Y0316323873",
    "1Z129D9Y0320762097",
    "1Z129D9Y0312718267",
    "1Z129D9Y0304035644",
    # Sadie VonRueden 02/18 — two tracking numbers
    "1Z129D9Y0301796855",
    "1Z129D9Y0315190634",
    "1Z129D9Y0304697822",
    "1Z129D9Y0306073215",
    "1Z129D9Y0326272687",
    "1Z129D9Y0319312807",
    # 02/17/2026
    "1Z129D9Y0333880677",
    "1Z129D9Y0328750068",
    "1Z129D9Y0321084854",
    "1Z129D9Y0305292598",
    "1Z129D9Y0312168585",
    "1Z129D9Y0313776774",
    "1Z129D9Y0320529045",
    "1Z129D9Y0300033162",
    "1Z129D9Y0334566630",
    "1Z129D9Y0330921628",
    "1Z129D9Y0319333759",
    "1Z129D9Y0323958013",
    "1Z129D9Y0312954547",
    "1Z129D9Y0301451539",
    "1Z129D9Y0303060725",
    "1Z129D9Y0304098112",
    "1Z129D9Y0325079808",
    "1Z129D9Y0301359701",
    "1Z129D9Y0316521499",
    # Delilah Orn 02/17 — two tracking numbers
    "1Z129D9Y0302539489",
    "1Z129D9Y0337130998",
    "1Z129D9Y0332795584",
    "1Z129D9Y0336997573",
    "1Z129D9Y0333300963",
    "1Z129D9Y0334309757",
    "1Z129D9Y0302049679",
    "1Z129D9Y0336067943",
    "1Z129D9Y0336459538",
    "1Z129D9Y0317768061",
    "1Z129D9Y0314890657",
]

# Concurrency limit to avoid overwhelming UPS API
CONCURRENCY = 5


async def void_one(
    ups: UPSMCPClient,
    semaphore: asyncio.Semaphore,
    tracking: str,
    index: int,
    total: int,
) -> tuple[str, bool, str]:
    """Void a single shipment. Returns (tracking, success, message)."""
    async with semaphore:
        try:
            result = await ups.void_shipment(shipment_id=tracking)
            success = result.get("success", False)
            desc = result.get("status", {}).get("description", "OK")
            status_str = "VOIDED" if success else f"FAILED ({desc})"
            print(f"  [{index}/{total}] {tracking} → {status_str}")
            return (tracking, success, desc)
        except UPSServiceError as e:
            print(f"  [{index}/{total}] {tracking} → ERROR: {e.code} - {e.message}")
            return (tracking, False, f"{e.code}: {e.message}")
        except Exception as e:
            print(f"  [{index}/{total}] {tracking} → EXCEPTION: {e}")
            return (tracking, False, str(e))


async def main() -> None:
    """Void all listed shipments via UPS MCP."""
    # Load credentials from keyring → env
    store = KeyringStore()
    store.load_all_to_env()

    client_id = os.environ.get("UPS_CLIENT_ID", "")
    client_secret = os.environ.get("UPS_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print("ERROR: UPS_CLIENT_ID and UPS_CLIENT_SECRET must be set in environment or keyring.")
        sys.exit(1)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for tn in TRACKING_NUMBERS:
        if tn not in seen:
            seen.add(tn)
            unique.append(tn)

    total = len(unique)
    print(f"\n{'='*60}")
    print(f"  UPS Batch Void — {total} shipments")
    print(f"  Concurrency: {CONCURRENCY}")
    print(f"{'='*60}\n")

    voided: list[str] = []
    failed: list[tuple[str, str]] = []

    start = time.monotonic()

    async with UPSMCPClient(
        client_id=client_id,
        client_secret=client_secret,
    ) as ups:
        semaphore = asyncio.Semaphore(CONCURRENCY)

        # Process in batches of CONCURRENCY to maintain ordering in output
        tasks = [
            void_one(ups, semaphore, tn, i + 1, total)
            for i, tn in enumerate(unique)
        ]
        results = await asyncio.gather(*tasks)

    elapsed = time.monotonic() - start

    # Tally results
    for tracking, success, msg in results:
        if success:
            voided.append(tracking)
        else:
            failed.append((tracking, msg))

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS — {elapsed:.1f}s elapsed")
    print(f"{'='*60}")
    print(f"  Voided:  {len(voided)}/{total}")
    print(f"  Failed:  {len(failed)}/{total}")

    if failed:
        print(f"\n  FAILED SHIPMENTS:")
        for tn, reason in failed:
            print(f"    {tn} — {reason}")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
