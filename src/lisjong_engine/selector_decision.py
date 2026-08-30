"""成功したengine transactionへ投入されたselector decisionの公開contract。

各`SelectorDecision`の`observation`は`seat`に対してplayer-safeであり、
`legal_actions`と`selected_action`は同じsnapshotから得た公開
`ActionDescriptor`だけを保持する。internal `LegalAction`、physical tile ID、
state、wall、random provenance、reaction resolution outcomeは含めない。

## bundleはsingle-player safeではない

reaction transactionの`SelectorDecisionCommit`は複数席のseat-relative
`SeatObservation`を1つに束ねる。各decisionはその席に対してplayer-safeだが、
bundle全体は複数playerのprivate informationを含み得るため、単一playerへ
渡してよいglobal-public recordとして扱ってはならない。

`selected_action`はselectorがtransaction inputとして選んだchoiceであり、
reaction priority適用後の盤面上のoutcomeではない。成立結果は既存のstate
transition / `RoundProgressFact`側の責務である。
"""

from dataclasses import dataclass

from lisjong_engine.action_descriptor import (
    ACTION_DESCRIPTOR_TYPES,
    ActionDescriptor,
)
from lisjong_engine.observation import SeatObservation
from lisjong_engine.seat import Seat


@dataclass(frozen=True, kw_only=True)
class SelectorDecision:
    """1席のsnapshot-localなselector inputとselected public choice。"""

    seat: Seat
    revision: int
    observation: SeatObservation
    legal_actions: tuple[ActionDescriptor, ...]
    selected_action: ActionDescriptor

    def __post_init__(self) -> None:
        if not isinstance(self.seat, Seat):
            raise TypeError("seat must be a Seat")
        if type(self.revision) is not int:
            raise TypeError("revision must be an int")
        if self.revision < 0:
            raise ValueError("revision must not be negative")
        if not isinstance(self.observation, SeatObservation):
            raise TypeError("observation must be a SeatObservation")
        if self.observation.viewer_seat is not self.seat:
            raise ValueError("observation viewer_seat must match seat")

        try:
            legal_actions = tuple(self.legal_actions)
        except TypeError:
            raise TypeError("legal_actions must be an iterable") from None
        if not legal_actions:
            raise ValueError("legal_actions must not be empty")
        if any(
            not isinstance(action, ACTION_DESCRIPTOR_TYPES) for action in legal_actions
        ):
            raise TypeError("legal_actions must contain only ActionDescriptor values")
        if not isinstance(self.selected_action, ACTION_DESCRIPTOR_TYPES):
            raise TypeError("selected_action must be an ActionDescriptor")
        if self.selected_action not in legal_actions:
            raise ValueError("selected_action must be among legal_actions")

        object.__setattr__(self, "legal_actions", legal_actions)


@dataclass(frozen=True)
class SelectorDecisionCommit:
    """1つのsuccessful engine transactionへ投入されたdecision batch。

    複数decisionを持つreaction batchはsingle-player safeではない。module
    docstringのinformation boundaryに従い、各seat向けprojectionとして扱う。
    """

    decisions: tuple[SelectorDecision, ...]

    def __post_init__(self) -> None:
        try:
            decisions = tuple(self.decisions)
        except TypeError:
            raise TypeError("decisions must be an iterable") from None
        if not decisions:
            raise ValueError("decisions must not be empty")
        if any(not isinstance(item, SelectorDecision) for item in decisions):
            raise TypeError("decisions must contain only SelectorDecision values")
        if len({item.seat for item in decisions}) != len(decisions):
            raise ValueError("decisions must not repeat a seat")
        if len({item.revision for item in decisions}) != 1:
            raise ValueError("decisions in one commit must share one revision")

        object.__setattr__(self, "decisions", decisions)
