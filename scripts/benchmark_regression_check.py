#!/usr/bin/env python3
"""Non-blocking regression check for preview benchmark CSV outputs.

Compares current benchmark p50 values to baseline and warns when p50
is greater than 2x baseline for matching dataset/concurrency/mode keys.
Always exits 0 so it can be run in CI without blocking merges.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def _load_rows(path: Path) -> dict[tuple[str, str, str], float]:
    rows: dict[tuple[str, str, str], float] = {}
    with path.open("r", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = (row["dataset"], row["concurrency"], row["mode"])
            rows[key] = float(row["p50"])
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Check preview benchmark regressions.")
    parser.add_argument("--baseline", required=True, help="Baseline CSV path")
    parser.add_argument("--current", required=True, help="Current CSV path")
    args = parser.parse_args()

    baseline = _load_rows(Path(args.baseline))
    current = _load_rows(Path(args.current))

    warnings = 0
    for key, cur_p50 in current.items():
        base_p50 = baseline.get(key)
        if base_p50 is None:
            continue
        if base_p50 > 0 and cur_p50 > (2.0 * base_p50):
            warnings += 1
            print(
                "WARNING: regression key=%s dataset=%s concurrency=%s mode=%s "
                "baseline_p50=%.3f current_p50=%.3f"
                % (key, key[0], key[1], key[2], base_p50, cur_p50),
            )

    if warnings == 0:
        print("No p50 regressions >2x baseline detected.")
    else:
        print(f"Detected {warnings} p50 regression warning(s).")


if __name__ == "__main__":
    main()
