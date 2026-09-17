#!/usr/bin/env python3
"""
Tests for gen_rings.py. Standard-library unittest only, so running the
generator's test suite never needs a pip install either. Run with:

    python3 -m unittest tools.test_gen_rings -v
"""

import random
import unittest
from datetime import date

import gen_rings


class MakeRingTests(unittest.TestCase):

    # With fuzzing off, every member must still share exactly one phone number - the
    # pre-fuzzing behavior must remain reachable, not just the fuzzy default.
    def test_all_members_share_one_phone_when_fuzz_rate_is_zero(self):
        rng = random.Random(1)
        members, shared_phone, _, _ = gen_rings.make_ring(rng, "ring-0000", size=6, fuzz_rate=0.0)

        self.assertEqual(len(members), 6)
        self.assertTrue(all(m.claimant_phone == shared_phone for m in members))
        self.assertTrue(all(m.ring_id == "ring-0000" for m in members))

    # The first member always keeps the exact shared phone (an exact-match anchor for the
    # ring), even at a high fuzz rate - otherwise a ring could end up with NO two members
    # sharing anything at all, which wouldn't be a ring by this project's own definition.
    def test_first_member_always_keeps_the_exact_shared_phone(self):
        rng = random.Random(7)
        members, shared_phone, _, _ = gen_rings.make_ring(rng, "ring-0002", size=6, fuzz_rate=1.0)

        self.assertEqual(members[0].claimant_phone, shared_phone)

    # A high fuzz rate must actually produce at least one member whose phone differs from
    # the shared one - otherwise fuzz_rate would be a parameter that does nothing.
    def test_high_fuzz_rate_produces_phone_variants(self):
        rng = random.Random(8)
        members, shared_phone, _, _ = gen_rings.make_ring(rng, "ring-0003", size=10, fuzz_rate=1.0)

        variant_phones = [m.claimant_phone for m in members[1:] if m.claimant_phone != shared_phone]
        self.assertGreater(len(variant_phones), 0)
        # A fuzzed phone must still be a same-length, same-leading-digit, PARSEABLE
        # number - it's meant to simulate a typo, not corrupt the field into garbage.
        for phone in variant_phones:
            self.assertEqual(len(phone), len(shared_phone))
            self.assertEqual(phone[:4], shared_phone[:4])
            self.assertNotEqual(phone, shared_phone)

    # date_range must actually constrain every member's incident_date - this is the
    # mechanism the held-out ring-injection ablation depends on entirely.
    def test_date_range_confines_every_members_incident_date(self):
        rng = random.Random(9)
        members, _, _, _ = gen_rings.make_ring(rng, "ring-0004", size=8, date_range=(200, 240))

        for m in members:
            offset_days = (date.fromisoformat(m.incident_date) - gen_rings.EPOCH).days
            self.assertGreaterEqual(offset_days, 200)
            self.assertLessEqual(offset_days, 240)

    # Every member of a ring must still be a distinct claimant, not a duplicated identity.
    def test_members_have_distinct_identities(self):
        rng = random.Random(2)
        members, _, _, _ = gen_rings.make_ring(rng, "ring-0001", size=8)

        claim_ids = {m.claim_id for m in members}
        names = {m.claimant_name for m in members}
        self.assertEqual(len(claim_ids), 8)
        self.assertGreater(len(names), 1, "a ring of 8 with only one distinct name is suspicious even for a test")


class FuzzPhoneTypoTests(unittest.TestCase):

    # A transposition must never touch the leading digit (index 3, right after "+91") -
    # that digit has to stay in 6-9 for the result to still be a valid Indian mobile number.
    def test_leading_digit_after_country_code_is_never_touched(self):
        rng = random.Random(10)
        phone = "+919876500011"
        for _ in range(50):
            fuzzed = gen_rings.fuzz_phone_typo(rng, phone)
            self.assertEqual(fuzzed[3], phone[3])
            self.assertEqual(len(fuzzed), len(phone))


class FuzzAddressVariantTests(unittest.TestCase):

    # A known city alias must be substitutable - this is the specific gap
    # AddressNormalizer's exact-match tokenizer cannot close on its own.
    def test_can_substitute_a_known_city_alias(self):
        rng = random.Random(11)
        address = "12 Lake View Road, Bengaluru"
        results = {gen_rings.fuzz_address_variant(rng, address) for _ in range(30)}
        self.assertIn("12 Lake View Road, Bangalore", results)

    # An address with no fuzzable city or street name must be returned unchanged, not
    # mangled into something implausible.
    def test_address_with_nothing_fuzzable_is_unchanged(self):
        rng = random.Random(12)
        address = "45 MG Road, Chennai"
        self.assertEqual(gen_rings.fuzz_address_variant(rng, address), address)


class FuzzShopVariantTests(unittest.TestCase):

    # A known suffix spacing variant must be substitutable - the specific gap
    # ShopNormalizer's own docstring names as deliberately unclosed.
    def test_can_substitute_a_known_suffix_spacing_variant(self):
        rng = random.Random(13)
        shop = "SpeedFix Auto Works"
        results = {gen_rings.fuzz_shop_variant(rng, shop) for _ in range(30)}
        self.assertIn("SpeedFix Autoworks", results)

    # A shop name with no fuzzable suffix must be returned unchanged.
    def test_shop_with_nothing_fuzzable_is_unchanged(self):
        rng = random.Random(14)
        shop = "Royal Motors"
        self.assertEqual(gen_rings.fuzz_shop_variant(rng, shop), shop)


class CamouflageTests(unittest.TestCase):

    # Camouflage claims must not be tagged with a ring_id - they're deliberately excluded from ground truth.
    def test_camouflage_claims_have_no_ring_id(self):
        rng = random.Random(3)
        camo = gen_rings.make_camouflage_claims(rng, count=3, shared_phone="+919000000001",
                                                 shared_shop="Test Motors", shared_address=None)

        self.assertEqual(len(camo), 3)
        self.assertTrue(all(c.ring_id is None for c in camo))

    # A camouflage claim must touch at least one of the ring's shared entities, or it wouldn't dilute anything.
    def test_camouflage_claims_touch_a_shared_entity(self):
        rng = random.Random(4)
        shared_phone = "+919000000002"
        shared_shop = "Test Motors"
        camo = gen_rings.make_camouflage_claims(rng, count=5, shared_phone=shared_phone,
                                                 shared_shop=shared_shop, shared_address=None)

        for c in camo:
            touches_something = c.claimant_phone == shared_phone or c.repair_shop_name == shared_shop
            self.assertTrue(touches_something)


class BackgroundCollisionTests(unittest.TestCase):

    # A non-zero collision rate must actually create at least one shared value among background claims.
    def test_collision_rate_creates_shared_values(self):
        rng = random.Random(5)
        claims = [gen_rings.make_background_claim(rng) for _ in range(200)]
        gen_rings.apply_background_collisions(rng, claims, rate=0.1)

        phones = [c.claimant_phone for c in claims]
        self.assertLess(len(set(phones)) + len(set(c.claimant_address for c in claims))
                         + len(set(c.repair_shop_name for c in claims)), 3 * 200,
                         "expected at least one coincidental collision with a 10% rate over 200 claims")

    # A zero collision rate must leave every claim with an independently random phone number.
    def test_zero_rate_creates_no_forced_collisions(self):
        rng = random.Random(6)
        claims = [gen_rings.make_background_claim(rng) for _ in range(50)]
        phones_before = [c.claimant_phone for c in claims]
        gen_rings.apply_background_collisions(rng, claims, rate=0.0)
        phones_after = [c.claimant_phone for c in claims]

        self.assertEqual(phones_before, phones_after)


class ReproducibilityTests(unittest.TestCase):

    # The same seed must produce byte-identical output, since eval numbers need to be reproducible.
    def test_same_seed_produces_identical_claims(self):
        rng1 = random.Random(42)
        rng2 = random.Random(42)

        claim1 = gen_rings.make_background_claim(rng1)
        claim2 = gen_rings.make_background_claim(rng2)

        self.assertEqual(claim1.claimant_name, claim2.claimant_name)
        self.assertEqual(claim1.claimant_phone, claim2.claimant_phone)
        self.assertEqual(claim1.claimant_address, claim2.claimant_address)


if __name__ == "__main__":
    unittest.main()
