#!/usr/bin/env python3
"""
Synthetic claim generator with planted fraud rings and known ground truth.

Real insurance fraud-network data is confidential and no public dataset has
the shared-entity structure ring detection needs (see docs/APPROACH.md §3),
so this script is how ClaimGuard gets labelled data to measure precision
and recall against. It writes two files:

  claims.csv           - every claim (background + ring + camouflage),
                          shaped exactly like ClaimRequest so it can be
                          loaded straight into the `claims` table.
  ground_truth_rings.csv - claim_id -> ring_id, for ring members ONLY.
                          Camouflage and background-collision claims are
                          deliberately left out: they exist to make life
                          hard for the detector, not to be graded against.

Deliberately zero third-party dependencies (stdlib only), so cloning the
repo and running this script never needs a `pip install` first.
"""

import argparse
import csv
import random
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

FIRST_NAMES = [
    "Asha", "Ravi", "Priya", "Arjun", "Meera", "Vikram", "Kavya", "Rahul",
    "Divya", "Sanjay", "Anita", "Karthik", "Neha", "Suresh", "Pooja",
    "Manoj", "Deepa", "Ajay", "Swati", "Rohit", "Lakshmi", "Vijay",
]
LAST_NAMES = [
    "Menon", "Kumar", "Sharma", "Nair", "Reddy", "Iyer", "Gupta", "Rao",
    "Pillai", "Verma", "Naidu", "Joshi", "Desai", "Bhatt", "Krishnan",
]
CITIES = [
    "Coimbatore", "Bengaluru", "Chennai", "Hyderabad", "Pune", "Kochi",
    "Mysuru", "Madurai", "Vizag", "Nagpur",
]
STREET_NAMES = [
    "Lake View", "MG", "Anna", "Gandhi", "Nehru", "Church", "Market",
    "Temple", "Station", "Ring", "Marina", "Hill",
]
ROAD_TYPES = ["Road", "Street", "Avenue", "Lane", "Cross"]
SHOP_PREFIXES = [
    "SpeedFix", "Metro", "Royal", "Prime", "City", "Elite", "Super",
    "National", "Sri", "Star",
]
SHOP_SUFFIXES = ["Auto Works", "Motors", "Garage", "Car Care", "Automobiles"]

EPOCH = date(2026, 1, 1)
DAY_SPAN = 240


@dataclass
class GeneratedClaim:
    claim_id: str
    claimant_name: str
    policy_number: str
    claim_amount: str
    incident_date: str
    claimant_phone: str
    claimant_address: str
    repair_shop_name: str
    ring_id: str | None = None


# Builds one policy number that looks like the format already used in README examples (POL-XXXXX).
def random_policy_number(rng: random.Random) -> str:
    return f"POL-{rng.randint(10000, 99999)}"


# Builds a plausible claimant full name from independent first/last name pools.
def random_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


# Builds an Indian-style mobile number in E.164 form; format variety (the messy formatting
# PhoneNormalizer has to handle) is intentionally NOT added here - that's exercised by
# hand-written unit tests, not generated data, so ground truth stays unambiguous.
def random_phone(rng: random.Random) -> str:
    return f"+91{rng.randint(6, 9)}{rng.randint(100000000, 999999999)}"


# Builds a plausible street address in one of the seeded cities.
def random_address(rng: random.Random) -> str:
    house_number = rng.randint(1, 200)
    street = rng.choice(STREET_NAMES)
    road_type = rng.choice(ROAD_TYPES)
    city = rng.choice(CITIES)
    return f"{house_number} {street} {road_type}, {city}"


# Builds a plausible repair shop name.
def random_shop(rng: random.Random) -> str:
    return f"{rng.choice(SHOP_PREFIXES)} {rng.choice(SHOP_SUFFIXES)}"


# Builds a random claim amount in a realistic auto-claim band, as a fixed-scale decimal string.
def random_amount(rng: random.Random) -> str:
    return f"{rng.uniform(5000, 150000):.2f}"


# Builds a random incident date within the generator's fixed date window.
def random_date(rng: random.Random) -> str:
    return (EPOCH + timedelta(days=rng.randint(0, DAY_SPAN))).isoformat()


# Generates one ordinary, unconnected claim - the "background" population a ring has to stand out against.
def make_background_claim(rng: random.Random) -> GeneratedClaim:
    return GeneratedClaim(
        claim_id=str(uuid.uuid4()),
        claimant_name=random_name(rng),
        policy_number=random_policy_number(rng),
        claim_amount=random_amount(rng),
        incident_date=random_date(rng),
        claimant_phone=random_phone(rng),
        claimant_address=random_address(rng),
        repair_shop_name=random_shop(rng),
    )


# Forces a small number of otherwise-unrelated background claims to share one entity, simulating
# the coincidental sharing that happens in real life (family members, a popular repair shop) -
# required so precision is measured against realistic noise, not a suspiciously edge-free graph.
def apply_background_collisions(rng: random.Random, claims: list[GeneratedClaim], rate: float) -> None:
    collision_count = int(len(claims) * rate)
    for _ in range(collision_count):
        a, b = rng.sample(claims, 2)
        shared_field = rng.choice(["claimant_phone", "claimant_address", "repair_shop_name"])
        setattr(b, shared_field, getattr(a, shared_field))


# Builds one fraud ring: `size` distinct claimant identities that all share the same phone
# number, and usually the same repair shop and/or address - the "many claimants, few real
# entities" fingerprint described in docs/APPROACH.md.
def make_ring(rng: random.Random, ring_id: str, size: int):
    shared_phone = random_phone(rng)
    shared_shop = random_shop(rng) if rng.random() < 0.8 else None
    shared_address = random_address(rng) if rng.random() < 0.3 else None

    members = []
    for _ in range(size):
        members.append(GeneratedClaim(
            claim_id=str(uuid.uuid4()),
            claimant_name=random_name(rng),
            policy_number=random_policy_number(rng),
            claim_amount=random_amount(rng),
            incident_date=random_date(rng),
            claimant_phone=shared_phone,
            claimant_address=shared_address or random_address(rng),
            repair_shop_name=shared_shop or random_shop(rng),
            ring_id=ring_id,
        ))
    return members, shared_phone, shared_shop, shared_address


# Generates camouflage claims for a ring: claims that touch one of the ring's shared entities
# (diluting how suspicious that entity looks) but are filed by unrelated identities and are
# deliberately excluded from ground truth - they exist to test whether the detector can still
# find the ring despite the padding, per the FRAUDAR-style camouflage discussed in APPROACH.md.
def make_camouflage_claims(rng: random.Random, count: int, shared_phone: str,
                            shared_shop: str | None, shared_address: str | None) -> list[GeneratedClaim]:
    claims = []
    for _ in range(count):
        claim = make_background_claim(rng)
        touch = rng.choice(["shop", "address"] if shared_shop or shared_address else ["phone"])
        if touch == "shop" and shared_shop:
            claim.repair_shop_name = shared_shop
        elif touch == "address" and shared_address:
            claim.claimant_address = shared_address
        else:
            claim.claimant_phone = shared_phone
        claims.append(claim)
    return claims


# Writes the full claim set to claims.csv, in the same field order ClaimRequest expects.
def write_claims_csv(path: Path, claims: list[GeneratedClaim]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "claim_id", "claimant_name", "policy_number", "claim_amount",
            "incident_date", "claimant_phone", "claimant_address", "repair_shop_name",
        ])
        for c in claims:
            writer.writerow([
                c.claim_id, c.claimant_name, c.policy_number, c.claim_amount,
                c.incident_date, c.claimant_phone, c.claimant_address, c.repair_shop_name,
            ])


# Writes the ground-truth membership file: one row per claim that is genuinely part of a ring.
def write_ground_truth_csv(path: Path, claims: list[GeneratedClaim]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["claim_id", "ring_id"])
        for c in claims:
            if c.ring_id is not None:
                writer.writerow([c.claim_id, c.ring_id])


# Parses command-line arguments for the generator.
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--claims", type=int, default=2000, help="number of background (non-ring) claims")
    parser.add_argument("--rings", type=int, default=10, help="number of fraud rings to plant")
    parser.add_argument("--min-ring-size", type=int, default=4)
    parser.add_argument("--max-ring-size", type=int, default=12)
    parser.add_argument("--camouflage-rate", type=float, default=0.3,
                         help="fraction of rings that also file camouflage claims")
    parser.add_argument("--background-collision-rate", type=float, default=0.02,
                         help="fraction of background claims forced to coincidentally share an entity")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    return parser.parse_args()


# Orchestrates generation end to end: background population, planted rings, camouflage,
# background collisions, then writes both output files and prints a summary.
def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_claims: list[GeneratedClaim] = [make_background_claim(rng) for _ in range(args.claims)]
    apply_background_collisions(rng, all_claims, args.background_collision_rate)

    ring_member_count = 0
    camouflage_count = 0
    for i in range(args.rings):
        ring_id = f"ring-{i:04d}"
        size = rng.randint(args.min_ring_size, args.max_ring_size)
        members, shared_phone, shared_shop, shared_address = make_ring(rng, ring_id, size)
        all_claims.extend(members)
        ring_member_count += len(members)

        if rng.random() < args.camouflage_rate:
            n_camouflage = rng.randint(1, 3)
            camo = make_camouflage_claims(rng, n_camouflage, shared_phone, shared_shop, shared_address)
            all_claims.extend(camo)
            camouflage_count += len(camo)

    rng.shuffle(all_claims)

    write_claims_csv(args.output_dir / "claims.csv", all_claims)
    write_ground_truth_csv(args.output_dir / "ground_truth_rings.csv", all_claims)

    print(f"Wrote {len(all_claims)} claims to {args.output_dir / 'claims.csv'}")
    print(f"  background:  {args.claims}")
    print(f"  ring members: {ring_member_count} across {args.rings} rings")
    print(f"  camouflage:  {camouflage_count}")
    print(f"Ground truth written to {args.output_dir / 'ground_truth_rings.csv'}")


if __name__ == "__main__":
    main()
