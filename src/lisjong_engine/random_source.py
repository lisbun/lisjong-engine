from collections.abc import MutableSequence
from random import Random
from typing import Any


class RandomSource:
    """seedから決定的に生成される、engine専用の乱数source。

    engineは暗黙のglobal random stateへ依存せず、乱数が必要な処理へ本classを
    明示的に注入する。同一seedから独立に生成した`RandomSource`は、同じ入力に
    対して同じ結果を返す。

    半荘seedと局seedの配分規則はMatch層の責務であり、本classは扱わない。
    """

    def __init__(self, seed: int) -> None:
        if type(seed) is not int:
            raise TypeError("seed must be an int")

        self._seed = seed
        self._random = Random(seed)

    @property
    def seed(self) -> int:
        return self._seed

    def shuffle(self, items: MutableSequence[Any]) -> None:
        """`items`をin-placeでshuffleする。"""
        self._random.shuffle(items)
