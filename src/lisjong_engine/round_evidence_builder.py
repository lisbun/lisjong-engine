"""局のengine内部stateから、viewer別のordered player-safe evidenceを構築する。

`round_evidence.py`はinternal event列を入力とするpure projectionであり、
本moduleはそこへ`RoundState`のinternal event historyとruleを渡すだけの
薄いfacadeである。consumerがplayer-safe evidenceを得るためにomniscientな
`RoundState.events`へ直接触れなくて済むように、engine側で唯一の入口を
提供する。

```text
RoundState（internal complete state / events）
    -> build_round_evidence(round_state, viewer_seat)
    -> ordered player-safe evidence
```

`build_seat_observation()`と違い、decision phaseであることは要求しない。
evidenceは意思決定snapshotではなく、局のどの時点でも参照できる
「そのviewerが合法的に観測できた進行」だからである。
"""

from lisjong_engine.round_evidence import RoundEvidence, project_round_evidence
from lisjong_engine.round_state import RoundState
from lisjong_engine.seat import Seat


def build_round_evidence(
    round_state: RoundState,
    viewer_seat: Seat,
) -> tuple[RoundEvidence, ...]:
    """`viewer_seat`から見た、現在までのordered player-safe evidenceを返す。"""
    if not isinstance(round_state, RoundState):
        raise TypeError("round_state must be a RoundState")
    return project_round_evidence(
        round_state.events,
        viewer_seat=viewer_seat,
        rules=round_state.rules,
    )
