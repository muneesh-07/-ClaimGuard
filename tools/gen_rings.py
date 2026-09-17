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
# Genuinely different spellings, not casing/punctuation - ShopNormalizer's own docstring
# names "Auto Works" vs "Autoworks" as exactly the kind of gap it deliberately does NOT
# close ("a fuzzy-matching problem deferred to M9").
SHOP_SUFFIX_SPACING_VARIANTS = {"Auto Works": "Autoworks", "Car Care": "CarCare"}

# Real, well-known alternate names for these cities (pre/post-2014 renamings,
# or long-standing colonial-era names still in everyday use) - a genuine
# entity-resolution gap, unlike a punctuation or word-order difference:
# AddressNormalizer's abbreviation table has no way to know "Bangalore" and
# "Bengaluru" are the same city, because they aren't spelling variants of
# the same word, they're two different words for the same place.
CITY_ALIASES = {
    "Bengaluru": "Bangalore",
    "Mysuru": "Mysore",
    "Vizag": "Visakhapatnam",
    "Kochi": "Cochin",
}
# "Lake View" is the one multi-word street name in STREET_NAMES - concatenating
# it to "Lakeview" is a realistic data-entry variant that AddressNormalizer's
# tokenizer cannot collapse: sorting ["lake","view"] never equals sorting
# ["lakeview"], because they're a different number of tokens.
STREET_SPACING_VARIANTS = {"Lake View": "Lakeview"}

EPOCH = date(2026, 1, 1)
DAY_SPAN = 240

# The temporal train/validation/test split, as fractions of DAY_SPAN. A single
# definition imported by tools/eval.py rather than a second hardcoded 0.6/0.8 -
# the split boundary the generator uses to place held-out rings and the split
# boundary eval.py filters claims by must never be able to quietly disagree,
# the same reasoning as detector.py's FLAG_AT/REVIEW_AT or CanonicalJson.
TRAIN_FRACTION = 0.6
VAL_FRACTION = 0.2  # test gets the remaining 1 - TRAIN_FRACTION - VAL_FRACTION


# The day-offsets (from EPOCH) marking the train/val and val/test boundaries -
# the one place both the generator and the evaluator compute this split.
def split_day_offsets() -> tuple[int, int]:
    train_end = int(DAY_SPAN * TRAIN_FRACTION)
    val_end = int(DAY_SPAN * (TRAIN_FRACTION + VAL_FRACTION))
    return train_end, val_end


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


# Builds a random incident date within the generator's fixed date window, or a
# narrower [start_offset, end_offset] sub-window of it - used to force a ring's
# claims into a specific period (e.g. entirely after the temporal train/test
# split cutoff, for the held-out ring-injection ablation in tools/eval.py).
def random_date(rng: random.Random, start_offset: int = 0, end_offset: int = DAY_SPAN) -> str:
    return (EPOCH + timedelta(days=rng.randint(start_offset, end_offset))).isoformat()


# Introduces one adjacent-digit transposition into the number's trailing 9
# digits (never the leading digit, which must stay in 6-9 for the number to
# still parse as a valid Indian mobile number) - the kind of data-entry slip
# a real fraud ring makes typing the "same" number twice, which produces a
# DIFFERENT E.164 canonical value after normalization, not the same one with
# different formatting. This is deliberately harder than a formatting
# difference (which PhoneNormalizer already collapses for free): it's what
# actually requires a fuzzy-matching capability to recover.
def fuzz_phone_typo(rng: random.Random, phone: str) -> str:
    digits = list(phone)
    i = rng.randint(4, len(digits) - 2)
    digits[i], digits[i + 1] = digits[i + 1], digits[i]
    return "".join(digits)


# Introduces a realistic address variant that AddressNormalizer's deterministic,
# exact-match tokenizer cannot collapse: a real city alias (Bengaluru/Bangalore)
# or a multi-word street name concatenated into one word (Lake View/Lakeview).
# Falls back to the address unchanged if neither applies - not every address
# has a fuzzable city or street name, and forcing one would be unrealistic.
def fuzz_address_variant(rng: random.Random, address: str) -> str:
    fuzzed = address
    for city, alias in CITY_ALIASES.items():
        if city in fuzzed and rng.random() < 0.5:
            fuzzed = fuzzed.replace(city, alias)
    for street, spacing_variant in STREET_SPACING_VARIANTS.items():
        if street in fuzzed and rng.random() < 0.5:
            fuzzed = fuzzed.replace(street, spacing_variant)
    return fuzzed


# Introduces a genuine spelling variant of a shop's suffix (per SHOP_SUFFIX_SPACING_VARIANTS)
# - the exact gap ShopNormalizer's own docstring names as deliberately unclosed. Physical
# shops are real and harder to fake than a phone number (per docs/APPROACH.md), but the TEXT
# a claimant types for one still varies between people, which is what this simulates.
def fuzz_shop_variant(rng: random.Random, shop_name: str) -> str:
    fuzzed = shop_name
    for suffix, spacing_variant in SHOP_SUFFIX_SPACING_VARIANTS.items():
        if suffix in fuzzed and rng.random() < 0.5:
            fuzzed = fuzzed.replace(suffix, spacing_variant)
    return fuzzed


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
# entities" fingerprint described in docs/APPROACH.md. NOT every member shares the identical
# phone/address string: a real ring re-typing "the same" number across several claims makes
# transposition slips, and re-typing "the same" address uses whatever city/street spelling
# that member happens to use - fuzz_rate controls what fraction of members (after the first,
# which always keeps the exact shared values so at least a partial exact-match core survives)
# get a near-duplicate variant instead of an identical string. date_range constrains every
# member's incident_date to a sub-window (used to force held-out rings entirely into the
# test period for the ring-injection ablation); defaults to the generator's full date span.
def make_ring(rng: random.Random, ring_id: str, size: int, fuzz_rate: float = 0.25,
              date_range: tuple[int, int] = (0, DAY_SPAN)):
    shared_phone = random_phone(rng)
    shared_shop = random_shop(rng) if rng.random() < 0.8 else None
    shared_address = random_address(rng) if rng.random() < 0.3 else None

    members = []
    for i in range(size):
        phone = shared_phone
        address = shared_address or random_address(rng)
        shop = shared_shop or random_shop(rng)
        if i > 0:
            if rng.random() < fuzz_rate:
                phone = fuzz_phone_typo(rng, shared_phone)
            if shared_address and rng.random() < fuzz_rate:
                address = fuzz_address_variant(rng, shared_address)
            # Shops are real and physically harder to fake than a phone number, so this
            # gets a lower rate than phone/address - the claimant, not the shop, is
            # usually who mistypes it.
            if shared_shop and rng.random() < fuzz_rate * 0.6:
                shop = fuzz_shop_variant(rng, shared_shop)

        members.append(GeneratedClaim(
            claim_id=str(uuid.uuid4()),
            claimant_name=random_name(rng),
            policy_number=random_policy_number(rng),
            claim_amount=random_amount(rng),
            incident_date=random_date(rng, *date_range),
            claimant_phone=phone,
            claimant_address=address,
            repair_shop_name=shop,
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


# Writes the held-out ring-injection manifest: the ids of rings deliberately built to land
# entirely in the test period (see main()'s held_out_ring_ids), for tools/eval.py's ablation -
# "does graph structure recover a ring the model has never had a chance to see any part of."
def write_held_out_rings_csv(path: Path, held_out_ring_ids: set[str]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ring_id"])
        for ring_id in sorted(held_out_ring_ids):
            writer.writerow([ring_id])


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
    parser.add_argument("--fuzz-rate", type=float, default=0.25,
                         help="fraction of each ring's members (after the first) that get a near-duplicate "
                              "phone/address variant instead of an identical string")
    parser.add_argument("--held-out-rings", type=int, default=20,
                         help="additional rings built entirely within the test period's date range, for "
                              "the ring-injection ablation - a model trained on data before this window "
                              "has never seen any part of these rings")
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

    _train_end_day, val_end_day = split_day_offsets()

    ring_member_count = 0
    camouflage_count = 0
    for i in range(args.rings):
        ring_id = f"ring-{i:04d}"
        size = rng.randint(args.min_ring_size, args.max_ring_size)
        members, shared_phone, shared_shop, shared_address = make_ring(rng, ring_id, size, args.fuzz_rate)
        all_claims.extend(members)
        ring_member_count += len(members)

        if rng.random() < args.camouflage_rate:
            n_camouflage = rng.randint(1, 3)
            camo = make_camouflage_claims(rng, n_camouflage, shared_phone, shared_shop, shared_address)
            all_claims.extend(camo)
            camouflage_count += len(camo)

    # Held-out rings for the ring-injection ablation: same shape as an ordinary ring, but
    # date_range confines every member's incident_date to strictly after the val/test
    # boundary, so nothing about this ring exists anywhere in the train or validation period.
    held_out_ring_ids: set[str] = set()
    for i in range(args.held_out_rings):
        ring_id = f"heldout-{i:04d}"
        held_out_ring_ids.add(ring_id)
        size = rng.randint(args.min_ring_size, args.max_ring_size)
        members, _phone, _shop, _address = make_ring(
            rng, ring_id, size, args.fuzz_rate, date_range=(val_end_day + 1, DAY_SPAN))
        all_claims.extend(members)
        ring_member_count += len(members)

    rng.shuffle(all_claims)

    write_claims_csv(args.output_dir / "claims.csv", all_claims)
    write_ground_truth_csv(args.output_dir / "ground_truth_rings.csv", all_claims)
    write_held_out_rings_csv(args.output_dir / "held_out_rings.csv", held_out_ring_ids)

    print(f"Wrote {len(all_claims)} claims to {args.output_dir / 'claims.csv'}")
    print(f"  background:   {args.claims}")
    print(f"  ring members: {ring_member_count} across {args.rings + args.held_out_rings} rings "
          f"({args.held_out_rings} held out entirely in the test period)")
    print(f"  camouflage:   {camouflage_count}")
    print(f"  fuzz rate:    {args.fuzz_rate:.0%} of each ring's members (after the first) get a "
          f"near-duplicate phone/address instead of an identical one")
    print(f"Ground truth written to {args.output_dir / 'ground_truth_rings.csv'}")
    print(f"Held-out ring ids written to {args.output_dir / 'held_out_rings.csv'}")


if __name__ == "__main__":
    main()
