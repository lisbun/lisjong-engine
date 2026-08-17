"""match seedから局ごとのround seedを決定的に導出するpureなmodule。

`RandomSource`と`create_shuffled_wall()`は既に確定済みだが（Issue #5）、
match seedを各局へどう割り当てるかはMatch層（Issue #24）へ保留されていた。
本moduleはその割当規則だけを、`MatchState`等のmutable state無しに提供する。

```text
match seed
+ 1-based round ordinal
        ↓
stable deterministic derivation (SHA-256)
        ↓
round seed
        ↓
RandomSource(round_seed)
        ↓
create_shuffled_wall(...)
        ↓
Wall
```

連荘によって同じ`RoundPosition`が繰り返されても、round ordinalが異なれば
別のround seedになる。「何局目として実際に開始されたか」を表すordinalの
保持・incrementはMatchState側の責務であり、本moduleはglobal counterを
持たない。
"""

import hashlib
from dataclasses import dataclass

from lisjong_engine.random_source import RandomSource
from lisjong_engine.wall import Wall, create_shuffled_wall

_ROUND_SEED_DOMAIN = "lisjong-engine:round-seed:v1"


def _validate_match_seed(match_seed: int) -> None:
    if type(match_seed) is not int:
        raise TypeError("match_seed must be an int")


def _validate_round_ordinal(round_ordinal: int) -> None:
    if type(round_ordinal) is not int:
        raise TypeError("round_ordinal must be an int")
    if round_ordinal < 1:
        raise ValueError("round_ordinal must be a positive int (1-based)")


def derive_round_seed(match_seed: int, round_ordinal: int) -> int:
    """match seedと1-based round ordinalから、局seedをdeterministicに導出する。

    stdlibの`hashlib.sha256`だけを使い、domain-separatedなcanonical
    UTF-8 textをdigestして、その全bitをunsigned big-endian整数として
    解釈する。`hash()`、`random`のglobal state、UUID、時刻、process ID、
    process-global counter、OSの乱数源には依存しない。このalgorithmは
    project全体のreplay可能性の正本であり、変更しない。
    """
    _validate_match_seed(match_seed)
    _validate_round_ordinal(round_ordinal)

    payload = f"{_ROUND_SEED_DOMAIN}:{match_seed}:{round_ordinal}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest, byteorder="big", signed=False)


@dataclass(frozen=True)
class RoundRandomProvenance:
    """1局分のrandom provenance。replay / artifactで局の乱数由来を追跡できる。

    ``match_seed`` / ``round_ordinal`` / ``round_seed`` の整合性はvalue object
    自身が保証する。
    """

    match_seed: int
    round_ordinal: int
    round_seed: int

    def __post_init__(self) -> None:
        _validate_match_seed(self.match_seed)
        _validate_round_ordinal(self.round_ordinal)
        if type(self.round_seed) is not int:
            raise TypeError("round_seed must be an int")

        expected_round_seed = derive_round_seed(
            self.match_seed,
            self.round_ordinal,
        )
        if self.round_seed != expected_round_seed:
            raise ValueError(
                "round_seed must match derive_round_seed(match_seed, round_ordinal)"
            )


def create_round_random_provenance(
    match_seed: int,
    round_ordinal: int,
) -> RoundRandomProvenance:
    """match seedとround ordinalから`RoundRandomProvenance`をpureに構築する。"""
    round_seed = derive_round_seed(match_seed, round_ordinal)
    return RoundRandomProvenance(
        match_seed=match_seed,
        round_ordinal=round_ordinal,
        round_seed=round_seed,
    )


def create_round_wall(provenance: RoundRandomProvenance) -> Wall:
    """provenanceの`round_seed`だけを使い、決定的にshuffleされた`Wall`を返す。

    既存の`RandomSource`と`create_shuffled_wall()`をそのまま利用し、
    shuffle logicを再実装しない。同じprovenanceからは常に同じWallになる。
    """
    if not isinstance(provenance, RoundRandomProvenance):
        raise TypeError("provenance must be a RoundRandomProvenance")

    return create_shuffled_wall(RandomSource(provenance.round_seed))
