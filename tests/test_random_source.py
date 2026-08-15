import random
import unittest

from lisjong_engine.random_source import RandomSource

_ITEM_COUNT = 50


def shuffled_range(random_source: RandomSource) -> list[int]:
    items = list(range(_ITEM_COUNT))
    random_source.shuffle(items)
    return items


class RandomSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(random.setstate, random.getstate())

    def test_exposes_the_seed_it_was_created_from(self) -> None:
        self.assertEqual(RandomSource(1234).seed, 1234)

    def test_accepts_any_int_seed(self) -> None:
        for seed in (0, -1, 2**64):
            with self.subTest(seed=seed):
                self.assertEqual(RandomSource(seed).seed, seed)

    def test_rejects_non_integer_seed(self) -> None:
        for seed in ("1234", 1234.0, True, None):
            with self.subTest(seed=seed), self.assertRaises(TypeError):
                RandomSource(seed)

    def test_shuffles_in_place_and_keeps_every_item(self) -> None:
        items = list(range(_ITEM_COUNT))

        result = RandomSource(1234).shuffle(items)

        self.assertIsNone(result)
        self.assertEqual(sorted(items), list(range(_ITEM_COUNT)))
        self.assertNotEqual(items, list(range(_ITEM_COUNT)))

    def test_same_seed_produces_the_same_shuffle(self) -> None:
        self.assertEqual(
            shuffled_range(RandomSource(1234)),
            shuffled_range(RandomSource(1234)),
        )

    def test_different_seeds_typically_produce_different_shuffles(self) -> None:
        """seedが実際に使われていることの回帰test。

        50要素のshuffleでは偶然の一致は無視できるが、異なるseedが常に異なる
        結果になることをengineの公開契約として保証するものではない。
        """
        self.assertNotEqual(
            shuffled_range(RandomSource(1234)),
            shuffled_range(RandomSource(5678)),
        )

    def test_consecutive_shuffles_advance_the_same_stream(self) -> None:
        random_source = RandomSource(1234)

        self.assertNotEqual(
            shuffled_range(random_source),
            shuffled_range(random_source),
        )

    def test_instances_with_the_same_seed_advance_independently(self) -> None:
        first = RandomSource(1234)
        second = RandomSource(1234)

        first_result = shuffled_range(first)
        shuffled_range(first)
        second_result = shuffled_range(second)

        self.assertEqual(second_result, first_result)

    def test_does_not_depend_on_global_random_state(self) -> None:
        random.seed(0)
        first_result = shuffled_range(RandomSource(1234))

        random.seed(9999)
        for _ in range(10):
            random.random()
        second_result = shuffled_range(RandomSource(1234))

        self.assertEqual(second_result, first_result)

    def test_does_not_disturb_global_random_state(self) -> None:
        random.seed(0)
        expected = [random.random() for _ in range(5)]

        random.seed(0)
        shuffled_range(RandomSource(1234))
        actual = [random.random() for _ in range(5)]

        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
