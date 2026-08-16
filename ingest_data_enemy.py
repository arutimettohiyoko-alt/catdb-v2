import requests
from bs4 import BeautifulSoup
import re
import time
import json
import copy

MAX_ENEMIES = 1500
JSON_FILE = 'nyanko_encyclopedia_enemy.json'


def parse_v(node):
    if not node:
        return "---"
    temp_node = copy.copy(node)
    for hidden in temp_node.find_all(True, class_=re.compile(r"hide")):
        hidden.decompose()
    text = temp_node.get_text(strip=True)
    match = re.search(r'[\d,]+', text)
    return match.group(0).replace(',', '') if match else "---"


# 敵の属性バッジ表記。ページ本文から該当ワードを検索するベストエフォート実装。
ATTRIBUTE_LABELS = [
    ("white", "白い敵"),
    ("red", "赤い敵"),
    ("black", "黒い敵"),
    ("floating", "浮いてる敵"),
    ("metal", "メタルな敵"),
    ("angel", "天使"),
    ("alien", "エイリアン"),
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

# スターエイリアンは「エイリアン（スター）」という完全な表記でのみ判定する。
# 単に「スター」だけで判定すると「狂乱のスターもねこ」「イベントオールスターズ」等の
# 無関係な文字列まで誤検出するため。
STAR_ALIEN_PATTERNS = ["エイリアン（スター）", "エイリアン(スター)"]


def collect_searchable_text(area):
    """通常のテキストに加え、img要素のalt/title属性も検索対象に含める。
    属性バッジがアイコン画像（altテキストのみ）で表現されている可能性があるため。"""
    if not area:
        return ""
    parts = [area.get_text()]
    for img in area.find_all("img"):
        if img.has_attr("alt"):
            parts.append(img["alt"])
        if img.has_attr("title"):
            parts.append(img["title"])
    return " ".join(parts)


def detect_attributes(full_text):
    attrs = []
    # エイリアンとスターエイリアンは包含関係（スターエイリアンは常にエイリアンでもある）
    # ため、「エイリアン」に一致すればスター有無に関わらずエイリアン判定を付与する。
    for aid, label in ATTRIBUTE_LABELS:
        if label in full_text:
            attrs.append(aid)
    if any(p in full_text for p in STAR_ALIEN_PATTERNS):
        attrs.append("star_alien")
    return attrs


def get_enemy_stat_data(content_area):
    """敵ページの本文から体力・攻撃力・DPS・射程・速度・対象・特性を抽出する。
    敵には進化形態・コスト・再生産・レアリティが無いため、味方版のような
    フォーム分割は行わずフラットな1つのデータとして扱う。"""
    data = {
        "hp": "---", "atk": "---", "dps": "---",
        "range": "---", "speed": "---", "target": "---",
        "atk_freq": "---", "atk_start": "---",
        "abilities": []
    }
    if not content_area:
        return None

    all_tds = content_area.find_all("td")

    for i, td in enumerate(all_tds):
        txt = td.get_text(strip=True)
        if i + 1 >= len(all_tds):
            break
        nxt = all_tds[i + 1]

        if txt == "体力":
            data["hp"] = parse_v(nxt)
        elif txt == "攻撃力":
            data["atk"] = parse_v(nxt)
        elif "DPS" in txt:
            data["dps"] = parse_v(nxt)
        elif txt == "射程":
            data["range"] = parse_v(nxt)
        elif txt == "速度":
            data["speed"] = parse_v(nxt)
        elif "攻撃発生" in txt:
            data["atk_start"] = parse_v(nxt)
        elif "攻撃頻度" in txt:
            data["atk_freq"] = parse_v(nxt)

        if "単体" in txt or "範囲" in txt:
            data["target"] = "単体" if "単体" in txt else "範囲"

    if data["hp"] == "---":
        return None

    # 特性抽出（味方版と同じ：アイコン画像(icon_s)区切りのテキストチャンクを取得）
    for el in all_tds:
        if not el.find("img", class_="icon_s"):
            continue
        temp_td = copy.copy(el)
        for hidden in temp_td.find_all(True, class_=re.compile(r"hide")):
            hidden.decompose()

        current_chunk = ""
        for child in temp_td.children:
            if child.name == "img" and child.has_attr('class') and 'icon_s' in child['class']:
                if current_chunk.strip():
                    clean_text = current_chunk.replace("▼", "").replace("▲", "").strip()
                    if clean_text:
                        data["abilities"].append(clean_text)
                current_chunk = ""
            elif isinstance(child, str):
                current_chunk += child
            elif hasattr(child, 'get_text'):
                current_chunk += child.get_text(strip=False)

        if current_chunk.strip():
            clean_text = current_chunk.replace("▼", "").replace("▲", "").strip()
            if clean_text:
                data["abilities"].append(clean_text)

    unique_abilities = []
    for ab in data["abilities"]:
        if ab not in unique_abilities:
            unique_abilities.append(ab)
    data["abilities"] = unique_abilities

    return data


def scrape_enemy_detail(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, "html.parser")

        name_tag = soup.find("title")
        if not name_tag or "404" in name_tag.text:
            return None

        full_name = name_tag.text.split("|")[0].replace("敵詳細", "").strip()

        content_area = soup.find("div", id="contents")
        target_area = content_area if content_area else soup

        # コラボ判定（味方版と同じロジック）
        is_collabo = False
        if target_area.find("a", href=re.compile(r"collabo\.html")):
            is_collabo = True

        attributes = detect_attributes(collect_searchable_text(target_area))

        stat_data = get_enemy_stat_data(target_area)
        if not stat_data:
            return {"name": full_name, "is_valid": False}

        return {
            "name": full_name,
            "is_valid": True,
            "is_collabo": is_collabo,
            "attributes": attributes,
            "stats": stat_data,
            "url": url,
        }
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None


def main():
    print("敵データ収集開始...")
    list_url = "https://battlecats-db.com/enemy/status_atr_all.html"
    res = requests.get(list_url, headers={"User-Agent": "Mozilla/5.0"})
    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")

    links = []
    for a in soup.find_all("a", href=True):
        if re.search(r's?\d+\.html$', a['href']):
            full_url = "https://battlecats-db.com/enemy/" + a['href'].split("/")[-1]
            if full_url not in links:
                links.append(full_url)

    unique_links = list(dict.fromkeys(links))
    all_enemies = []

    for i, url in enumerate(unique_links[:MAX_ENEMIES]):
        result = scrape_enemy_detail(url)
        if result and result.get("is_valid"):
            all_enemies.append(result)
            status = "[コラボ]" if result["is_collabo"] else "[通常]"
            print(f"[{i+1}/{len(unique_links)}] {status} {result['name']}")
        else:
            name_placeholder = result['name'] if result else url
            print(f"[{i+1}/{len(unique_links)}] スキップ：{name_placeholder}")

        time.sleep(1)

    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_enemies, f, ensure_ascii=False, indent=4)
    print(f"\n✅ 完了！ {len(all_enemies)}体のデータを {JSON_FILE} に保存しました。")


if __name__ == "__main__":
    main()
