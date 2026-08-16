import os
import json
import re
from flask import Blueprint, request, render_template

enemy_bp = Blueprint('enemy', __name__, template_folder='../templates')

JSON_FILE = 'nyanko_encyclopedia_enemy.json'
PER_PAGE = 30

# --- 属性（この敵自身が持つ属性バッジ） -----------------------------------
ATTRIBUTE_KEYWORDS = [
    ("white", "白い敵"),
    ("red", "赤い敵"),
    ("black", "黒い敵"),
    ("floating", "浮いてる敵"),
    ("metal", "メタルな敵"),
    ("angel", "天使"),
    ("alien", "エイリアン"),
    ("star_alien", "スターエイリアン"),
    ("zombie", "ゾンビ"),
    ("ancient", "古代種"),
    ("devil", "悪魔"),
    ("superorganism", "超生命体"),
    ("superbeast", "超獣"),
    ("sage", "超賢者"),
    ("kaijin", "怪人"),
    ("witch", "魔女"),
    ("apostle", "使徒"),
    ("none_attr", "無属性な敵"),
]

# --- 特性（敵が持つ攻撃効果・特殊能力） -----------------------------------
# (id, 表示ラベル, マッチ用パターン, パターンが正規表現かどうか)
EFFECT_KEYWORDS = [
    ("crit_heavy", "渾身の一撃", "渾身の一撃", False),
    ("crit", "クリティカル", r'クリティカル(?!.*除く)', True),

    ("wave", "波動", r'(?<!小)波動', True),
    ("mini_wave", "小波動", "小波動", False),
    ("surge", "烈波", r'^(?!倒されたら).*Lv\d+(?<!小)烈波(?!反射)', True),
    ("mini_surge", "小烈波", "小烈波", False),
    ("surge_reflect", "烈波反射", "烈波反射", False),
    ("surge_on_death", "倒されたら烈波", r'倒されたら.*烈波', True),
    ("blast", "爆波", "爆波", False),

    ("knockback", "ふっとばす", "ふっとばす", False),
    ("stop", "動きを止める", "動きを止める", False),
    ("slow", "動きを遅くする", "動きを遅くする", False),
    ("long_range", "遠方攻撃", "遠方", False),
    ("omni", "全方位攻撃", "全方位", False),

    ("burrow", "地中移動", "地中移動", False),
    ("resurrect", "蘇生", "蘇生", False),
    ("barrier", "バリア", "バリア", False),
    ("warp", "ワープ", "ワープ", False),
    ("poison", "毒撃", "毒撃", False),
    ("curse", "古代の呪い", "古代の呪い", False),

    ("devil_shield", "悪魔シールド", "悪魔シールド", False),
    ("delay_production", "再生産遅延", r'再生産.*遅延', True),

    ("multi_hit", "連続攻撃", "連続攻撃", False),
    ("single_hit", "1回攻撃", "1回攻撃", False),
    ("atk_up", "攻撃力上昇", r'攻撃力.*上昇', True),
    ("atk_down", "攻撃力低下", r'攻撃力.*低下', True),
    ("revive", "1度だけ生き残る", r'1度だけ.*生き残る', True),
    ("vs_castle", "対お城", r'お城|本体', True),
]

# --- 耐性・無効 -----------------------------------------------------------
# 「無効」＋直後の（〇〇）ペアから抽出したテキストと完全一致で判定
IMMUNITY_KEYWORDS = [
    ("imm_wave", "波動無効", ["波動"]),
    ("imm_surge", "烈波無効", ["烈波"]),
    ("imm_knockback", "ふっとばす無効", ["ふっとばす"]),
    ("imm_stop", "動きを止める無効", ["止める"]),
    ("imm_slow", "動きを遅くする無効", ["遅くする"]),
    ("imm_atkdown", "攻撃力低下無効", ["攻撃力低下"]),
    ("imm_curse", "呪い無効", ["呪い", "古代の呪い"]),
]
PAIR_IMMUNITY_TOKEN_MAP = {}
for kid, _label, tokens in IMMUNITY_KEYWORDS:
    for tok in tokens:
        PAIR_IMMUNITY_TOKEN_MAP[tok] = kid

# --- 期待値ベースの特性（波動・烈波・爆波・クリティカル・渾身の一撃・攻撃力上昇） -------
# 味方版と同じ仕組み。ただし「攻撃力上昇」は敵の場合、味方（「与ダメ xN」形式）と異なり
# 「残り体力50％以下で攻撃力50％上昇」のように上昇率が％で表記されるため、専用の抽出を行う。
WAVE_RE = re.compile(r"(\d+)％の確率で(?:Lv\d+)?(?<!小)波動(?!ストッパー)")
MINI_WAVE_RE = re.compile(r"(\d+)％の確率でLv(\d+)小波動")
SURGE_RE = re.compile(r"(\d+)％の確率でLv(\d+)(?<!小)烈波(?!反射)")
MINI_SURGE_RE = re.compile(r"(\d+)％の確率でLv(\d+)小烈波")
BLAST_RE = re.compile(r"(\d+)％の確率で爆波")
CRIT_PROB_RE = re.compile(r"(\d+)％の確率でクリティカル")
KONSHIN_RE = re.compile(r"(\d+)％の確率で渾身の一撃（与ダメ\s*[x×]([\d.]+)）")
ATK_UP_PERCENT_RE = re.compile(r"攻撃力(\d+)％上昇")


def compute_ev_traits(inflict_abilities):
    """発生確率をもとにした期待値ベースの攻撃力上昇特性の一覧を返す（敵版）。"""
    traits = []

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

    for ab in inflict_abilities:
        m = ATK_UP_PERCENT_RE.search(ab)
        if m:
            pct = int(m.group(1))
            mult = 1 + pct / 100
            traits.append({
                "id": "atk_up_low_hp", "label": "攻撃力上昇", "kind": "prob",
                "prob": 1.0, "atkMult": mult, "dpsCoef": mult - 1,
                "display": "攻撃力{}％上昇".format(pct),
            })
            break

    return traits

SORT_FIELDS = {
    'no': 'catalog_no',
    'name': 'name',
    'hp': 'hp', 'atk': 'atk', 'dps': 'dps',
    'range': 'range', 'speed': 'speed',
}


def load_data():
    if not os.path.exists(JSON_FILE):
        return []
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for i, char in enumerate(data):
            char['id'] = i
            char['clean_name'] = clean_name(char.get('name', ''))
            char['catalog_no'] = extract_catalog_no(char.get('name', ''))
        return data


def clean_name(raw_name):
    name = raw_name.replace("にゃんこ大戦争DB", "")
    name = re.sub(r'No\.\d+', '', name)
    return re.sub(r'\s+', ' ', name).strip()


def extract_catalog_no(raw_name):
    m = re.search(r'No\.(\d+)', raw_name)
    return int(m.group(1)) if m else None


def analyze_abilities(stats):
    """敵の特性テキストを解析し、以下を返す。
    1) inflict_abilities: 特性(付与)の判定に使うテキスト一覧（「無効」＋直後の括弧ペアを除く）
    2) immunity_tags: 耐性・無効タグの集合
    """
    raw = list((stats or {}).get('abilities', []))

    immunity_tags = set()
    inflict_abilities = []
    skip_next = False
    for i, ab in enumerate(raw):
        if skip_next:
            skip_next = False
            continue
        if ab == '無効' and i + 1 < len(raw) and raw[i + 1].startswith('（'):
            inner = raw[i + 1].strip('（）')
            for tok in inner.split():
                if tok in PAIR_IMMUNITY_TOKEN_MAP:
                    immunity_tags.add(PAIR_IMMUNITY_TOKEN_MAP[tok])
            skip_next = True
            continue
        inflict_abilities.append(ab)

    return inflict_abilities, immunity_tags


def compute_effect_matches(inflict_abilities):
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


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


all_enemies = load_data()


@enemy_bp.route('/')
def zukan():
    args = request.args

    q = args.get('q', '').strip()
    collabo = args.get('collabo', 'all')
    target = args.get('target', 'all')
    sort_key = args.get('sort', 'no')
    sort_dir = args.get('dir', 'asc')
    try:
        page = max(1, int(args.get('page', 1)))
    except ValueError:
        page = 1

    range_filters = {}
    for field in ['hp', 'atk', 'dps', 'range', 'speed']:
        vmin = to_float(args.get(f'{field}_min'))
        vmax = to_float(args.get(f'{field}_max'))
        range_filters[field] = (vmin, vmax)

    selected_attrs = [k for k, _l in ATTRIBUTE_KEYWORDS if args.get(f'kw_{k}') == '1']
    selected_effects = [k for k, _l, _p, _r in EFFECT_KEYWORDS if args.get(f'kw_{k}') == '1']
    selected_immunities = [k for k, _l, _t in IMMUNITY_KEYWORDS if args.get(f'kw_{k}') == '1']

    results = []
    for char in all_enemies:
        stats = char.get('stats') or {}

        if collabo == 'yes' and not char.get('is_collabo'):
            continue
        if collabo == 'no' and char.get('is_collabo'):
            continue

        if q and q.lower() not in char['clean_name'].lower():
            continue

        if target != 'all' and stats.get('target') != target:
            continue

        char_attrs = set(char.get('attributes', []))
        if selected_attrs and not all(k in char_attrs for k in selected_attrs):
            continue

        inflict_abilities, immunity_tags = analyze_abilities(stats)

        stat_values = {}
        skip = False
        for field, (vmin, vmax) in range_filters.items():
            val = to_float(stats.get(field))
            stat_values[field] = val
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
            'url': char.get('url'),
            'target': stats.get('target'),
            'attributes': char_attrs,
            'abilities': inflict_abilities,
            'immunity_tags': immunity_tags,
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

    attribute_labels = {kid: label for kid, label in ATTRIBUTE_KEYWORDS}
    immunity_labels = {kid: label for kid, label, _t in IMMUNITY_KEYWORDS}

    ev_traits_map = {str(r['id']): r['ev_traits'] for r in page_results if r['ev_traits']}
    ev_traits_json = json.dumps(ev_traits_map, ensure_ascii=False)

    return render_template(
        'zukan_enemy.html',
        characters=page_results,
        total=total,
        page=page,
        total_pages=total_pages,
        all_matched_names=all_matched_names,
        attribute_keywords=ATTRIBUTE_KEYWORDS,
        effect_keywords=EFFECT_KEYWORDS,
        immunity_keywords=IMMUNITY_KEYWORDS,
        attribute_labels=attribute_labels,
        immunity_labels=immunity_labels,
        selected_attrs=selected_attrs,
        selected_effects=selected_effects,
        selected_immunities=selected_immunities,
        ev_traits_json=ev_traits_json,
        args=args,
        q=q, collabo=collabo, target=target,
        sort_key=sort_key, sort_dir=sort_dir,
    )

