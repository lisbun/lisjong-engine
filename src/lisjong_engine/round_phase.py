from enum import Enum


class RoundPhase(Enum):
    """局内の進行段階。

    `AWAITING_WIN_FINALIZATION`は、反応windowでロンの成立者が確定した
    一方、点数確定・`RoundResult`構築・終局commitがまだ行われていない
    中間状態を表す。E2はここまでを担当し、E3がこの状態から`FINISHED`へ
    進める。同じ反応windowを二重に解決できないことを、この段階を独立した
    phaseにすることで表現する。
    """

    UNDEALT = "undealt"
    AWAITING_DRAW = "awaiting_draw"
    AWAITING_DISCARD = "awaiting_discard"
    AWAITING_RINSHAN_DRAW = "awaiting_rinshan_draw"
    AWAITING_REACTIONS = "awaiting_reactions"
    AWAITING_KAKAN_REACTIONS = "awaiting_kakan_reactions"
    AWAITING_ANKAN_REACTIONS = "awaiting_ankan_reactions"
    AWAITING_WIN_FINALIZATION = "awaiting_win_finalization"
    FINISHED = "finished"
