#!/usr/bin/env python3
"""Benchmark BatchEngine preview latency against real UPS sandbox.

Runs warm and cold preview benchmarks for synthetic dataset sizes and
concurrency settings, then prints p50/p95 and retry/reconnect counters.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from dataclasses import dataclass
from typing import Any

from src.services.batch_engine import BatchEngine
from src.services.ups_mcp_client import UPSMCPClient
from src.services.ups_payload_builder import build_shipper


@dataclass
class BenchRow:
    """Minimal row object compatible with BatchEngine.preview()."""

    row_number: int
    order_data: str


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _parse_csv_ints(raw: str) -> list[int]:
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(len(ordered) * p) - 1))
    return ordered[idx]


def _build_rows(size: int, service_code: str = "03") -> list[BenchRow]:
    states = ["CA", "TX", "NY", "FL", "WA", "IL", "CO", "GA", "NC", "AZ"]
    cities = {
        "CA": "Los Angeles",
        "TX": "Austin",
        "NY": "New York",
        "FL": "Miami",
        "WA": "Seattle",
        "IL": "Chicago",
        "CO": "Denver",
        "GA": "Atlanta",
        "NC": "Charlotte",
        "AZ": "Phoenix",
    }
    zips = {
        "CA": "90001",
        "TX": "73301",
        "NY": "10001",
        "FL": "33101",
        "WA": "98101",
        "IL": "60601",
        "CO": "80201",
        "GA": "30301",
        "NC": "28201",
        "AZ": "85001",
    }
    rows: list[BenchRow] = []
    for i in range(1, size + 1):
        state = states[(i - 1) % len(states)]
        payload = {
            "order_id": f"bench-{i}",
            "ship_to_name": f"Benchmark Recipient {i}",
            "ship_to_address1": "123 Benchmark Ave",
            "ship_to_city": cities[state],
            "ship_to_state": state,
            "ship_to_postal_code": zips[state],
            "ship_to_country": "US",
            "service_code": service_code,
            "weight": 1.0 + (i % 5) * 0.5,
            "ship_to_residential": i % 2 == 0,
        }
        rows.append(BenchRow(row_number=i, order_data=json.dumps(payload)))
    return rows


async def _run_preview_once(
    *,
    client: UPSMCPClient,
    rows: list[BenchRow],
    shipper: dict[str, Any],
    dataset_size: int,
) -> dict[str, float]:
    engine = BatchEngine(
        ups_service=client,
        db_session=None,
        account_number=os.environ.get("UPS_ACCOUNT_NUMBER", ""),
    )
    retries_before = client.retry_attempts_total
    reconnects_before = client.reconnect_count
    started = time.perf_counter()
    result = await engine.preview(
        job_id=f"bench-{dataset_size}-{int(started * 1000)}",
        rows=rows,
        shipper=shipper,
    )
    elapsed = time.perf_counter() - started
    retries_after = client.retry_attempts_total
    reconnects_after = client.reconnect_count
    return {
        "elapsed": elapsed,
        "rows_total": float(result.get("total_rows", 0)),
        "rows_rated": float(len(result.get("preview_rows", []))),
        "retries": float(retries_after - retries_before),
        "reconnects": float(reconnects_after - reconnects_before),
    }


async def _benchmark_variant(
    *,
    runs: int,
    dataset_size: int,
    concurrency: int,
    mode: str,
    client_id: str,
    client_secret: str,
    environment: str,
) -> dict[str, float]:
    rows = _build_rows(dataset_size)
    shipper = build_shipper()
    os.environ["BATCH_CONCURRENCY"] = str(concurrency)
    os.environ["BATCH_PREVIEW_MAX_ROWS"] = str(dataset_size)

    samples: list[float] = []
    retries = 0.0
    reconnects = 0.0
    rows_rated = 0.0

    if mode == "warm":
        async with UPSMCPClient(
            client_id=client_id,
            client_secret=client_secret,
            environment=environment,
            account_number=os.environ.get("UPS_ACCOUNT_NUMBER", ""),
        ) as client:
            for _ in range(runs):
                outcome = await _run_preview_once(
                    client=client,
                    rows=rows,
                    shipper=shipper,
                    dataset_size=dataset_size,
                )
                samples.append(outcome["elapsed"])
                retries += outcome["retries"]
                reconnects += outcome["reconnects"]
                rows_rated = outcome["rows_rated"]
    else:
        for _ in range(runs):
            async with UPSMCPClient(
                client_id=client_id,
                client_secret=client_secret,
                environment=environment,
                account_number=os.environ.get("UPS_ACCOUNT_NUMBER", ""),
            ) as client:
                outcome = await _run_preview_once(
                    client=client,
                    rows=rows,
                    shipper=shipper,
                    dataset_size=dataset_size,
                )
                samples.append(outcome["elapsed"])
                retries += outcome["retries"]
                reconnects += outcome["reconnects"]
                rows_rated = outcome["rows_rated"]

    return {
        "runs": float(runs),
        "dataset_size": float(dataset_size),
        "concurrency": float(concurrency),
        "mode": mode,
        "p50": statistics.median(samples),
        "p95": _percentile(samples, 0.95),
        "avg": statistics.mean(samples),
        "rows_rated": rows_rated,
        "retries_total": retries,
        "reconnects_total": reconnects,
    }


async def _main_async(args: argparse.Namespace) -> None:
    client_id = _require_env("UPS_CLIENT_ID")
    client_secret = _require_env("UPS_CLIENT_SECRET")
    _require_env("UPS_ACCOUNT_NUMBER")

    base_url = os.environ.get("UPS_BASE_URL", "https://wwwcie.ups.com")
    environment = "test" if "wwwcie" in base_url else "production"
    datasets = _parse_csv_ints(args.datasets)
    concurrencies = _parse_csv_ints(args.concurrency)
    modes = ["warm", "cold"] if args.mode == "both" else [args.mode]

    print(
        f"Benchmark start: runs={args.runs} datasets={datasets} "
        f"concurrency={concurrencies} mode={modes} env={environment}",
    )
    print("dataset,concurrency,mode,p50,p95,avg,rows_rated,retries,reconnects")

    for dataset_size in datasets:
        for concurrency in concurrencies:
            for mode in modes:
                result = await _benchmark_variant(
                    runs=args.runs,
                    dataset_size=dataset_size,
                    concurrency=concurrency,
                    mode=mode,
                    client_id=client_id,
                    client_secret=client_secret,
                    environment=environment,
                )
                print(
                    f"{int(result['dataset_size'])},"
                    f"{int(result['concurrency'])},"
                    f"{result['mode']},"
                    f"{result['p50']:.3f},"
                    f"{result['p95']:.3f},"
                    f"{result['avg']:.3f},"
                    f"{int(result['rows_rated'])},"
                    f"{int(result['retries_total'])},"
                    f"{int(result['reconnects_total'])}",
                )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark UPS preview latency.")
    parser.add_argument("--runs", type=int, default=20, help="Runs per variant")
    parser.add_argument(
        "--datasets",
        type=str,
        default="22,50,100",
        help="Comma-separated dataset sizes",
    )
    parser.add_argument(
        "--concurrency",
        type=str,
        default="5,8,10",
        help="Comma-separated BATCH_CONCURRENCY values",
    )
    parser.add_argument(
        "--mode",
        choices=["warm", "cold", "both"],
        default="both",
        help="Benchmark warm, cold, or both",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
