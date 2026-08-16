import requests
from bs4 import BeautifulSoup
import re
import time
import json
import copy

MAX_UNITS = 1200
JSON_FILE = 'nyanko_encyclopedia.json'

def parse_v(node):
    if not node: return "---"
    temp_node = copy.copy(node)
    # 非表示設定（hideクラス）の数値を削除して、現在のレベルの数値のみ抽出
    for hidden in temp_node.find_all(True, class_=re.compile(r"hide")):
        hidden.decompose()
    text = temp_node.get_text(strip=True)
    # 数値（カンマ含む）を抽出
    match = re.search(r'[\d,]+', text)
    return match.group(0).replace(',', '') if match else "---"

def get_form_data(elements):
    data = {
        "hp": "---", "atk": "---", "dps": "---", 
        "range": "---", "speed": "---", "cost": "---", 
        "recharge": "---", "target": "---", 
        "atk_freq": "---", "atk_start": "---",
        "abilities": []
    }
    
    if not elements: return None

    all_tds = []
    for el in elements:
        if el.name == "td":
            if el.has_attr('class') and 'kai' in el['class']: continue
            all_tds.append(el)
        elif hasattr(el, "find_all"):
            for sub_td in el.find_all("td"):
                if sub_td.has_attr('class') and 'kai' in sub_td['class']: continue
                all_tds.append(sub_td)

    for i, td in enumerate(all_tds):
        txt = td.get_text(strip=True)
        if i + 1 >= len(all_tds): break
        nxt = all_tds[i+1]
        
        # 項目名の判定（コストの判定を強化）
        if txt == "体力": data["hp"] = parse_v(nxt)
        elif txt == "攻撃力": data["atk"] = parse_v(nxt)
        elif "DPS" in txt: data["dps"] = parse_v(nxt)
        elif txt == "射程": data["range"] = parse_v(nxt)
        elif txt == "速度": data["speed"] = parse_v(nxt)
        elif "コスト" in txt: # 「コスト(1章)」などに対応
            val = parse_v(nxt)
            if val != "---": data["cost"] = val
        elif "再生産" in txt: data["recharge"] = parse_v(nxt)
        elif "攻撃発生" in txt: data["atk_start"] = parse_v(nxt)
        elif "攻撃頻度" in txt: data["atk_freq"] = parse_v(nxt)
        
        if "単体" in txt or "範囲" in txt:
            data["target"] = "単体" if "単体" in txt else "範囲"

    # 体力すら取れない場合は、その形態データ自体が無効と判断
    if data["hp"] == "---": return None

    # 特性抽出
    for el in elements:
        if el.name == "td":
            if el.has_attr('class') and 'kai' in el['class']: continue
            if "にゃんコンボ" in el.get_text(): continue
            if not el.find("img", class_="icon_s"): continue

            temp_td = copy.copy(el)
            for hidden in temp_td.find_all(True, class_=re.compile(r"hide")):
                hidden.decompose()
            
            current_chunk = ""
            for child in temp_td.children:
                if child.name == "img" and child.has_attr('class') and 'icon_s' in child['class']:
                    if current_chunk.strip():
                        clean_text = current_chunk.replace("▼", "").replace("▲", "").strip()
                        if clean_text: data["abilities"].append(clean_text)
                    current_chunk = ""
                elif isinstance(child, str):
                    current_chunk += child
                elif hasattr(child, 'get_text'):
                    current_chunk += child.get_text(strip=False)
            
            if current_chunk.strip():
                clean_text = current_chunk.replace("▼", "").replace("▲", "").strip()
                if clean_text: data["abilities"].append(clean_text)

    unique_abilities = []
    for ab in data["abilities"]:
        if ab not in unique_abilities:
            unique_abilities.append(ab)
    data["abilities"] = unique_abilities
    
    return data

# レアリティの表記（長い名称から先に判定：「激レア」等が「レア」の部分一致にならないように）
RARITY_LABELS = ["伝説レア", "超激レア", "激レア", "レア", "EX", "基本"]


def get_rarity(soup, content_area):
    """ページ内テキストからレアリティ表記を探すベストエフォート実装。
    サイト構造の変更や取得失敗時は None を返す（呼び出し側で "不明" 等の扱いにする）。"""
    text_area = content_area if content_area else soup
    full_text = text_area.get_text()
    for label in RARITY_LABELS:
        if label in full_text:
            return label
    return None


def scrape_unit_detail(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, "html.parser")
        
        name_tag = soup.find("title")
        if not name_tag or "404" in name_tag.text: return None
        
        full_name = name_tag.text.split("|")[0].replace("味方詳細", "").strip()

        # コラボ判定（contents内限定）
        is_collabo = False
        content_area = soup.find("div", id="contents")
        if content_area and content_area.find("a", href=re.compile(r"collabo\.html")):
            is_collabo = True

        rarity = get_rarity(soup, content_area)
        
        form_ranges = {"-1": [], "-2": [], "-3": [], "-4": []}
        current_key = None
        target_area = content_area if content_area else soup
        for el in target_area.descendants:
            if isinstance(el, str) and "No." in el and "-" in el:
                if "-1" in el: current_key = "-1"
                elif "-2" in el: current_key = "-2"
                elif "-3" in el: current_key = "-3"
                elif "-4" in el: current_key = "-4"
            if current_key and el.name:
                form_ranges[current_key].append(el)
        
        f1 = get_form_data(form_ranges["-1"])
        if not f1:
            return {"name": full_name, "is_valid": False}

        return {
            "name": full_name, "is_valid": True, "is_collabo": is_collabo,
            "rarity": rarity,
            "form1": f1, "form2": get_form_data(form_ranges["-2"]),
            "form3": get_form_data(form_ranges["-3"]), "form4": get_form_data(form_ranges["-4"]),
            "url": url
        }
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None

def main():
    print("データ収集開始（コスト取得強化版）...")
    list_url = "https://battlecats-db.com/unit/status_r_all.html"
    res = requests.get(list_url)
    res.encoding = res.apparent_encoding
    soup = BeautifulSoup(res.text, "html.parser")
    
    links = []
    for a in soup.find_all("a", href=True):
        if re.search(r's?\d+\.html$', a['href']):
            full_url = "https://battlecats-db.com/unit/" + a['href'].split("/")[-1]
            if full_url not in links: links.append(full_url)
    
    unique_links = list(dict.fromkeys(links))
    all_units = []
    
    for i, url in enumerate(unique_links[:MAX_UNITS]):
        result = scrape_unit_detail(url)
        if result and result.get("is_valid"):
            all_units.append(result)
            status = "[コラボ]" if result["is_collabo"] else "[通常]"
            print(f"[{i+1}/{len(unique_links)}] {status} {result['name']}")
        else:
            name_placeholder = result['name'] if result else url
            print(f"[{i+1}/{len(unique_links)}] スキップ：{name_placeholder}")
        
        # サーバー負荷軽減
        time.sleep(1)
        
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_units, f, ensure_ascii=False, indent=4)
    print(f"\n✅ 完了！")

if __name__ == "__main__":
    main()