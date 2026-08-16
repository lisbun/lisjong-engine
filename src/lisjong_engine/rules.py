"""麻雀ルールの設定値を保持する単一の値型`RuleSet`を定義するmodule。

`RuleSet`はrule **設定値** だけを持ち、ゲーム状態、状態遷移、役判定、
符計算、Policyそのものは持たない。ゲームmechanicsは`RuleSet`の具体的な
fieldとpolicy enumを参照して分岐し、ルールセット名では分岐しない。

設定値の意味と標準ルールの内容は`docs/rules.md`を正本とする。
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lisjong_engine.yaku import Yaku

# パオ（責任払い）を成立させ得る役。責任者を一意に特定できる副露で
# 確定する役満だけを対象とする。
_SUPPORTED_PAO_YAKU = frozenset(
    {
        Yaku.DAISANGEN,
        Yaku.DAISUUSHII,
        Yaku.SUUKANTSU,
    }
)

# ダブル役満（2倍役満）として扱う候補がある役。どれを実際に採用するかは
# `RuleSet.double_yakuman_variants`で選ぶ。
_DOUBLE_YAKUMAN_VARIANT_CANDIDATES = frozenset(
    {
        Yaku.SUUANKOU_TANKI,
        Yaku.KOKUSHI_MUSOU_13_WAIT,
        Yaku.DAISUUSHII,
        Yaku.JUNSEI_CHUUREN_POUTOU,
    }
)


class MatchFormat(Enum):
    HANCHAN = "hanchan"


class MultipleRonAwardPolicy(Enum):
    """複数ロン成立後、本場・供託を誰が受け取るかを表す。"""

    NEAREST_WINNER_TO_DISCARDER = "nearest_winner_to_discarder"


class RonResolutionPolicy(Enum):
    """複数席が同じ牌へロンを選択したときの成立人数を表す。

    `MultipleRonAwardPolicy`が「複数ロン成立後、本場・供託を誰が
    受け取るか」を扱うのに対し、このenumは「複数ロン選択時に
    そもそも何人を和了者として成立させるか」を扱う、別の軸の
    ポリシーである。

    ``MULTIPLE_RON``: ロンを選択した席すべてを和了者として成立させる。
    ``HEAD_BUMP``: 頭ハネ。放銃者から見て最も近い1名だけを和了者として
    成立させる。常に和了者が1名へ確定するため、複数ロン成立を前提とする
    三家和途中流局（`triple_ron_abortive_draw`）とは併用できない。
    """

    MULTIPLE_RON = "multiple_ron"
    HEAD_BUMP = "head_bump"


class KanDoraRevealPolicy(Enum):
    """大明槓・加槓成立時の槓ドラ公開タイミングを表す。

    暗槓は（国士無双の暗槓ロンを除き）槍槓が存在しないため、この
    ポリシーに関わらず成立と同時に槓ドラを公開する。大明槓・加槓は、
    成立前に槍槓ロンで局が終わる可能性があるため、このenumで成立確定と
    公開タイミングの関係を切り替える。

    ``DELAY_OPEN_KAN_DORA``: 大明槓はその直後の打牌がロン以外で解決する
    まで、加槓は槍槓が全員パスされるまで、槓ドラ公開を保留する。嶺上開花の
    和了評価には、保留中の自身の槓ドラを含める。

    ``IMMEDIATE_ON_KAN_CONFIRMATION``: 大明槓・加槓が成立した時点
    （加槓は槍槓に対して全員パスした時点）で、直ちに槓ドラを公開する。
    槍槓で加槓自体が成立しなかった場合は公開しない。
    """

    DELAY_OPEN_KAN_DORA = "delay_open_kan_dora"
    IMMEDIATE_ON_KAN_CONFIRMATION = "immediate_on_kan_confirmation"


class RiichiAnkanPolicy(Enum):
    """立直後の暗槓をどこまで許容するかを表す。

    送り槓禁止（暗槓にツモ牌を含むこと）と待ち牌種類の不変は
    全ポリシー共通の必須条件であり、このenumは、それに加えて
    和了時の面子分解の維持まで要求するかどうかだけを切り替える。
    """

    PRESERVE_WAIT_AND_DECOMPOSITION = "preserve_wait_and_decomposition"
    PRESERVE_WAIT_ONLY = "preserve_wait_only"


class FinalPointsRounding(Enum):
    """最終粗点の計算方式を表す。

    単なる丸め粒度の指定ではなく、1位への残差配分の有無を含めた
    最終粗点計算方式そのものを表すenum。
    """

    TOWARD_ZERO_REMAINDER_TO_FIRST = "toward_zero_remainder_to_first"
    EXACT_NO_ROUNDING = "exact_no_rounding"


class FinalRankTiePolicy(Enum):
    """半荘終了時、同点者をどう順位付けするかを表す。

    ``SEAT_ORDER``: 東1局開始時の風順（東→南→西→北）で同点を一意な
    順位へ分解する。
    ``SPLIT_RANK_POINTS``: 同点者を同順位（標準競技順位、例: 1,1,3,4）
    として扱い、該当する複数順位の順位点合計を人数で均等分配する。
    """

    SEAT_ORDER = "seat_order"
    SPLIT_RANK_POINTS = "split_rank_points"


class PaoCompoundYakumanPolicy(Enum):
    """パオ対象役満と対象外の役満が複合したとき、責任払いの範囲を表す。

    ``FULL_HAND``: パオが成立したら、複合役満の点数を含め和了手全体を
    責任者が支払う。
    ``RESPONSIBLE_YAKUMAN_ONLY``: パオ対象役満の分（本場を含む）だけを
    責任払いとし、対象外の役満分は通常の精算（ロンなら放銃者、ツモなら
    3家）で扱う。
    """

    FULL_HAND = "full_hand"
    RESPONSIBLE_YAKUMAN_ONLY = "responsible_yakuman_only"


@dataclass(frozen=True)
class RuleSet:
    """1つのルールセットを表すfrozenな設定値。

    旧`python-study`の`MahjongRules`・`YakuRules`・`FuRules`を単一契約へ
    統合したものであり、`RulePreset`のような束ね直し用の型は持たない。

    `name`・`version`は識別・version管理・ログ・再現性の補助情報であり、
    ゲームmechanicsの分岐条件には使用しない。分岐は必ず具体的なfieldまたは
    policy enumで行う。
    """

    # 識別情報。mechanicsの分岐条件には使わない。
    name: str
    version: int

    # 対局形式
    match_format: MatchFormat
    player_count: int

    # 持ち点と最終精算の基準
    starting_points: int
    # 最終精算（オカ計算）の基準点。終局判定には使用しない。
    return_points: int
    # 南4以降の終局判定で用いる一位必要点数。最終精算には使用しない。
    # return_pointsと値が同じルールもあるが、意味が異なる独立した概念
    # として維持する。
    first_place_target_points: int
    uma: tuple[int, int, int, int]

    # 終局条件
    bankruptcy_enabled: bool
    bankruptcy_threshold: int
    west_round_enabled: bool
    dealer_win_end_enabled: bool
    dealer_tenpai_end_enabled: bool

    # 得点評価の有効・無効
    rounded_mangan_enabled: bool
    counted_yakuman_enabled: bool
    multiple_yakuman_enabled: bool

    # 本場・供託・罰符
    ron_honba_points: int
    tsumo_honba_points_per_payer: int
    riichi_stick_points: int
    noten_penalty_total: int
    nagashi_mangan_enabled: bool

    # パオ（責任払い）
    pao_enabled: bool
    pao_yaku: frozenset[Yaku]
    # パオ対象役満と対象外役満が複合したときの責任払い範囲。詳細は
    # `PaoCompoundYakumanPolicy`を参照。
    pao_compound_yakuman_policy: PaoCompoundYakumanPolicy

    # 複数ロン
    double_ron_enabled: bool
    ron_resolution_policy: RonResolutionPolicy
    triple_ron_abortive_draw: bool
    multiple_ron_honba_policy: MultipleRonAwardPolicy
    multiple_ron_riichi_stick_policy: MultipleRonAwardPolicy

    # 途中流局
    nine_terminals_abortive_draw_enabled: bool
    four_winds_abortive_draw_enabled: bool
    four_kans_abortive_draw_enabled: bool
    four_riichi_abortive_draw_enabled: bool

    # 最終順位・順位点
    final_points_rounding: FinalPointsRounding
    final_rank_tie_policy: FinalRankTiePolicy
    bankruptcy_bonus_points: int
    bankrupt_player_penalty_points: int

    # 立直・槓
    riichi_ankan_policy: RiichiAnkanPolicy
    # 大明槓・加槓成立時の槓ドラ公開タイミング。詳細は`KanDoraRevealPolicy`
    # を参照。暗槓の公開タイミング（成立と同時）はこの設定の対象外。
    kan_dora_reveal_policy: KanDoraRevealPolicy
    # 暗槓に対する槍槓（国士無双のみ）を許すかどうか。国士無双以外の
    # 通常形・七対子等では、この設定に関わらず暗槓ロンは成立しない。
    kokushi_ankan_chankan_enabled: bool
    # 立直宣言に必要な最低持ち点。Noneは「下限なし」を表し、0点未満
    # （マイナス点）でも立直宣言を許すルールを表現する。
    riichi_minimum_points: int | None
    # 立直宣言に必要なlive wall（山の残り生牌）の最低残枚数。
    # 1を指定すると、海底牌（残り0枚）をツモった直後の立直だけを禁止し、
    # 次巡の自摸番の有無自体は立直可否条件にしない。
    riichi_minimum_live_wall_tiles: int

    # 役に関する設定（旧`YakuRules`相当）。
    # 2倍役満として扱う役。空集合ならダブル役満を採用しない。
    double_yakuman_variants: frozenset[Yaku]

    # 符に関する設定（旧`FuRules`相当）。
    # 連風牌（場風かつ門風）の雀頭に与える符。2または4。
    double_wind_pair_fu: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("name must be a str")
        if not self.name:
            raise ValueError("name must not be empty")

        integer_fields = (
            "version",
            "player_count",
            "starting_points",
            "return_points",
            "first_place_target_points",
            "bankruptcy_threshold",
            "ron_honba_points",
            "tsumo_honba_points_per_payer",
            "riichi_stick_points",
            "noten_penalty_total",
            "bankruptcy_bonus_points",
            "bankrupt_player_penalty_points",
            "riichi_minimum_live_wall_tiles",
            "double_wind_pair_fu",
        )
        for field_name in integer_fields:
            if type(getattr(self, field_name)) is not int:
                raise TypeError(f"{field_name} must be an int")

        if self.riichi_minimum_points is not None and (
            type(self.riichi_minimum_points) is not int
        ):
            raise TypeError("riichi_minimum_points must be an int or None")

        boolean_fields = (
            "bankruptcy_enabled",
            "west_round_enabled",
            "dealer_win_end_enabled",
            "dealer_tenpai_end_enabled",
            "rounded_mangan_enabled",
            "counted_yakuman_enabled",
            "multiple_yakuman_enabled",
            "nagashi_mangan_enabled",
            "double_ron_enabled",
            "triple_ron_abortive_draw",
            "nine_terminals_abortive_draw_enabled",
            "four_winds_abortive_draw_enabled",
            "four_kans_abortive_draw_enabled",
            "four_riichi_abortive_draw_enabled",
            "pao_enabled",
            "kokushi_ankan_chankan_enabled",
        )
        for field_name in boolean_fields:
            if type(getattr(self, field_name)) is not bool:
                raise TypeError(f"{field_name} must be a bool")

        enum_fields = (
            ("match_format", MatchFormat),
            ("ron_resolution_policy", RonResolutionPolicy),
            ("multiple_ron_honba_policy", MultipleRonAwardPolicy),
            ("multiple_ron_riichi_stick_policy", MultipleRonAwardPolicy),
            ("final_points_rounding", FinalPointsRounding),
            ("final_rank_tie_policy", FinalRankTiePolicy),
            ("riichi_ankan_policy", RiichiAnkanPolicy),
            ("kan_dora_reveal_policy", KanDoraRevealPolicy),
            ("pao_compound_yakuman_policy", PaoCompoundYakumanPolicy),
        )
        for field_name, enum_type in enum_fields:
            if not isinstance(getattr(self, field_name), enum_type):
                raise TypeError(f"{field_name} must be a {enum_type.__name__}")

        try:
            uma = tuple(self.uma)
        except TypeError:
            raise TypeError("uma must be an iterable of four ints") from None
        if len(uma) != self.player_count:
            raise ValueError("uma must contain one value for each player")
        if any(type(value) is not int for value in uma):
            raise TypeError("uma must contain only ints")
        if sum(uma) != 0:
            raise ValueError("uma must sum to zero")

        if self.version <= 0:
            raise ValueError("version must be positive")
        if self.player_count != 4:
            raise ValueError("only four-player rules are supported")
        if self.starting_points <= 0 or self.return_points <= 0:
            raise ValueError("starting_points and return_points must be positive")
        if self.first_place_target_points <= 0:
            raise ValueError("first_place_target_points must be positive")
        if self.return_points < self.starting_points:
            raise ValueError("return_points must not be less than starting_points")
        if ((self.return_points - self.starting_points) * self.player_count) % 1_000:
            raise ValueError("oka must be expressible as whole rank points")
        if self.bankruptcy_threshold != 0:
            raise ValueError("bankruptcy_threshold must be zero")
        if self.ron_honba_points < 0 or self.tsumo_honba_points_per_payer < 0:
            raise ValueError("honba payments must be non-negative")
        if self.riichi_stick_points <= 0:
            raise ValueError("riichi_stick_points must be positive")
        if self.noten_penalty_total <= 0 or self.noten_penalty_total % 6 != 0:
            raise ValueError("noten_penalty_total must be positive and divisible by 6")

        pao_yaku = _normalize_yaku_set(self.pao_yaku, "pao_yaku")
        if not pao_yaku <= _SUPPORTED_PAO_YAKU:
            raise ValueError("pao_yaku contains an unsupported yaku")
        if self.pao_enabled and not pao_yaku:
            raise ValueError("enabled pao rules must contain at least one yaku")

        double_yakuman_variants = _normalize_yaku_set(
            self.double_yakuman_variants,
            "double_yakuman_variants",
        )
        if not double_yakuman_variants <= _DOUBLE_YAKUMAN_VARIANT_CANDIDATES:
            raise ValueError("double_yakuman_variants contains an unsupported yaku")

        if self.double_wind_pair_fu not in (2, 4):
            raise ValueError("double_wind_pair_fu must be 2 or 4")

        if self.triple_ron_abortive_draw and not self.double_ron_enabled:
            raise ValueError("triple ron handling requires double ron")
        if (
            self.ron_resolution_policy is RonResolutionPolicy.HEAD_BUMP
            and self.triple_ron_abortive_draw
        ):
            raise ValueError(
                "head bump always resolves to one winner; "
                "triple ron abortive draw cannot apply"
            )
        if self.bankruptcy_bonus_points < 0:
            raise ValueError("bankruptcy_bonus_points must be non-negative")
        if self.bankrupt_player_penalty_points > 0:
            raise ValueError("bankrupt_player_penalty_points must be non-positive")
        if self.bankruptcy_bonus_points + self.bankrupt_player_penalty_points != 0:
            raise ValueError("bankruptcy bonus and penalty must sum to zero")
        if self.riichi_minimum_live_wall_tiles < 1:
            raise ValueError("riichi_minimum_live_wall_tiles must be at least 1")

        object.__setattr__(self, "uma", uma)
        object.__setattr__(self, "pao_yaku", pao_yaku)
        object.__setattr__(
            self,
            "double_yakuman_variants",
            double_yakuman_variants,
        )

    @property
    def oka_points(self) -> int:
        """配給原点と返し点の差から導かれる、1位へ与えるオカの点数。"""
        return (self.return_points - self.starting_points) * self.player_count

    @property
    def oka_rank_points(self) -> int:
        """オカを1,000点単位の順位点へ換算した値。"""
        return self.oka_points // 1_000

    @classmethod
    def default(cls) -> "RuleSet":
        """標準ルールセット`project-standard-v1`を返す。

        呼び出しごとに等価な値を返すが、同一instanceであることは契約
        としない。設定を変えたRuleSetは`dataclasses.replace()`で作る。
        """
        return cls(
            name="project-standard-v1",
            version=1,
            match_format=MatchFormat.HANCHAN,
            player_count=4,
            starting_points=25_000,
            return_points=30_000,
            first_place_target_points=30_000,
            uma=(30, 10, -10, -30),
            bankruptcy_enabled=True,
            bankruptcy_threshold=0,
            west_round_enabled=True,
            dealer_win_end_enabled=True,
            dealer_tenpai_end_enabled=True,
            rounded_mangan_enabled=False,
            counted_yakuman_enabled=True,
            multiple_yakuman_enabled=True,
            ron_honba_points=300,
            tsumo_honba_points_per_payer=100,
            riichi_stick_points=1_000,
            noten_penalty_total=3_000,
            nagashi_mangan_enabled=True,
            pao_enabled=True,
            pao_yaku=frozenset({Yaku.DAISANGEN, Yaku.DAISUUSHII}),
            pao_compound_yakuman_policy=PaoCompoundYakumanPolicy.FULL_HAND,
            double_ron_enabled=True,
            ron_resolution_policy=RonResolutionPolicy.MULTIPLE_RON,
            triple_ron_abortive_draw=True,
            multiple_ron_honba_policy=(
                MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER
            ),
            multiple_ron_riichi_stick_policy=(
                MultipleRonAwardPolicy.NEAREST_WINNER_TO_DISCARDER
            ),
            nine_terminals_abortive_draw_enabled=True,
            four_winds_abortive_draw_enabled=True,
            four_kans_abortive_draw_enabled=True,
            four_riichi_abortive_draw_enabled=True,
            final_points_rounding=FinalPointsRounding.TOWARD_ZERO_REMAINDER_TO_FIRST,
            final_rank_tie_policy=FinalRankTiePolicy.SEAT_ORDER,
            bankruptcy_bonus_points=10,
            bankrupt_player_penalty_points=-10,
            riichi_ankan_policy=RiichiAnkanPolicy.PRESERVE_WAIT_AND_DECOMPOSITION,
            kan_dora_reveal_policy=KanDoraRevealPolicy.DELAY_OPEN_KAN_DORA,
            kokushi_ankan_chankan_enabled=False,
            riichi_minimum_points=1_000,
            riichi_minimum_live_wall_tiles=4,
            double_yakuman_variants=frozenset(),
            double_wind_pair_fu=4,
        )


def _normalize_yaku_set(value: Iterable[Yaku], field_name: str) -> frozenset[Yaku]:
    try:
        yaku_set = frozenset(value)
    except TypeError:
        raise TypeError(f"{field_name} must be an iterable of Yaku values") from None
    if any(not isinstance(yaku, Yaku) for yaku in yaku_set):
        raise TypeError(f"{field_name} must contain only Yaku values")
    return yaku_set
