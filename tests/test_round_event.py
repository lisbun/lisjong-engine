import unittest
from dataclasses import FrozenInstanceError, fields

from lisjong_engine.round_event import (
    DrawSource,
    RoundEndedEvent,
    RoundEvent,
    RoundEventSnapshot,
    RoundStartedEvent,
    TileDiscardedEvent,
    TileDrawnEvent,
    TilesDealtEvent,
)
from lisjong_engine.round_result import AbortiveDrawReason, AbortiveDrawResult
from lisjong_engine.seat import Seat
from lisjong_engine.tile import STANDARD_TILES
from lisjong_engine.wind import Wind


class RoundEventValueTest(unittest.TestCase):
    def test_events_are_frozen_domain_values(self) -> None:
        event = TileDrawnEvent(Seat.EAST, STANDARD_TILES[0], DrawSource.LIVE_WALL)

        self.assertIsInstance(event, RoundEvent)
        with self.assertRaises(FrozenInstanceError):
            event.seat = Seat.SOUTH

    def test_round_started_event_records_the_round_facts(self) -> None:
        event = RoundStartedEvent(Seat.SOUTH, Wind.EAST)

        self.assertIs(event.dealer_seat, Seat.SOUTH)
        self.assertIs(event.prevailing_wind, Wind.EAST)

    def test_tiles_dealt_event_normalizes_tiles_into_a_tuple(self) -> None:
        tiles = list(STANDARD_TILES[:13])

        event = TilesDealtEvent(Seat.EAST, tiles)
        tiles.append(STANDARD_TILES[13])

        self.assertIsInstance(event.tiles, tuple)
        self.assertEqual(event.tiles, STANDARD_TILES[:13])

    def test_tile_discarded_event_records_tsumogiri(self) -> None:
        event = TileDiscardedEvent(Seat.WEST, STANDARD_TILES[5], True)

        self.assertIs(event.seat, Seat.WEST)
        self.assertEqual(event.tile, STANDARD_TILES[5])
        self.assertTrue(event.is_tsumogiri)

    def test_draw_source_is_limited_to_the_implemented_sources(self) -> None:
        self.assertEqual(
            tuple((source.name, source.value) for source in DrawSource),
            (("LIVE_WALL", "live_wall"), ("RINSHAN", "rinshan")),
        )

    def test_rejects_invalid_event_fields(self) -> None:
        for factory in (
            lambda: RoundStartedEvent("east", Wind.EAST),
            lambda: RoundStartedEvent(Seat.EAST, "east"),
            lambda: TilesDealtEvent("east", ()),
            lambda: TilesDealtEvent(Seat.EAST, ("1m",)),
            lambda: TileDrawnEvent(Seat.EAST, "1m", DrawSource.LIVE_WALL),
            lambda: TileDrawnEvent(Seat.EAST, STANDARD_TILES[0], "live_wall"),
            lambda: TileDiscardedEvent(Seat.EAST, STANDARD_TILES[0], 1),
        ):
            with self.subTest(factory=factory):
                with self.assertRaises(TypeError):
                    factory()

    def test_round_ended_event_carries_exactly_one_terminal_result(self) -> None:
        result = AbortiveDrawResult(AbortiveDrawReason.FOUR_WINDS)
        event = RoundEndedEvent(result)

        self.assertIs(event.result, result)
        self.assertIsInstance(event, RoundEvent)
        self.assertEqual(tuple(field.name for field in fields(event)), ("result",))
        self.assertEqual(tuple(RoundEventSnapshot((event,))), (event,))
        with self.assertRaises(FrozenInstanceError):
            event.result = AbortiveDrawResult(AbortiveDrawReason.FOUR_KANS)

    def test_round_ended_event_rejects_non_result(self) -> None:
        with self.assertRaisesRegex(TypeError, "RoundResult"):
            RoundEndedEvent("finished")


class RoundEventSnapshotTest(unittest.TestCase):
    def test_is_empty_by_default(self) -> None:
        snapshot = RoundEventSnapshot()

        self.assertEqual(snapshot.events, ())
        self.assertEqual(len(snapshot), 0)

    def test_supports_iteration_indexing_and_length(self) -> None:
        events = (
            RoundStartedEvent(Seat.EAST, Wind.EAST),
            TileDrawnEvent(Seat.EAST, STANDARD_TILES[0], DrawSource.LIVE_WALL),
        )

        snapshot = RoundEventSnapshot(events)

        self.assertEqual(tuple(snapshot), events)
        self.assertIs(snapshot[0], events[0])
        self.assertEqual(len(snapshot), 2)

    def test_appended_returns_a_new_snapshot_without_mutating_the_original(
        self,
    ) -> None:
        first_event = RoundStartedEvent(Seat.EAST, Wind.EAST)
        second_event = TileDrawnEvent(
            Seat.EAST, STANDARD_TILES[0], DrawSource.LIVE_WALL
        )
        snapshot = RoundEventSnapshot((first_event,))

        extended = snapshot.appended((second_event,))

        self.assertEqual(snapshot.events, (first_event,))
        self.assertEqual(extended.events, (first_event, second_event))

    def test_rejects_values_that_are_not_events(self) -> None:
        with self.assertRaises(TypeError):
            RoundEventSnapshot(("started",))
        with self.assertRaises(TypeError):
            RoundEventSnapshot().appended(("drawn",))


if __name__ == "__main__":
    unittest.main()
