#!/usr/bin/env python3
"""
Tests for gen_rings.py. Standard-library unittest only, so running the
generator's test suite never needs a pip install either. Run with:

    python3 -m unittest tools.test_gen_rings -v
"""

import random
import unittest

import gen_rings


class MakeRingTests(unittest.TestCase):

    # A ring's members must all share exactly one phone number - that's the fixed part of the fingerprint.
    def test_all_members_share_one_phone(self):
        rng = random.Random(1)
        members, shared_phone, _, _ = gen_rings.make_ring(rng, "ring-0000", size=6)

        self.assertEqual(len(members), 6)
        self.assertTrue(all(m.claimant_phone == shared_phone for m in members))
        self.assertTrue(all(m.ring_id == "ring-0000" for m in members))

    # Every member of a ring must still be a distinct claimant, not a duplicated identity.
    def test_members_have_distinct_identities(self):
        rng = random.Random(2)
        members, _, _, _ = gen_rings.make_ring(rng, "ring-0001", size=8)

        claim_ids = {m.claim_id for m in members}
        names = {m.claimant_name for m in members}
        self.assertEqual(len(claim_ids), 8)
        self.assertGreater(len(names), 1, "a ring of 8 with only one distinct name is suspicious even for a test")


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
