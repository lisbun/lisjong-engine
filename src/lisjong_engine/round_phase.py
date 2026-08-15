from enum import Enum


class RoundPhase(Enum):
    """局内の進行段階。状態遷移logic自体は後続Issueで実装する。"""

    UNDEALT = "undealt"
    AWAITING_DRAW = "awaiting_draw"
    AWAITING_DISCARD = "awaiting_discard"
    AWAITING_RINSHAN_DRAW = "awaiting_rinshan_draw"
    AWAITING_REACTIONS = "awaiting_reactions"
    AWAITING_KAKAN_REACTIONS = "awaiting_kakan_reactions"
    AWAITING_ANKAN_REACTIONS = "awaiting_ankan_reactions"
    FINISHED = "finished"
