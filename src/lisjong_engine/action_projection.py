"""内部LegalActionをsnapshot-localな公開choiceへ射影する。"""

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from lisjong_engine.action_descriptor import (
    ACTION_DESCRIPTOR_TYPES,
    ActionDescriptor,
    AnkanActionDescriptor,
    ChiActionDescriptor,
    DaiminkanActionDescriptor,
    DiscardActionDescriptor,
    KakanActionDescriptor,
    NineTerminalsActionDescriptor,
    PassActionDescriptor,
    PonActionDescriptor,
    RiichiDiscardActionDescriptor,
    RonActionDescriptor,
    TsumoActionDescriptor,
)
from lisjong_engine.legal_action import (
    AnkanLegalAction,
    ChiLegalAction,
    DaiminkanLegalAction,
    DiscardDeclaration,
    DiscardLegalAction,
    KakanLegalAction,
    LegalAction,
    LegalActionSnapshot,
    NineTerminalsLegalAction,
    PassLegalAction,
    PonLegalAction,
    ReactionOrigin,
    RonLegalAction,
    TsumoLegalAction,
    is_legal_action,
)
from lisjong_engine.public_state import PublicTile
from lisjong_engine.round_state import RoundState
from lisjong_engine.seat import Seat
from lisjong_engine.tile import Tile

_SEAT_INDEX = {seat: index for index, seat in enumerate(Seat)}
_DESCRIPTOR_KIND = {
    DiscardActionDescriptor: 0,
    RiichiDiscardActionDescriptor: 1,
    AnkanActionDescriptor: 2,
    KakanActionDescriptor: 3,
    TsumoActionDescriptor: 4,
    NineTerminalsActionDescriptor: 5,
    PassActionDescriptor: 6,
    RonActionDescriptor: 7,
    ChiActionDescriptor: 8,
    PonActionDescriptor: 9,
    DaiminkanActionDescriptor: 10,
}


class ActionProjectionError(RuntimeError):
    """公開action projectionのcontract不整合。"""


class ActionProjection:
    """1つのLegalActionSnapshotに固定された公開optionと内部対応表。"""

    def __init__(
        self,
        *,
        revision: int,
        seat: Seat,
        canonical_actions: Mapping[ActionDescriptor, LegalAction],
    ) -> None:
        if type(revision) is not int:
            raise TypeError("revision must be an int")
        if revision < 0:
            raise ValueError("revision must not be negative")
        if not isinstance(seat, Seat):
            raise TypeError("seat must be a Seat")
        try:
            mapping = dict(canonical_actions)
        except TypeError:
            raise TypeError("canonical_actions must be a mapping") from None
        if not mapping:
            raise ActionProjectionError(
                "a decision must have at least one public option"
            )
        if any(not isinstance(option, ACTION_DESCRIPTOR_TYPES) for option in mapping):
            raise TypeError(
                "canonical_actions must be keyed by ActionDescriptor values"
            )
        if any(not is_legal_action(action) for action in mapping.values()):
            raise TypeError("canonical_actions must contain only legal actions")

        self._revision = revision
        self._seat = seat
        self._canonical_actions = MappingProxyType(mapping)
        self._options = tuple(sorted(mapping, key=_public_action_sort_key))

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def seat(self) -> Seat:
        return self._seat

    @property
    def options(self) -> tuple[ActionDescriptor, ...]:
        return self._options

    def resolve(self, choice: object) -> LegalAction:
        """提示済みdescriptorを同じsnapshotのcanonical internal actionへ戻す。"""
        if not isinstance(choice, ACTION_DESCRIPTOR_TYPES):
            raise TypeError("selector choice must be an ActionDescriptor")
        try:
            return self._canonical_actions[choice]
        except KeyError:
            raise ValueError(
                "selector choice was not among the offered public options"
            ) from None


def project_legal_actions(
    snapshot: LegalActionSnapshot,
    round_state: RoundState,
) -> ActionProjection:
    """snapshotのactionを公開意味でcollapseし、公開情報だけでsortする。"""
    if not isinstance(snapshot, LegalActionSnapshot):
        raise TypeError("snapshot must be a LegalActionSnapshot")
    if not isinstance(round_state, RoundState):
        raise TypeError("round_state must be a RoundState")
    if (
        snapshot.revision != round_state.revision
        or snapshot.phase is not round_state.phase
    ):
        raise ActionProjectionError(
            "legal action snapshot does not match current state"
        )
    if not snapshot.actions:
        raise ActionProjectionError("a decision must have at least one legal action")

    grouped: dict[ActionDescriptor, list[LegalAction]] = {}
    for action in snapshot.actions:
        descriptor = _descriptor_from_legal_action(
            action,
            round_state,
            snapshot.seat,
        )
        grouped.setdefault(descriptor, []).append(action)

    canonical_actions = {
        descriptor: min(actions, key=_internal_action_sort_key)
        for descriptor, actions in grouped.items()
    }
    return ActionProjection(
        revision=snapshot.revision,
        seat=snapshot.seat,
        canonical_actions=canonical_actions,
    )


def _public_tile(tile: Tile) -> PublicTile:
    return PublicTile(tile.tile_type, tile.is_red)


def _tile_by_id(tiles: Iterable[Tile], tile_id: int) -> Tile:
    for tile in tiles:
        if tile.id == tile_id:
            return tile
    raise ActionProjectionError(
        "an action tile is unavailable in the public projection"
    )


def _hand_public_tile(round_state: RoundState, seat: Seat, tile_id: int) -> PublicTile:
    return _public_tile(_tile_by_id(round_state.hand_tiles(seat), tile_id))


def _reaction_target(
    round_state: RoundState,
    origin: ReactionOrigin,
    target_tile_id: int,
) -> tuple[PublicTile, Seat]:
    if origin is ReactionOrigin.DISCARD:
        pending = round_state.pending_discard
        source = round_state.pending_discarder
        target = None if pending is None else pending.tile
    elif origin is ReactionOrigin.KAKAN:
        pending_kakan = round_state.pending_kakan
        source = None if pending_kakan is None else pending_kakan.seat
        target = None if pending_kakan is None else pending_kakan.target_tile
    else:
        pending_ankan = round_state.pending_ankan
        source = None if pending_ankan is None else pending_ankan.seat
        target = None if pending_ankan is None else pending_ankan.target_tile

    if target is None or source is None or target.id != target_tile_id:
        raise ActionProjectionError(
            "reaction target is unavailable in the current state"
        )
    return _public_tile(target), source


def _discard_target(
    round_state: RoundState, target_tile_id: int
) -> tuple[PublicTile, Seat]:
    pending = round_state.pending_discard
    source = round_state.pending_discarder
    if pending is None or source is None or pending.tile.id != target_tile_id:
        raise ActionProjectionError(
            "discard target is unavailable in the current state"
        )
    return _public_tile(pending.tile), source


def _descriptor_from_legal_action(
    action: LegalAction,
    round_state: RoundState,
    viewer_seat: Seat,
) -> ActionDescriptor:
    if isinstance(action, DiscardLegalAction):
        tile = _hand_public_tile(round_state, viewer_seat, action.tile_id)
        is_tsumogiri = round_state.drawn_tile_id == action.tile_id
        if action.declaration is DiscardDeclaration.RIICHI:
            return RiichiDiscardActionDescriptor(tile, is_tsumogiri)
        return DiscardActionDescriptor(tile, is_tsumogiri)

    if isinstance(action, AnkanLegalAction):
        return AnkanActionDescriptor(
            tuple(
                _hand_public_tile(round_state, viewer_seat, tile_id)
                for tile_id in action.tile_ids
            )
        )
    if isinstance(action, KakanLegalAction):
        return KakanActionDescriptor(
            _hand_public_tile(round_state, viewer_seat, action.added_tile_id)
        )
    if isinstance(action, TsumoLegalAction):
        drawn_tile = round_state.drawn_tile
        if drawn_tile is None:
            raise ActionProjectionError(
                "tsumo target is unavailable in the current state"
            )
        return TsumoActionDescriptor(_public_tile(drawn_tile))
    if isinstance(action, NineTerminalsLegalAction):
        return NineTerminalsActionDescriptor()

    if isinstance(action, (PassLegalAction, RonLegalAction)):
        tile, source = _reaction_target(
            round_state,
            action.origin,
            action.target_tile_id,
        )
        if isinstance(action, PassLegalAction):
            return PassActionDescriptor(tile, source)
        return RonActionDescriptor(tile, source)

    if isinstance(action, (ChiLegalAction, PonLegalAction, DaiminkanLegalAction)):
        tile, source = _discard_target(round_state, action.target_tile_id)
        consumed_tiles = tuple(
            _hand_public_tile(round_state, viewer_seat, tile_id)
            for tile_id in action.consumed_tile_ids
        )
        if isinstance(action, ChiLegalAction):
            return ChiActionDescriptor(tile, consumed_tiles, source)
        if isinstance(action, PonLegalAction):
            return PonActionDescriptor(tile, consumed_tiles, source)
        return DaiminkanActionDescriptor(tile, consumed_tiles, source)

    raise ActionProjectionError("unsupported legal action type")


def _tile_key(tile: PublicTile) -> tuple[int, bool]:
    return (tile.tile_type.id, tile.is_red)


def _public_action_sort_key(descriptor: ActionDescriptor) -> tuple:
    kind = _DESCRIPTOR_KIND[type(descriptor)]
    if isinstance(
        descriptor,
        (DiscardActionDescriptor, RiichiDiscardActionDescriptor),
    ):
        return (kind, _tile_key(descriptor.tile), descriptor.is_tsumogiri)
    if isinstance(descriptor, AnkanActionDescriptor):
        return (kind, tuple(_tile_key(tile) for tile in descriptor.tiles))
    if isinstance(descriptor, (KakanActionDescriptor, TsumoActionDescriptor)):
        return (kind, _tile_key(descriptor.tile))
    if isinstance(descriptor, NineTerminalsActionDescriptor):
        return (kind,)
    if isinstance(descriptor, (PassActionDescriptor, RonActionDescriptor)):
        return (kind, _tile_key(descriptor.tile), _SEAT_INDEX[descriptor.from_seat])
    return (
        kind,
        _tile_key(descriptor.tile),
        tuple(_tile_key(tile) for tile in descriptor.consumed_tiles),
        _SEAT_INDEX[descriptor.from_seat],
    )


def _internal_action_sort_key(action: LegalAction) -> tuple[int, ...]:
    if isinstance(action, DiscardLegalAction):
        return (action.tile_id,)
    if isinstance(action, AnkanLegalAction):
        return action.tile_ids
    if isinstance(action, KakanLegalAction):
        return (action.added_tile_id,)
    if isinstance(action, (TsumoLegalAction, NineTerminalsLegalAction)):
        return ()
    if isinstance(action, (PassLegalAction, RonLegalAction)):
        return (action.target_tile_id,)
    if isinstance(action, (ChiLegalAction, PonLegalAction, DaiminkanLegalAction)):
        return (action.target_tile_id, *action.consumed_tile_ids)
    raise ActionProjectionError("unsupported legal action type")
