import unittest

from lisjong_engine.random_source import RandomSource
from lisjong_engine.round_allocation import (
    RoundRandomProvenance,
    create_round_random_provenance,
    create_round_wall,
    derive_round_seed,
)
from lisjong_engine.wall import Wall, create_shuffled_wall

# `derive_round_seed()`が独自に導出した値ではなく、productionと独立に
# hashlib.sha256で計算した既知の期待値。algorithmの回帰を検出するために
# production functionを呼ばずに固定する。
_KNOWN_MATCH_SEED = 12345
_KNOWN_ROUND_ORDINAL = 1
_KNOWN_ROUND_SEED = (
    94989027591253833448260429421886588848012180282710119613339357967353645062342
)


class DeriveRoundSeedTest(unittest.TestCase):
    def test_same_match_seed_and_ordinal_produce_the_same_round_seed(self) -> None:
        first = derive_round_seed(7, 3)
        second = derive_round_seed(7, 3)

        self.assertEqual(first, second)

    def test_different_ordinal_produces_a_different_round_seed(self) -> None:
        self.assertNotEqual(
            derive_round_seed(7, 1),
            derive_round_seed(7, 2),
        )

    def test_different_match_seed_produces_a_different_round_seed(self) -> None:
        self.assertNotEqual(
            derive_round_seed(7, 1),
            derive_round_seed(8, 1),
        )

    def test_rejects_non_positive_round_ordinal(self) -> None:
        with self.assertRaises(ValueError):
            derive_round_seed(1, 0)
        with self.assertRaises(ValueError):
            derive_round_seed(1, -1)

    def test_rejects_invalid_match_seed_types(self) -> None:
        for invalid in (True, False, 1.0, "1", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    derive_round_seed(invalid, 1)

    def test_rejects_invalid_round_ordinal_types(self) -> None:
        for invalid in (True, False, 1.0, "1", None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    derive_round_seed(1, invalid)

    def test_fixes_the_sha256_derivation_contract_for_a_known_input(self) -> None:
        self.assertEqual(
            derive_round_seed(_KNOWN_MATCH_SEED, _KNOWN_ROUND_ORDINAL),
            _KNOWN_ROUND_SEED,
        )


class RoundRandomProvenanceTest(unittest.TestCase):
    def test_holds_match_seed_ordinal_and_derived_round_seed(self) -> None:
        provenance = create_round_random_provenance(42, 5)

        self.assertEqual(provenance.match_seed, 42)
        self.assertEqual(provenance.round_ordinal, 5)
        self.assertEqual(provenance.round_seed, derive_round_seed(42, 5))

    def test_rejects_non_positive_round_ordinal(self) -> None:
        with self.assertRaises(ValueError):
            RoundRandomProvenance(
                match_seed=1,
                round_ordinal=0,
                round_seed=1,
            )

    def test_rejects_invalid_field_types(self) -> None:
        with self.assertRaises(TypeError):
            RoundRandomProvenance(
                match_seed=True,
                round_ordinal=1,
                round_seed=1,
            )
        with self.assertRaises(TypeError):
            RoundRandomProvenance(
                match_seed=1,
                round_ordinal=1.0,
                round_seed=1,
            )
        with self.assertRaises(TypeError):
            RoundRandomProvenance(
                match_seed=1,
                round_ordinal=1,
                round_seed="1",
            )


class CreateRoundWallTest(unittest.TestCase):
    def test_same_provenance_produces_the_same_wall(self) -> None:
        provenance = create_round_random_provenance(1_000, 1)

        first = create_round_wall(provenance)
        second = create_round_wall(provenance)

        self.assertEqual(first.remaining_tiles, second.remaining_tiles)
        self.assertEqual(first.dead_wall_tiles, second.dead_wall_tiles)

    def test_matches_directly_constructed_random_source_wall(self) -> None:
        provenance = create_round_random_provenance(1_000, 1)

        wall = create_round_wall(provenance)
        expected = create_shuffled_wall(RandomSource(provenance.round_seed))

        self.assertEqual(wall.remaining_tiles, expected.remaining_tiles)
        self.assertEqual(wall.dead_wall_tiles, expected.dead_wall_tiles)

    def test_different_round_ordinal_produces_a_different_wall(self) -> None:
        first = create_round_wall(create_round_random_provenance(1_000, 1))
        second = create_round_wall(create_round_random_provenance(1_000, 2))

        self.assertNotEqual(first.remaining_tiles, second.remaining_tiles)

    def test_rejects_non_provenance_input(self) -> None:
        with self.assertRaises(TypeError):
            create_round_wall("not-a-provenance")

    def test_returns_a_wall(self) -> None:
        provenance = create_round_random_provenance(1_000, 1)

        self.assertIsInstance(create_round_wall(provenance), Wall)


if __name__ == "__main__":
    unittest.main()
