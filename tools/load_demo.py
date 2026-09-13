#!/usr/bin/env python3
"""
Loads a small slice of a generated claims.csv through the real API
(POST /api/claims), one HTTP call per claim.

This is the "small demo set" path from docs/EXECUTION_PLAN.md M4: going
through the real endpoint exercises entity resolution and writes the
CLAIM_CREATED audit event for each claim, exactly like a real submission
would. It does NOT scale to 50k rows - that's tools/gen_rings.py's larger
output, which is meant for a bulk COPY plus the backend's
POST /api/entities/resolve-backlog pass instead (see PROJECT_GUIDE.md).

Zero third-party dependencies: uses urllib from the standard library so
running this never needs a `pip install` first.
"""

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


# Sends one claim as a POST /api/claims request and returns True if the server accepted it.
def post_claim(base_url: str, row: dict) -> bool:
    payload = {
        "claimantName": row["claimant_name"],
        "policyNumber": row["policy_number"],
        "claimAmount": row["claim_amount"],
        "incidentDate": row["incident_date"],
        "claimantPhone": row["claimant_phone"],
        "claimantAddress": row["claimant_address"],
        "repairShopName": row["repair_shop_name"] or None,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/claims", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.status == 201
    except urllib.error.HTTPError as e:
        print(f"  claim {row['claim_id']} rejected: {e.code} {e.read().decode('utf-8', errors='replace')}",
              file=sys.stderr)
        return False


# Parses command-line arguments for the loader.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--claims-csv", type=Path, default=Path("data/claims.csv"))
    parser.add_argument("--count", type=int, default=200, help="how many rows from the top of the CSV to load")
    parser.add_argument("--base-url", default="http://localhost:8080")
    return parser.parse_args()


# Reads the first N rows of the CSV and POSTs each one, reporting a running success/failure count.
def main() -> None:
    args = parse_args()
    with args.claims_csv.open() as f:
        rows = list(csv.DictReader(f))[:args.count]

    succeeded = 0
    for i, row in enumerate(rows, start=1):
        if post_claim(args.base_url, row):
            succeeded += 1
        if i % 50 == 0 or i == len(rows):
            print(f"  {i}/{len(rows)} posted ({succeeded} succeeded)")

    print(f"Done: {succeeded}/{len(rows)} claims loaded into {args.base_url}")


if __name__ == "__main__":
    main()
