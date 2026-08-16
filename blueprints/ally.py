import os
import json
import re
from flask import Blueprint, request, render_template

ally_bp = Blueprint('ally', __name__, template_folder='../templates')

JSON_FILE = 'nyanko_encyclopedia.json'
PER_PAGE = 30

# --- 対応属性キーワード -------------------------------------------------
# (id, 表示ラベル, 本文中で検索する部分文字列)
ATTRIBUTE_KEYWORDS = [
    ("red", "赤い敵", "赤い敵"),
    ("black", "黒い敵", "黒い敵"),
    ("white", "白い敵", "白い敵"),
    ("angel", "天使", "天使"),
    ("alien", "エイリアン", "エイリアン"),
    ("zombie", "ゾンビ", "ゾンビ"),
    ("devil", "悪魔", "悪魔"),
    ("metal", "メタル", "メタルな敵"),
    ("floating", "浮いてる敵", "浮いてる敵"),
    ("ancient", "古代種", "古代種"),
]
ATTR_IDS = [k for k, _l, _t in ATTRIBUTE_KEYWORDS]

# 「対 全ての敵（〇〇 除く）」の括弧内トークン -> 属性id
# 無・魔・使 はゲーム仕様上「実質除外されない」ため対象から外す（ユーザー指摘の仕様）
FULL_TARGET_EXCLUDE_MAP = {
    "白": "white",
    "メタル": "metal",
    "浮": "floating",
    "黒": "black",
    "赤": "red",
    "エイリアン": "alien",
    "ゾンビ": "zombie",
    "古代種": "ancient",
}
FULL_TARGET_IGNORE_TOKENS = {"無", "魔", "使"}

# --- 特殊効果（攻撃時に相手に与える効果／自身の特性） ---------------------
# (id, 表示ラベル, マッチ用パターン, パターンが正規表現かどうか)
EFFECT_KEYWORDS = [
    ("super_dmg", "超ダメージ", "超ダメージ", False),
    ("extreme_dmg", "極ダメージ", "極ダメージ", False),
    ("tough", "打たれ強い", r'(?<!超)打たれ強い', True),
    ("super_tough", "超打たれ強い", "超打たれ強い", False),
    ("strong", "めっぽう強い", "めっぽう強い", False),
    ("crit_heavy", "渾身の一撃", "渾身の一撃", False),
    ("crit", "クリティカル", r'クリティカル(?!.*除く)', True),
    ("barrier_break_enemy", "バリアブレイク", "バリアブレイク", False),
    ("shield_break", "悪魔シールド貫通", "シールド貫通", False),
    ("wave", "波動", r'(?<!小)波動(?!ストッパー)', True),
    ("mini_wave", "小波動", "小波動", False),
    ("surge", "烈波", r'Lv\d+(?<!小)烈波(?!反射)', True),
    ("mini_surge", "小烈波", "小烈波", False),
    ("blast", "爆波", "爆波", False),
    ("knockback", "ふっとばす", "ふっとばす", False),
    ("stop", "動きを止める", "動きを止める", False),
    ("slow", "動きを遅くする", "動きを遅くする", False),
    ("long_range", "遠方攻撃", "遠方", False),
    ("omni", "全方位攻撃", "全方位", False),
    ("metal_killer", "メタルキラー", "メタルキラー", False),
    ("zombie_killer", "ゾンビキラー", "ゾンビキラー", False),
    ("soul_atk", "魂攻撃", "魂攻撃", False),
    ("summon", "召喚", "召喚", False),
    ("vs_ultra", "超生命体特効", "超生命体", False),
    ("vs_beast", "超獣特効", "超獣", False),
    ("vs_sage", "超賢者特効", "超賢者", False),
    ("witch_killer", "魔女キラー", "魔女キラー", False),
    ("apostle_killer", "使徒キラー", "使徒キラー", False),
    ("multi_hit", "連続攻撃", "連続攻撃", False),
    ("single_hit", "1回攻撃", "1回攻撃", False),
    ("atk_up", "攻撃力上昇", "攻撃力上昇", False),
    ("atk_down", "攻撃力低下", "％に低下", False),
    ("revive", "1度だけ生き残る", "1度だけ生き残る", False),
    ("money", "お金x2", "お金x2", False),
    ("vs_castle", "対お城", "敵城", False),
    ("self_metal", "メタル化", r'^メタル（被ダメージ', True),
    ("curse", "呪い", "呪い", False),
]

# --- 耐性・無効（自分が受ける／防ぐ効果） --------------------------------
# mode='pair'  : 「無効」＋直後の（〇〇）ペアから抽出したトークンと完全一致で判定
# mode='text'  : 通常の特性テキストにそのまま出現する文言を部分一致で判定
IMMUNITY_KEYWORDS = [
    ("imm_wave", "波動無効", "波動", "pair"),
    ("imm_stopper", "波動ストッパー", "波動ストッパー", "text"),
    ("imm_surge", "烈波無効", "烈波", "pair"),
    ("imm_blast", "爆波無効", "爆波", "pair"),
    ("imm_knockback", "ふっとばす無効", "ふっとばす", "pair"),
    ("imm_stop", "動きを止める無効", "止める", "pair"),
    ("imm_slow", "動きを遅くする無効", "遅くする", "pair"),
    ("imm_atkdown", "攻撃力低下無効", "攻撃力低下", "pair"),
    ("imm_warp", "ワープ無効", "ワープ", "pair"),
    ("imm_curse", "古代の呪い無効", "古代の呪い", "pair"),
    ("imm_poison", "毒撃無効", "毒撃", "pair"),
    ("imm_atknull", "攻撃無効", "攻撃無効", "text"),
]

PAIR_IMMUNITY_TOKEN_MAP = {text: kid for kid, _label, text, mode in IMMUNITY_KEYWORDS if mode == 'pair'}
TEXT_IMMUNITY_ITEMS = [(kid, text) for kid, _label, text, mode in IMMUNITY_KEYWORDS if mode == 'text']

RARITY_ORDER = ["基本", "EX", "レア", "激レア", "超激レア", "伝説レア"]

# --- レベル成長ルール ------------------------------------------------------
# tiers: [(合計値の上限, その区間でのレベル毎上昇率), ...]  最後の上限はNoneで「それ以上」を表す
# ref  : JSONに保存されているステータスが何レベル時点の値か（基本のみ110、それ以外は30）
# max  : そのレアリティが取りうるレベル+プラス値合計の最大値
GROWTH_RULES = {
    "basic":    {"tiers": [(60, 0.20), (None, 0.10)], "ref": 110, "max": 110},
    "ex":       {"tiers": [(60, 0.20), (None, 0.10)], "ref": 30, "max": 100},
    "rare":     {"tiers": [(70, 0.20), (90, 0.10), (None, 0.05)], "ref": 30, "max": 130},
    "srare":    {"tiers": [(60, 0.20), (None, 0.10)], "ref": 30, "max": 120},
    "urare":    {"tiers": [(60, 0.20), (None, 0.10)], "ref": 30, "max": 130},
    "legend":   {"tiers": [(None, 0.20)], "ref": 30, "max": 59},
    # 狂乱・大狂乱（9体）：レアリティは激レアだが、成長の区切りが20と特殊
    "kyouran":  {"tiers": [(20, 0.20), (None, 0.10)], "ref": 30, "max": 120},
    # ネコムート（1体・3形態）：レアリティはEXだが、成長の区切りが30と特殊
    "nekomute": {"tiers": [(30, 0.20), (None, 0.10)], "ref": 30, "max": 100},
}

RARITY_TO_RULE = {
    "基本": "basic", "EX": "ex", "レア": "rare",
    "激レア": "srare", "超激レア": "urare", "伝説レア": "legend",
}

# ユーザー指定の狂乱・大狂乱9体（clean_name完全一致で判定）
KYOURAN_NAMES = {
    "狂乱のネコ 狂乱のネコビルダー 大狂乱のネコモヒカン",
    "狂乱のタンクネコ 狂乱のネコカベ 大狂乱のゴムネコ",
    "狂乱のバトルネコ 狂乱の勇者ネコ 大狂乱の暗黒ネコ",
    "狂乱のキモネコ 狂乱の美脚ネコ 大狂乱のムキあしネコ",
    "狂乱のウシネコ 狂乱のキリンネコ 大狂乱のネコライオン",
    "狂乱のネコノトリ 狂乱のネコUFO 大狂乱の天空のネコ",
    "狂乱のネコフィッシュ 狂乱のネコクジラ 大狂乱のネコ島",
    "狂乱のネコトカゲ 狂乱のネコドラゴン 大狂乱のネコキングドラゴン",
    "狂乱の巨神ネコ 狂乱のネコダラボッチ 大狂乱のネコジャラミ",
}
NEKOMUTO_NAME = "ネコムート 狂乱のネコムート 覚醒のネコムート"


def get_growth_rule_id(char):
    """キャラクターに適用すべき成長ルールのidを返す。判定不能ならNone。"""
    name = char.get('clean_name', '')
    if name in KYOURAN_NAMES:
        return "kyouran"
    if name == NEKOMUTO_NAME:
        return "nekomute"
    return RARITY_TO_RULE.get(char.get('rarity'))


FORM_KEYS = ['form1', 'form2', 'form3', 'form4']

SORT_FIELDS = {
    'no': 'catalog_no',
    'name': 'name',
    'hp': 'hp', 'atk': 'atk', 'dps': 'dps',
    'range': 'range', 'speed': 'speed',
    'cost': 'cost', 'recharge': 'recharge_sec',
}

FULL_TARGET_RE = re.compile(r'全ての敵（([^）]*)除く）')

# --- 特性によるステータス上昇（詳細パネルのオン/オフ機能で使用） ------------
# GROUP_A（赤黒天使エイリアンゾンビメタル浮いてる敵）と
# GROUP_B（白・古代種・悪魔）で倍率が異なる特性
GROUP_A = {"red", "black", "angel", "alien", "zombie", "metal", "floating"}
GROUP_B = {"white", "ancient", "devil"}

# (id, 表示ラベル, 検索用正規表現, GROUP_A時倍率{atk,hp}, GROUP_B時倍率{atk,hp})
SPECIAL_GROUP_TRAITS = [
    ("dmg_super", "超ダメージ", r"超ダメージ", {"atk": 4, "hp": 1}, {"atk": 3, "hp": 1}),
    ("dmg_extreme", "極ダメージ", r"極ダメージ", {"atk": 6, "hp": 1}, {"atk": 5, "hp": 1}),
    ("tough", "打たれ強い", r"(?<!超)打たれ強い", {"atk": 1, "hp": 5}, {"atk": 1, "hp": 4}),
    ("super_tough", "超打たれ強い", r"超打たれ強い", {"atk": 1, "hp": 7}, {"atk": 1, "hp": 6}),
    ("strong", "めっぽう強い", r"めっぽう強い", {"atk": 1.8, "hp": 2.5}, {"atk": 1.5, "hp": 2}),
]

# 属性が単一（グループ分けなし）の特効系特性
# (id, 表示ラベル, 検索文字列, 倍率{atk,hp})
SPECIAL_SINGLE_TRAITS = [
    ("vs_beast", "超獣特効", "超獣", {"atk": 2.5, "hp": 5 / 3}),
    ("vs_ultra", "超生命体特効", "超生命体", {"atk": 1.6, "hp": 10 / 7}),
    ("vs_sage", "超賢者特効", "超賢者", {"atk": 1.2, "hp": 2}),
]

# 体力低下時の攻撃力上昇。倍率がキャラクターごとに異なるため、
# DBの特性テキスト（例:「体力50％以下で攻撃力上昇（与ダメ x1.5）」）から都度倍率を読み取る
ATK_UP_ON_LOW_HP_RE = re.compile(r"攻撃力上昇（与ダメ\s*[x×]([\d.]+)）")

# 波動・小波動・烈波・小烈波・爆波・クリティカル・渾身の一撃は、いずれも
# 「発生確率」をDBテキストから読み取り、DPSの期待値計算に使う。
# 「小波動」「小烈波」は文字列に「波動」「烈波」を含むため、否定先読みで区別する。
WAVE_RE = re.compile(r"(\d+)％の確率で(?:Lv\d+)?(?<!小)波動(?!ストッパー)")
MINI_WAVE_RE = re.compile(r"(\d+)％の確率でLv(\d+)小波動")
SURGE_RE = re.compile(r"(\d+)％の確率でLv(\d+)(?<!小)烈波(?!反射)")
MINI_SURGE_RE = re.compile(r"(\d+)％の確率でLv(\d+)小烈波")
BLAST_RE = re.compile(r"(\d+)％の確率で爆波")
CRIT_PROB_RE = re.compile(r"(\d+)％の確率でクリティカル")
KONSHIN_RE = re.compile(r"(\d+)％の確率で渾身の一撃（与ダメ\s*[x×]([\d.]+)）")


def extract_line_attrs(ability_text):
    """1行の特性テキストから、それが対象とする属性idの集合を抽出する。
    「全ての敵（〇〇除く）」表記にも対応。"""
    m = FULL_TARGET_RE.search(ability_text)
    if m:
        excluded = set()
        for tok in m.group(1).split():
            if tok in FULL_TARGET_IGNORE_TOKENS:
                continue
            if tok in FULL_TARGET_EXCLUDE_MAP:
                excluded.add(FULL_TARGET_EXCLUDE_MAP[tok])
        return set(ATTR_IDS) - excluded
    attrs = set()
    for kid, _label, text in ATTRIBUTE_KEYWORDS:
        if text in ability_text:
            attrs.add(kid)
    return attrs


ATTR_SHORT_LABEL = {
    "red": "赤", "black": "黒", "white": "白", "angel": "天使",
    "alien": "エイリアン", "zombie": "ゾンビ", "devil": "悪魔",
    "metal": "メタル", "floating": "浮いてる敵", "ancient": "古代",
}


def compute_ev_traits(inflict_abilities):
    """発生確率をもとにした期待値ベースの攻撃力上昇特性の一覧を返す。
    各traitは以下を持つ:
      kind='flat'  : 確率なし。オンにすると常に atkMult 倍（体力低下で攻撃力上昇）
      kind='prob'  : 確率 prob でトリガーし、攻撃力は atkMult 倍（デタミニスティック表示用）、
                     DPS期待値は 1 + dpsCoef * prob 倍
    """
    traits = []

    for ab in inflict_abilities:
        m = ATK_UP_ON_LOW_HP_RE.search(ab)
        if m:
            mult_val = float(m.group(1))
            traits.append({
                "id": "atk_up_low_hp", "label": "攻撃力上昇", "kind": "flat",
                "atkMult": mult_val,
                "display": "攻撃力上昇 {}倍".format(_fmt_num(mult_val)),
            })
            break

    for ab in inflict_abilities:
        m = WAVE_RE.search(ab)
        if m:
            prob = int(m.group(1)) / 100
            traits.append({
                "id": "wave_dmg", "label": "波動", "kind": "prob",
                "prob": prob, "atkMult": 2, "dpsCoef": 1,
                "display": "波動 {}%".format(m.group(1)),
            })
            break

    for ab in inflict_abilities:
        m = MINI_WAVE_RE.search(ab)
        if m:
            prob = int(m.group(1)) / 100
            traits.append({
                "id": "mini_wave_dmg", "label": "小波動", "kind": "prob",
                "prob": prob, "atkMult": 1.2, "dpsCoef": 0.2,
                "display": "小波動 {}%".format(m.group(1)),
            })
            break

    for ab in inflict_abilities:
        m = SURGE_RE.search(ab)
        if m:
            prob = int(m.group(1)) / 100
            lv = int(m.group(2))
            traits.append({
                "id": "surge_dmg", "label": "烈波", "kind": "prob",
                "prob": prob, "atkMult": 1 + lv, "dpsCoef": lv,
                "display": "烈波Lv{} {}%".format(lv, m.group(1)),
                "appliedTag": "烈波（全弾ヒット）",
            })
            break

    for ab in inflict_abilities:
        m = MINI_SURGE_RE.search(ab)
        if m:
            prob = int(m.group(1)) / 100
            lv = int(m.group(2))
            traits.append({
                "id": "mini_surge_dmg", "label": "小烈波", "kind": "prob",
                "prob": prob, "atkMult": 1 + lv * (1 / 5), "dpsCoef": lv * (1 / 5),
                "display": "小烈波Lv{} {}%".format(lv, m.group(1)),
                "appliedTag": "小烈波（全弾ヒット）",
            })
            break

    for ab in inflict_abilities:
        m = BLAST_RE.search(ab)
        if m:
            prob = int(m.group(1)) / 100
            traits.append({
                "id": "blast_dmg", "label": "爆波", "kind": "prob",
                "prob": prob, "atkMult": 2, "dpsCoef": 1,
                "display": "爆波 {}%".format(m.group(1)),
            })
            break

    for ab in inflict_abilities:
        m = CRIT_PROB_RE.search(ab)
        if m:
            prob = int(m.group(1)) / 100
            traits.append({
                "id": "crit", "label": "クリティカル", "kind": "prob",
                "prob": prob, "atkMult": 2, "dpsCoef": 1,
                "display": "{}％の確率でクリティカル".format(m.group(1)),
            })
            break

    for ab in inflict_abilities:
        m = KONSHIN_RE.search(ab)
        if m:
            prob = int(m.group(1)) / 100
            mult = float(m.group(2))
            traits.append({
                "id": "konshin", "label": "渾身の一撃", "kind": "prob",
                "prob": prob, "atkMult": mult, "dpsCoef": mult - 1,
                "display": "{}％の確率で渾身の一撃".format(m.group(1)),
            })
            break

    return traits


def _fmt_num(v):
    return str(int(v)) if float(v).is_integer() else str(v)


def compute_special_traits(inflict_abilities):
    """キャラクター（1形態分）が持つ、ステータスをオン/オフで変更できる特性の一覧を返す。"""
    traits = []
    for tid, label, pattern, mult_a, mult_b in SPECIAL_GROUP_TRAITS:
        matched_cats = set()
        for ab in inflict_abilities:
            if re.search(pattern, ab):
                matched_cats |= extract_line_attrs(ab)
        cats_a = sorted(matched_cats & GROUP_A, key=lambda k: ATTR_IDS.index(k))
        cats_b = sorted(matched_cats & GROUP_B, key=lambda k: ATTR_IDS.index(k))
        if cats_a or cats_b:
            traits.append({
                "id": tid, "label": label, "kind": "group",
                "hasA": bool(cats_a), "hasB": bool(cats_b),
                "catsA": [ATTR_SHORT_LABEL[c] for c in cats_a],
                "catsB": [ATTR_SHORT_LABEL[c] for c in cats_b],
                "multA": mult_a, "multB": mult_b,
            })
    for tid, label, text, mult in SPECIAL_SINGLE_TRAITS:
        if any(text in ab for ab in inflict_abilities):
            traits.append({
                "id": tid, "label": label, "kind": "single",
                "targetLabel": text, "mult": mult,
            })
    return traits


def load_data():
    if not os.path.exists(JSON_FILE):
        return []
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for i, char in enumerate(data):
            char['id'] = i
            char['clean_name'] = clean_name(char.get('name', ''))
            char['catalog_no'] = extract_catalog_no(char.get('name', ''))
            char['growth_rule'] = get_growth_rule_id(char)
        return data


def clean_name(raw_name):
    name = raw_name.replace("にゃんこ大戦争DB", "")
    name = re.sub(r'No\.\d+', '', name)
    return re.sub(r'\s+', ' ', name).strip()


def extract_catalog_no(raw_name):
    m = re.search(r'No\.(\d+)', raw_name)
    return int(m.group(1)) if m else None


def analyze_form_abilities(form_dict):
    """1つの形態の特性テキストを解析し、以下3つを返す。
    1) inflict_abilities: 攻撃時に相手へ与える効果・自身の特性の判定に使うテキスト一覧
       （「無効」＋直後の括弧ペア、および単独の「波動ストッパー」行を除く）
    2) immunity_tags: 耐性・無効タグの集合
    3) matched_attrs: 対応属性（「全ての敵（〇〇除く）」表記を含む）の集合
    """
    raw = list((form_dict or {}).get('abilities', []))

    immunity_tags = set()
    inflict_abilities = []
    skip_next = False
    for i, ab in enumerate(raw):
        if skip_next:
            skip_next = False
            continue
        # 「無効」＋直後の（〇〇）ペア -> 耐性・無効タグとして分離
        if ab == '無効' and i + 1 < len(raw) and raw[i + 1].startswith('（'):
            inner = raw[i + 1].strip('（）')
            for tok in inner.split():
                if tok in PAIR_IMMUNITY_TOKEN_MAP:
                    immunity_tags.add(PAIR_IMMUNITY_TOKEN_MAP[tok])
            skip_next = True  # 直後の括弧テキストも読み飛ばす
            continue
        # 単独テキストで判定する耐性系（波動ストッパー／攻撃無効）
        matched_text_immunity = False
        for kid, text in TEXT_IMMUNITY_ITEMS:
            if text in ab:
                immunity_tags.add(kid)
                if kid == 'imm_stopper':
                    matched_text_immunity = True  # 波動ストッパーは特性欄からも除外
        if matched_text_immunity:
            continue
        inflict_abilities.append(ab)

    matched_attrs = set()
    for ab in inflict_abilities:
        m = FULL_TARGET_RE.search(ab)
        if m:
            excluded = set()
            for tok in m.group(1).split():
                if tok in FULL_TARGET_IGNORE_TOKENS:
                    continue
                if tok in FULL_TARGET_EXCLUDE_MAP:
                    excluded.add(FULL_TARGET_EXCLUDE_MAP[tok])
            matched_attrs |= (set(ATTR_IDS) - excluded)
        else:
            for kid, _label, text in ATTRIBUTE_KEYWORDS:
                if text in ab:
                    matched_attrs.add(kid)

    return inflict_abilities, immunity_tags, matched_attrs


def compute_effect_matches(inflict_abilities):
    """inflict_abilities（無効ペア等を除いたテキスト一覧）から、
    該当する特殊効果キーワードidの集合を返す。"""
    matched = set()
    for kid, _label, pattern, is_regex in EFFECT_KEYWORDS:
        for ab in inflict_abilities:
            if is_regex:
                if re.search(pattern, ab):
                    matched.add(kid)
                    break
            else:
                if pattern in ab:
                    matched.add(kid)
                    break
    return matched


def get_display_form(char, form_choice):
    """form_choice: '1'/'2'/'3'/'4'/'final' -> (form_dict, form_label) か (None, None)"""
    if form_choice == 'final':
        for idx, fk in enumerate(reversed(FORM_KEYS), start=0):
            f = char.get(fk)
            if f:
                form_num = 4 - idx
                return f, f"第{form_num}形態"
        return None, None
    fk = f'form{form_choice}'
    f = char.get(fk)
    if f:
        return f, f"第{form_choice}形態"
    return None, None


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


all_characters = load_data()
HAS_RARITY_DATA = any(c.get('rarity') for c in all_characters)


@ally_bp.route('/')
def zukan():
    args = request.args

    q = args.get('q', '').strip()
    collabo = args.get('collabo', 'all')
    target = args.get('target', 'all')
    rarity = args.get('rarity', 'all')
    form_choice = args.get('form', 'final')
    sort_key = args.get('sort', 'no')
    sort_dir = args.get('dir', 'asc')
    try:
        page = max(1, int(args.get('page', 1)))
    except ValueError:
        page = 1

    range_filters = {}
    for field, seconds in [('hp', False), ('atk', False), ('dps', False),
                            ('range', False), ('speed', False), ('cost', False),
                            ('recharge', True)]:
        vmin = to_float(args.get(f'{field}_min'))
        vmax = to_float(args.get(f'{field}_max'))
        range_filters[field] = (vmin, vmax, seconds)

    selected_attrs = [k for k, _l, _t in ATTRIBUTE_KEYWORDS if args.get(f'kw_{k}') == '1']
    selected_effects = [k for k, _l, _p, _r in EFFECT_KEYWORDS if args.get(f'kw_{k}') == '1']
    selected_immunities = [k for k, _l, _t, _m in IMMUNITY_KEYWORDS if args.get(f'kw_{k}') == '1']

    results = []
    for char in all_characters:
        f, form_label = get_display_form(char, form_choice)
        if f is None:
            continue

        if collabo == 'yes' and not char.get('is_collabo'):
            continue
        if collabo == 'no' and char.get('is_collabo'):
            continue

        if rarity != 'all' and char.get('rarity') != rarity:
            continue

        if q and q.lower() not in char['clean_name'].lower():
            continue

        if target != 'all' and f.get('target') != target:
            continue

        inflict_abilities, immunity_tags, matched_attrs = analyze_form_abilities(f)

        stat_values = {}
        skip = False
        for field, (vmin, vmax, is_seconds) in range_filters.items():
            raw = to_float(f.get(field))
            val = raw
            if is_seconds and raw is not None:
                val = round(raw / 30, 2)
            key = 'recharge_sec' if field == 'recharge' else field
            stat_values[key] = val
            if vmin is not None or vmax is not None:
                if val is None:
                    skip = True
                    break
                if vmin is not None and val < vmin:
                    skip = True
                    break
                if vmax is not None and val > vmax:
                    skip = True
                    break
        if skip:
            continue

        if selected_attrs and not all(k in matched_attrs for k in selected_attrs):
            continue

        effect_matches = compute_effect_matches(inflict_abilities) if selected_effects else set()
        if selected_effects and not all(k in effect_matches for k in selected_effects):
            continue

        if selected_immunities and not all(k in immunity_tags for k in selected_immunities):
            continue

        results.append({
            'id': char['id'],
            'catalog_no': char['catalog_no'],
            'name': char['clean_name'],
            'is_collabo': char.get('is_collabo', False),
            'rarity': char.get('rarity'),
            'growth_rule': char.get('growth_rule'),
            'url': char.get('url'),
            'form_label': form_label,
            'target': f.get('target'),
            'abilities': inflict_abilities,
            'immunity_tags': immunity_tags,
            'matched_attrs': sorted(matched_attrs, key=lambda k: ATTR_IDS.index(k)),
            'special_traits': compute_special_traits(inflict_abilities),
            'ev_traits': compute_ev_traits(inflict_abilities),
            **stat_values,
        })

    reverse = sort_dir == 'desc'
    sort_field = SORT_FIELDS.get(sort_key, 'catalog_no')
    if sort_field == 'name':
        results.sort(key=lambda r: r['name'], reverse=reverse)
    else:
        results.sort(key=lambda r: (r[sort_field] is None, r[sort_field] or 0), reverse=reverse)

    total = len(results)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, total_pages)
    start = (page - 1) * PER_PAGE
    page_results = results[start:start + PER_PAGE]
    all_matched_names = [r['name'] for r in results]

    special_traits_map = {str(r['id']): r['special_traits'] for r in page_results if r['special_traits']}
    special_traits_json = json.dumps(special_traits_map, ensure_ascii=False)

    ev_traits_map = {str(r['id']): r['ev_traits'] for r in page_results if r['ev_traits']}
    ev_traits_json = json.dumps(ev_traits_map, ensure_ascii=False)

    immunity_labels = {kid: label for kid, label, _t, _m in IMMUNITY_KEYWORDS}
    attribute_labels = {kid: label for kid, label, _t in ATTRIBUTE_KEYWORDS}

    return render_template(
        'zukan.html',
        characters=page_results,
        total=total,
        page=page,
        total_pages=total_pages,
        all_matched_names=all_matched_names,
        attribute_keywords=ATTRIBUTE_KEYWORDS,
        effect_keywords=EFFECT_KEYWORDS,
        immunity_keywords=IMMUNITY_KEYWORDS,
        immunity_labels=immunity_labels,
        attribute_labels=attribute_labels,
        selected_attrs=selected_attrs,
        selected_effects=selected_effects,
        selected_immunities=selected_immunities,
        rarity_order=RARITY_ORDER,
        has_rarity_data=HAS_RARITY_DATA,
        growth_rules_json=json.dumps(GROWTH_RULES, ensure_ascii=False),
        special_traits_json=special_traits_json,
        ev_traits_json=ev_traits_json,
        args=args,
        q=q, collabo=collabo, target=target, rarity=rarity, form_choice=form_choice,
        sort_key=sort_key, sort_dir=sort_dir,
    )

