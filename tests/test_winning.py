import unittest

from lisjong_engine.meld import Ankan, Chi, Daiminkan, Kakan, Pon
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES, Tile, TileCategory, TileType
from lisjong_engine.winning import (
    SequenceGroup,
    StandardWinningDecomposition,
    StandardWinningInterpretation,
    TripletGroup,
    WaitType,
    WinningShape,
    find_standard_decompositions,
    find_standard_winning_interpretations,
    find_wait_types,
    find_winning_shapes,
    find_winning_tile_types,
    is_winning_shape,
)

_TILE_CATEGORIES = {
    "m": TileCategory.MANZU,
    "p": TileCategory.PINZU,
    "s": TileCategory.SOUZU,
    "z": TileCategory.HONOR,
}


def _tile_type(name: str) -> TileType:
    return TileType(_TILE_CATEGORIES[name[-1]], int(name[:-1]))


def _tiles(*names: str) -> tuple[Tile, ...]:
    copy_counts: dict[TileType, int] = {}
    tiles = []

    for name in names:
        tile_type = _tile_type(name)
        copy_index = copy_counts.get(tile_type, 0)
        tiles.append(STANDARD_TILES[tile_type.id * 4 + copy_index])
        copy_counts[tile_type] = copy_index + 1

    return tuple(tiles)


class FindWinningShapesTest(unittest.TestCase):
    def test_finds_standard_shape_with_sequences_triplet_and_pair(self) -> None:
        tiles = _tiles(
            "1m",
            "2m",
            "3m",
            "1p",
            "2p",
            "3p",
            "1s",
            "2s",
            "3s",
            "7z",
            "7z",
            "7z",
            "5m",
            "5m",
        )

        result = find_winning_shapes(tiles)

        self.assertEqual(result, frozenset({WinningShape.STANDARD}))

    def test_finds_standard_shape_independent_of_tile_order(self) -> None:
        tiles = tuple(
            reversed(
                _tiles(
                    "1m",
                    "2m",
                    "3m",
                    "4m",
                    "5m",
                    "6m",
                    "7m",
                    "8m",
                    "9m",
                    "3p",
                    "3p",
                    "3p",
                    "2z",
                    "2z",
                )
            )
        )

        result = find_winning_shapes(tiles)

        self.assertEqual(result, frozenset({WinningShape.STANDARD}))
        self.assertTrue(any(tile.is_red for tile in tiles))

    def test_finds_standard_shape_with_each_declared_meld_kind(self) -> None:
        concealed_tiles = _tiles(
            "1p",
            "2p",
            "3p",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "2z",
            "2z",
        )
        chi_tiles = _tiles("1m", "2m", "3m")
        triplet_tiles = _tiles("1m", "1m", "1m", "1m")
        pon = Pon(
            triplet_tiles[0],
            triplet_tiles[1:3],
            Seat.EAST,
        )
        melds = (
            Chi(chi_tiles[0], chi_tiles[1:3], Seat.NORTH),
            pon,
            Daiminkan(
                triplet_tiles[0],
                triplet_tiles[1:],
                Seat.SOUTH,
            ),
            Ankan(triplet_tiles),
            Kakan(pon, triplet_tiles[3]),
        )

        for meld in melds:
            with self.subTest(meld_type=type(meld).__name__):
                result = find_winning_shapes(concealed_tiles, (meld,))

                self.assertEqual(
                    result,
                    frozenset({WinningShape.STANDARD}),
                )

    def test_finds_standard_shape_with_four_declared_melds(self) -> None:
        first_chi_tiles = _tiles("1m", "2m", "3m")
        second_chi_tiles = _tiles("4m", "5m", "6m")
        pon_tiles = _tiles("1p", "1p", "1p")
        ankan_tiles = _tiles("1s", "1s", "1s", "1s")
        melds = (
            Chi(
                first_chi_tiles[0],
                first_chi_tiles[1:],
                Seat.NORTH,
            ),
            Chi(
                second_chi_tiles[0],
                second_chi_tiles[1:],
                Seat.WEST,
            ),
            Pon(pon_tiles[0], pon_tiles[1:], Seat.SOUTH),
            Ankan(ankan_tiles),
        )

        result = find_winning_shapes(_tiles("2z", "2z"), melds)

        self.assertEqual(result, frozenset({WinningShape.STANDARD}))

    def test_rejects_tiles_that_cannot_form_a_pair(self) -> None:
        tiles = _tiles(
            "1m",
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
            "7m",
            "8m",
            "9m",
            "1p",
            "2p",
            "3p",
            "4s",
            "5s",
        )

        self.assertEqual(find_winning_shapes(tiles), frozenset())

    def test_does_not_treat_honor_tiles_as_a_sequence(self) -> None:
        tiles = _tiles(
            "1m",
            "2m",
            "3m",
            "1p",
            "2p",
            "3p",
            "1s",
            "2s",
            "3s",
            "1z",
            "2z",
            "3z",
            "5m",
            "5m",
        )

        self.assertEqual(find_winning_shapes(tiles), frozenset())

    def test_finds_seven_distinct_pairs(self) -> None:
        tiles = _tiles(
            "1m",
            "1m",
            "2m",
            "2m",
            "3p",
            "3p",
            "4p",
            "4p",
            "5s",
            "5s",
            "6s",
            "6s",
            "7z",
            "7z",
        )

        result = find_winning_shapes(tiles)

        self.assertEqual(result, frozenset({WinningShape.SEVEN_PAIRS}))

    def test_does_not_count_four_identical_tiles_as_two_pairs(self) -> None:
        tiles = _tiles(
            "1m",
            "1m",
            "1m",
            "1m",
            "2m",
            "2m",
            "3p",
            "3p",
            "4p",
            "4p",
            "5s",
            "5s",
            "6z",
            "6z",
        )

        result = find_winning_shapes(tiles)

        self.assertNotIn(WinningShape.SEVEN_PAIRS, result)

    def test_returns_both_standard_and_seven_pairs_interpretations(self) -> None:
        tiles = _tiles(
            "1m",
            "1m",
            "2m",
            "2m",
            "3m",
            "3m",
            "4p",
            "4p",
            "5p",
            "5p",
            "6p",
            "6p",
            "7s",
            "7s",
        )

        result = find_winning_shapes(tiles)

        self.assertEqual(
            result,
            frozenset(
                {
                    WinningShape.STANDARD,
                    WinningShape.SEVEN_PAIRS,
                }
            ),
        )

    def test_finds_thirteen_orphans_with_one_duplicate(self) -> None:
        tiles = _tiles(
            "1m",
            "1m",
            "9m",
            "1p",
            "9p",
            "1s",
            "9s",
            "1z",
            "2z",
            "3z",
            "4z",
            "5z",
            "6z",
            "7z",
        )

        result = find_winning_shapes(tiles)

        self.assertEqual(
            result,
            frozenset({WinningShape.THIRTEEN_ORPHANS}),
        )

    def test_rejects_thirteen_orphans_missing_a_required_tile_type(self) -> None:
        tiles = _tiles(
            "1m",
            "1m",
            "9m",
            "1p",
            "1p",
            "9p",
            "1s",
            "1z",
            "2z",
            "3z",
            "4z",
            "5z",
            "6z",
            "7z",
        )

        result = find_winning_shapes(tiles)

        self.assertNotIn(WinningShape.THIRTEEN_ORPHANS, result)

    def test_rejects_incomplete_and_structurally_oversized_hands(self) -> None:
        standard_tiles = _tiles(
            "1m",
            "2m",
            "3m",
            "1p",
            "2p",
            "3p",
            "1s",
            "2s",
            "3s",
            "7z",
            "7z",
            "7z",
            "5m",
            "5m",
        )
        meld_tiles = _tiles("7p", "8p", "9p")
        chi = Chi(meld_tiles[0], meld_tiles[1:], Seat.NORTH)

        self.assertEqual(
            find_winning_shapes(standard_tiles[:-1]),
            frozenset(),
        )
        self.assertEqual(
            find_winning_shapes(standard_tiles, (chi,)),
            frozenset(),
        )


class WinningGroupTest(unittest.TestCase):
    def test_sequence_group_exposes_three_consecutive_tile_types(self) -> None:
        group = SequenceGroup(_tile_type("4p"))

        self.assertEqual(
            group.tile_types,
            (
                _tile_type("4p"),
                _tile_type("5p"),
                _tile_type("6p"),
            ),
        )

    def test_sequence_group_rejects_invalid_start_tile_type(self) -> None:
        invalid_tile_types = (
            _tile_type("8m"),
            _tile_type("1z"),
        )

        for start_tile_type in invalid_tile_types:
            with (
                self.subTest(start_tile_type=start_tile_type),
                self.assertRaises(ValueError),
            ):
                SequenceGroup(start_tile_type)

        with self.assertRaises(TypeError):
            SequenceGroup("1m")

    def test_triplet_group_exposes_three_equal_tile_types(self) -> None:
        group = TripletGroup(_tile_type("7z"))

        self.assertEqual(
            group.tile_types,
            (
                _tile_type("7z"),
                _tile_type("7z"),
                _tile_type("7z"),
            ),
        )

    def test_triplet_group_rejects_non_tile_type(self) -> None:
        with self.assertRaises(TypeError):
            TripletGroup("7z")


class StandardWinningDecompositionTest(unittest.TestCase):
    def test_copies_group_and_meld_sequences(self) -> None:
        groups = [
            SequenceGroup(_tile_type("1m")),
            SequenceGroup(_tile_type("4p")),
            TripletGroup(_tile_type("7z")),
        ]
        pon_tiles = _tiles("1s", "1s", "1s")
        melds = [Pon(pon_tiles[0], pon_tiles[1:], Seat.SOUTH)]

        decomposition = StandardWinningDecomposition(
            pair=_tile_type("2z"),
            concealed_groups=groups,
            declared_melds=melds,
        )
        groups.clear()
        melds.clear()

        self.assertEqual(len(decomposition.concealed_groups), 3)
        self.assertEqual(len(decomposition.declared_melds), 1)

    def test_requires_exactly_four_total_groups(self) -> None:
        with self.assertRaises(ValueError):
            StandardWinningDecomposition(
                pair=_tile_type("2z"),
                concealed_groups=(
                    SequenceGroup(_tile_type("1m")),
                    SequenceGroup(_tile_type("4p")),
                    TripletGroup(_tile_type("7z")),
                ),
            )

    def test_rejects_invalid_pair_group_and_meld_types(self) -> None:
        groups = (
            SequenceGroup(_tile_type("1m")),
            SequenceGroup(_tile_type("4p")),
            TripletGroup(_tile_type("7z")),
            TripletGroup(_tile_type("1s")),
        )

        with self.assertRaises(TypeError):
            StandardWinningDecomposition(
                pair="2z",
                concealed_groups=groups,
            )
        with self.assertRaises(TypeError):
            StandardWinningDecomposition(
                pair=_tile_type("2z"),
                concealed_groups=(*groups[:3], "1s"),
            )
        with self.assertRaises(TypeError):
            StandardWinningDecomposition(
                pair=_tile_type("2z"),
                concealed_groups=groups[:3],
                declared_melds=(STANDARD_TILES[0],),
            )


class FindStandardDecompositionsTest(unittest.TestCase):
    def test_returns_pair_groups_and_declared_melds(self) -> None:
        concealed_tiles = _tiles(
            "1p",
            "2p",
            "3p",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "2z",
            "2z",
        )
        pon_tiles = _tiles("1m", "1m", "1m")
        pon = Pon(pon_tiles[0], pon_tiles[1:], Seat.SOUTH)

        result = find_standard_decompositions(concealed_tiles, (pon,))

        self.assertEqual(
            result,
            frozenset(
                {
                    StandardWinningDecomposition(
                        pair=_tile_type("2z"),
                        concealed_groups=(
                            SequenceGroup(_tile_type("1p")),
                            SequenceGroup(_tile_type("4p")),
                            SequenceGroup(_tile_type("7s")),
                        ),
                        declared_melds=(pon,),
                    )
                }
            ),
        )

    def test_returns_every_valid_standard_decomposition(self) -> None:
        tiles = _tiles(
            "1m",
            "1m",
            "1m",
            "2m",
            "2m",
            "2m",
            "3m",
            "3m",
            "3m",
            "4m",
            "4m",
            "4m",
            "5m",
            "5m",
        )

        result = find_standard_decompositions(tiles)

        self.assertEqual(
            result,
            frozenset(
                {
                    StandardWinningDecomposition(
                        pair=_tile_type("5m"),
                        concealed_groups=(
                            TripletGroup(_tile_type("1m")),
                            TripletGroup(_tile_type("2m")),
                            TripletGroup(_tile_type("3m")),
                            TripletGroup(_tile_type("4m")),
                        ),
                    ),
                    StandardWinningDecomposition(
                        pair=_tile_type("5m"),
                        concealed_groups=(
                            SequenceGroup(_tile_type("1m")),
                            SequenceGroup(_tile_type("1m")),
                            SequenceGroup(_tile_type("1m")),
                            TripletGroup(_tile_type("4m")),
                        ),
                    ),
                    StandardWinningDecomposition(
                        pair=_tile_type("5m"),
                        concealed_groups=(
                            TripletGroup(_tile_type("1m")),
                            SequenceGroup(_tile_type("2m")),
                            SequenceGroup(_tile_type("2m")),
                            SequenceGroup(_tile_type("2m")),
                        ),
                    ),
                    StandardWinningDecomposition(
                        pair=_tile_type("2m"),
                        concealed_groups=(
                            TripletGroup(_tile_type("1m")),
                            SequenceGroup(_tile_type("2m")),
                            SequenceGroup(_tile_type("3m")),
                            SequenceGroup(_tile_type("3m")),
                        ),
                    ),
                }
            ),
        )

    def test_returns_pair_only_with_four_declared_melds(self) -> None:
        melds = []
        for name, source_seat in (
            ("1m", Seat.SOUTH),
            ("2p", Seat.WEST),
            ("3s", Seat.NORTH),
            ("4z", Seat.SOUTH),
        ):
            meld_tiles = _tiles(name, name, name)
            melds.append(
                Pon(
                    meld_tiles[0],
                    meld_tiles[1:],
                    source_seat,
                )
            )

        result = find_standard_decompositions(
            _tiles("7z", "7z"),
            melds,
        )

        self.assertEqual(
            result,
            frozenset(
                {
                    StandardWinningDecomposition(
                        pair=_tile_type("7z"),
                        concealed_groups=(),
                        declared_melds=tuple(melds),
                    )
                }
            ),
        )

    def test_is_independent_of_concealed_tile_order(self) -> None:
        tiles = _tiles(
            "1m",
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
            "7m",
            "8m",
            "9m",
            "1p",
            "1p",
            "1p",
            "2z",
            "2z",
        )

        self.assertEqual(
            find_standard_decompositions(tiles),
            find_standard_decompositions(reversed(tiles)),
        )

    def test_returns_empty_set_for_non_standard_shape(self) -> None:
        seven_pairs = _tiles(
            "1m",
            "1m",
            "2m",
            "2m",
            "3p",
            "3p",
            "4p",
            "4p",
            "5s",
            "5s",
            "6s",
            "6s",
            "7z",
            "7z",
        )

        self.assertEqual(
            find_standard_decompositions(seven_pairs),
            frozenset(),
        )

    def test_applies_the_same_input_validation_as_shape_detection(self) -> None:
        tile = STANDARD_TILES[0]

        with self.assertRaises(TypeError):
            find_standard_decompositions(None)
        with self.assertRaises(ValueError):
            find_standard_decompositions((tile, tile))


class FindStandardWinningInterpretationsTest(unittest.TestCase):
    def test_identifies_ryanmen_wait_and_completed_sequence(self) -> None:
        tiles = _tiles(
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "2z",
            "1m",
        )

        result = find_standard_winning_interpretations(tiles, tiles[-1])

        self.assertEqual(len(result), 1)
        interpretation = next(iter(result))
        self.assertIsInstance(
            interpretation,
            StandardWinningInterpretation,
        )
        self.assertEqual(
            interpretation.completed_group,
            SequenceGroup(_tile_type("1m")),
        )
        self.assertIs(interpretation.wait_type, WaitType.RYANMEN)

    def test_identifies_kanchan_wait(self) -> None:
        tiles = _tiles(
            "2m",
            "4m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "2z",
            "3m",
        )

        result = find_wait_types(tiles, tiles[-1])

        self.assertEqual(result, frozenset({WaitType.KANCHAN}))

    def test_identifies_penchan_wait_at_both_suit_edges(self) -> None:
        cases = (
            (
                ("1m", "2m"),
                "3m",
                ("4p", "5p", "6p"),
            ),
            (
                ("8m", "9m"),
                "7m",
                ("4p", "5p", "6p"),
            ),
        )

        for partial_sequence, winning_name, second_group in cases:
            with self.subTest(winning_name=winning_name):
                tiles = _tiles(
                    *partial_sequence,
                    *second_group,
                    "7s",
                    "8s",
                    "9s",
                    "1z",
                    "1z",
                    "1z",
                    "2z",
                    "2z",
                    winning_name,
                )

                result = find_wait_types(tiles, tiles[-1])

                self.assertEqual(result, frozenset({WaitType.PENCHAN}))

    def test_identifies_shanpon_wait_and_completed_triplet(self) -> None:
        tiles = _tiles(
            "1m",
            "1m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "3z",
            "3z",
            "3z",
            "2z",
            "2z",
            "1m",
        )

        result = find_standard_winning_interpretations(tiles, tiles[-1])

        self.assertEqual(len(result), 1)
        interpretation = next(iter(result))
        self.assertEqual(
            interpretation.completed_group,
            TripletGroup(_tile_type("1m")),
        )
        self.assertIs(interpretation.wait_type, WaitType.SHANPON)

    def test_identifies_tanki_wait_and_completed_pair(self) -> None:
        tiles = _tiles(
            "1m",
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "2z",
        )

        result = find_standard_winning_interpretations(tiles, tiles[-1])

        self.assertEqual(len(result), 1)
        interpretation = next(iter(result))
        self.assertIsNone(interpretation.completed_group)
        self.assertIs(interpretation.wait_type, WaitType.TANKI)

    def test_preserves_every_possible_wait_interpretation(self) -> None:
        tiles = _tiles(
            "1m",
            "1m",
            "1m",
            "2m",
            "2m",
            "3m",
            "3m",
            "3m",
            "4m",
            "4m",
            "4m",
            "5m",
            "5m",
            "2m",
        )

        result = find_wait_types(tiles, tiles[-1])

        self.assertEqual(
            result,
            frozenset(
                {
                    WaitType.RYANMEN,
                    WaitType.KANCHAN,
                    WaitType.SHANPON,
                    WaitType.TANKI,
                }
            ),
        )

    def test_supports_declared_melds(self) -> None:
        concealed_tiles = _tiles(
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "2z",
            "2z",
            "1m",
        )
        pon_tiles = _tiles("1z", "1z", "1z")
        pon = Pon(pon_tiles[0], pon_tiles[1:], Seat.SOUTH)

        result = find_wait_types(
            concealed_tiles,
            concealed_tiles[-1],
            (pon,),
        )

        self.assertEqual(result, frozenset({WaitType.RYANMEN}))

    def test_returns_empty_set_when_tiles_are_not_a_winning_shape(self) -> None:
        tiles = _tiles(
            "1m",
            "2m",
            "4m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "3m",
        )

        result = find_wait_types(tiles, tiles[-1])

        self.assertEqual(result, frozenset())

    def test_rejects_winning_tile_that_is_not_concealed(self) -> None:
        tiles = _tiles(
            "1m",
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "2z",
        )

        with self.assertRaises(ValueError):
            find_wait_types(tiles, STANDARD_TILES[132])
        with self.assertRaises(TypeError):
            find_wait_types(tiles, "2z")


class FindSpecialWaitTypesTest(unittest.TestCase):
    def test_identifies_seven_pairs_tanki_wait(self) -> None:
        tiles = _tiles(
            "1m",
            "1m",
            "2m",
            "2m",
            "3p",
            "3p",
            "4p",
            "4p",
            "5s",
            "5s",
            "6s",
            "6s",
            "7z",
            "7z",
        )

        result = find_wait_types(tiles, tiles[-1])

        self.assertEqual(result, frozenset({WaitType.TANKI}))

    def test_distinguishes_thirteen_sided_and_single_kokushi_waits(
        self,
    ) -> None:
        thirteen_sided_tiles = _tiles(
            "1m",
            "9m",
            "1p",
            "9p",
            "1s",
            "9s",
            "1z",
            "2z",
            "3z",
            "4z",
            "5z",
            "6z",
            "7z",
            "1m",
        )
        single_wait_tiles = _tiles(
            "1m",
            "1m",
            "1p",
            "9p",
            "1s",
            "9s",
            "1z",
            "2z",
            "3z",
            "4z",
            "5z",
            "6z",
            "7z",
            "9m",
        )

        self.assertEqual(
            find_wait_types(
                thirteen_sided_tiles,
                thirteen_sided_tiles[-1],
            ),
            frozenset({WaitType.KOKUSHI_THIRTEEN_SIDED}),
        )
        self.assertEqual(
            find_wait_types(single_wait_tiles, single_wait_tiles[-1]),
            frozenset({WaitType.KOKUSHI_SINGLE}),
        )


class FindWinningTileTypesTest(unittest.TestCase):
    def test_finds_both_ends_of_ryanmen_wait(self) -> None:
        tiles = _tiles(
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
            "2z",
        )

        result = find_winning_tile_types(tiles)

        self.assertEqual(
            result,
            frozenset({_tile_type("1m"), _tile_type("4m")}),
        )

    def test_finds_both_tiles_of_shanpon_wait(self) -> None:
        tiles = _tiles(
            "1m",
            "1m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "3z",
            "3z",
            "3z",
            "2z",
            "2z",
        )

        result = find_winning_tile_types(tiles)

        self.assertEqual(
            result,
            frozenset({_tile_type("1m"), _tile_type("2z")}),
        )

    def test_finds_seven_pairs_and_thirteen_orphans_waits(self) -> None:
        seven_pairs_tiles = _tiles(
            "1m",
            "1m",
            "2m",
            "2m",
            "3p",
            "3p",
            "4p",
            "4p",
            "5s",
            "5s",
            "6s",
            "6s",
            "7z",
        )
        kokushi_tiles = _tiles(
            "1m",
            "9m",
            "1p",
            "9p",
            "1s",
            "9s",
            "1z",
            "2z",
            "3z",
            "4z",
            "5z",
            "6z",
            "7z",
        )

        self.assertEqual(
            find_winning_tile_types(seven_pairs_tiles),
            frozenset({_tile_type("7z")}),
        )
        self.assertEqual(
            find_winning_tile_types(kokushi_tiles),
            frozenset(
                _tile_type(name)
                for name in (
                    "1m",
                    "9m",
                    "1p",
                    "9p",
                    "1s",
                    "9s",
                    "1z",
                    "2z",
                    "3z",
                    "4z",
                    "5z",
                    "6z",
                    "7z",
                )
            ),
        )

    def test_supports_declared_melds(self) -> None:
        concealed_tiles = _tiles(
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "2z",
            "2z",
        )
        pon_tiles = _tiles("1z", "1z", "1z")
        pon = Pon(pon_tiles[0], pon_tiles[1:], Seat.SOUTH)

        result = find_winning_tile_types(concealed_tiles, (pon,))

        self.assertEqual(
            result,
            frozenset({_tile_type("1m"), _tile_type("4m")}),
        )

    def test_excludes_impossible_fifth_copy_wait(self) -> None:
        tiles = _tiles(
            "1m",
            "1m",
            "1m",
            "1m",
            "2p",
            "3p",
            "4p",
            "5s",
            "6s",
            "7s",
            "7p",
            "8p",
            "9p",
        )

        result = find_winning_tile_types(tiles)

        self.assertEqual(result, frozenset())

    def test_returns_empty_set_for_non_thirteen_tile_equivalent(self) -> None:
        tiles = _tiles(
            "2m",
            "3m",
            "4p",
            "5p",
            "6p",
            "7s",
            "8s",
            "9s",
            "1z",
            "1z",
            "1z",
            "2z",
        )

        result = find_winning_tile_types(tiles)

        self.assertEqual(result, frozenset())


class IsWinningShapeTest(unittest.TestCase):
    def test_returns_boolean_result(self) -> None:
        complete_tiles = _tiles(
            "1m",
            "2m",
            "3m",
            "4m",
            "5m",
            "6m",
            "7m",
            "8m",
            "9m",
            "1p",
            "1p",
            "1p",
            "2z",
            "2z",
        )

        self.assertTrue(is_winning_shape(complete_tiles))
        self.assertFalse(is_winning_shape(complete_tiles[:-1]))


class WinningShapeValidationTest(unittest.TestCase):
    def test_rejects_non_iterable_concealed_tiles(self) -> None:
        with self.assertRaises(TypeError):
            find_winning_shapes(None)

    def test_rejects_non_tile_in_concealed_tiles(self) -> None:
        with self.assertRaises(TypeError):
            find_winning_shapes((STANDARD_TILES[0], "2m"))

    def test_rejects_non_iterable_declared_melds(self) -> None:
        with self.assertRaises(TypeError):
            find_winning_shapes((), None)

    def test_rejects_non_meld_in_declared_melds(self) -> None:
        with self.assertRaises(TypeError):
            find_winning_shapes((), (STANDARD_TILES[0],))

    def test_rejects_duplicate_physical_tile_in_concealed_tiles(self) -> None:
        tile = STANDARD_TILES[0]

        with self.assertRaises(ValueError):
            find_winning_shapes((tile, tile))

    def test_rejects_duplicate_physical_tile_across_hand_and_meld(self) -> None:
        meld_tiles = _tiles("1m", "1m", "1m")
        pon = Pon(meld_tiles[0], meld_tiles[1:], Seat.SOUTH)

        with self.assertRaises(ValueError):
            find_winning_shapes((meld_tiles[0],), (pon,))


if __name__ == "__main__":
    unittest.main()
