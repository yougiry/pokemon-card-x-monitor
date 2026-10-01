import hashlib
import html
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse


# ============================================================
# V3-A TEST / DRY RUN
# ============================================================

VERSION = "3A-DRY-RUN"

SOURCES = [
    {
        "id": "pokemon-card-news",
        "name": "ポケモンカード公式",
        "url": "https://www.pokemon-card.com/info/index.html",
    }
]

SALE_KEYWORDS = [
    "抽選販売",
    "予約販売",
    "受注販売",
    "招待販売",
    "追加販売",
    "再販売",
    "再販",
    "再入荷",
    "在庫",
    "販売開始",
    "販売方法",
    "商品の抽選",
    "商品抽選",
    "ポケモンセンターオンライン",
]

EXCLUDE_KEYWORDS = [
    "シティリーグ",
    "チャンピオンズリーグ",
    "ジャパンチャンピオンシップス",
    "PJCS",
    "大会",
    "エントリー",
    "イベント参加",
    "プレイヤーズクラブ",
]

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; pokemon-card-x-monitor/3.0; "
    "+https://github.com/yougiry/pokemon-card-x-monitor)"
)


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode(
            "utf-8",
            errors="replace",
        )


def clean_text(value):
    value = re.sub(
        r"<script.*?</script>",
        " ",
        value,
        flags=re.I | re.S,
    )

    value = re.sub(
        r"<style.*?</style>",
        " ",
        value,
        flags=re.I | re.S,
    )

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = html.unescape(value)

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def is_sale_candidate(title):
    if not title:
        return False

    lower = title.lower()

    if any(
        word.lower() in lower
        for word in EXCLUDE_KEYWORDS
    ):
        return False

    return any(
        word.lower() in lower
        for word in SALE_KEYWORDS
    )


def extract_candidates(source, page):
    links = re.findall(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>'
        r'(.*?)</a>',
        page,
        flags=re.I | re.S,
    )

    results = {}

    for href, body in links:
        title = clean_text(body)

        if not is_sale_candidate(title):
            continue

        url = urljoin(
            source["url"],
            href,
        ).strip()

        if not (
            "pokemon-card.com" in url
            or "pokemoncenter-online.com" in url
        ):
            continue

        event_id = hashlib.sha256(
            f'{source["id"]}|{url}'.encode("utf-8")
        ).hexdigest()[:24]

        results[event_id] = {
            "id": event_id,
            "source": source["name"],
            "title": title,
            "url": url,
        }

    return list(results.values())


def detect_retailer(url):
    host = urlparse(url).netloc.lower()

    if "pokemoncenter-online.com" in host:
        return "ポケモンセンターオンライン"

    if "pokemon-card.com" in host:
        return "ポケモンカード公式"

    return host


def detect_sale_type(text):
    checks = [
        ("抽選", "抽選販売"),
        ("予約", "予約販売"),
        ("受注", "受注販売"),
        ("招待", "招待販売"),
        ("追加販売", "追加販売"),
        ("再販売", "再販売"),
        ("再販", "再販売"),
        ("再入荷", "再入荷"),
        ("在庫", "在庫情報"),
    ]

    for keyword, label in checks:
        if keyword in text:
            return label

    return "販売情報"


def extract_price(text):
    patterns = [
        r"(?:販売価格|価格|税込価格|希望小売価格)"
        r"[\s：:]*"
        r"([0-9]{1,3}(?:,[0-9]{3})+円)",
        r"(?:販売価格|価格|税込価格|希望小売価格)"
        r"[\s：:]*"
        r"([0-9]{3,6}円)",
        r"([0-9]{1,3}(?:,[0-9]{3})+円)"
        r"(?:\s*\(税込\))",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            return match.group(1)

    return None


def normalize_datetime(value):
    value = value.strip()

    value = value.replace("年", "/")
    value = value.replace("月", "/")
    value = value.replace("日", " ")

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def extract_periods(text):
    result = {
        "application_start": None,
        "application_end": None,
        "result_date": None,
        "purchase_end": None,
    }

    date_time = (
        r"\d{4}年\d{1,2}月\d{1,2}日"
        r"(?:\([^)]+\))?"
        r"(?:\s*\d{1,2}時\d{0,2}分?)?"
    )

    # 応募・受付期間
    period_patterns = [
        rf"(?:応募期間|抽選応募期間|受付期間)"
        rf"[^0-9]{{0,30}}"
        rf"({date_time})"
        rf"\s*[～〜~-]\s*"
        rf"({date_time})",

        rf"(?:応募受付|抽選受付)"
        rf"[^0-9]{{0,30}}"
        rf"({date_time})"
        rf"\s*[～〜~-]\s*"
        rf"({date_time})",
    ]

    for pattern in period_patterns:
        match = re.search(pattern, text)

        if match:
            result["application_start"] = (
                normalize_datetime(match.group(1))
            )
            result["application_end"] = (
                normalize_datetime(match.group(2))
            )
            break

    # 当選発表
    result_patterns = [
        rf"(?:抽選結果発表|当選発表|結果発表)"
        rf"[^0-9]{{0,30}}"
        rf"({date_time})",
    ]

    for pattern in result_patterns:
        match = re.search(pattern, text)

        if match:
            result["result_date"] = (
                normalize_datetime(match.group(1))
            )
            break

    # 購入期限
    purchase_patterns = [
        rf"(?:購入期限|購入期間)"
        rf"[^0-9]{{0,30}}"
        rf"(?:{date_time})?"
        rf"\s*[～〜~-]?\s*"
        rf"({date_time})",
    ]

    for pattern in purchase_patterns:
        match = re.search(pattern, text)

        if match:
            result["purchase_end"] = (
                normalize_datetime(match.group(1))
            )
            break

    return result


def extract_product_name(title, text):
    # まずタイトルから不要部分を削る
    name = title

    prefixes = [
        "その他 ",
        "ニュース ",
        "商品 ",
        "イベント ",
    ]

    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]

    # 日付を除去
    name = re.sub(
        r"\s+20\d{2}\.\d{1,2}\.\d{1,2}\s*$",
        "",
        name,
    )

    # 外部リンク表記
    name = name.replace("(外部リンク)", "").strip()

    return name


def analyze_detail(item):
    result = {
        "retailer": detect_retailer(item["url"]),
        "product_name": None,
        "sale_type": detect_sale_type(item["title"]),
        "price": None,
        "application_start": None,
        "application_end": None,
        "result_date": None,
        "purchase_end": None,
        "detail_status": "not_fetched",
    }

    detail_text = ""

    try:
        page = fetch(item["url"])
        detail_text = clean_text(page)

        result["detail_status"] = "fetched"

    except urllib.error.HTTPError as exc:
        result["detail_status"] = (
            f"http_{exc.code}"
        )

        print(
            f"DETAIL HTTP {exc.code}: "
            f"{item['url']}"
        )

    except Exception as exc:
        result["detail_status"] = "error"

        print(
            f"DETAIL ERROR: "
            f"{item['url']} : {exc}"
        )

    combined = (
        item["title"]
        + " "
        + detail_text
    )

    result["product_name"] = (
        extract_product_name(
            item["title"],
            detail_text,
        )
    )

    result["sale_type"] = (
        detect_sale_type(combined)
    )

    if detail_text:
        result["price"] = (
            extract_price(detail_text)
        )

        periods = extract_periods(
            detail_text
        )

        result.update(periods)

    return result


def make_preview(item):
    lines = [
        "----------------------------------------",
        "投稿候補",
        "----------------------------------------",
        f"販売元: {item['retailer']}",
        f"商品/告知: {item['product_name']}",
        f"種別: {item['sale_type']}",
    ]

    if item.get("price"):
        lines.append(
            f"価格: {item['price']}"
        )

    if item.get("application_start"):
        lines.append(
            "応募開始: "
            f"{item['application_start']}"
        )

    if item.get("application_end"):
        lines.append(
            "応募締切: "
            f"{item['application_end']}"
        )

    if item.get("result_date"):
        lines.append(
            "結果発表: "
            f"{item['result_date']}"
        )

    if item.get("purchase_end"):
        lines.append(
            "購入期限: "
            f"{item['purchase_end']}"
        )

    lines.extend(
        [
            f"詳細取得: {item['detail_status']}",
            f"公式: {item['url']}",
        ]
    )

    return "\n".join(lines)


def main():
    print(
        f"Pokemon Card Monitor {VERSION}"
    )

    print(
        "DRY RUN: Buffer/X投稿なし"
    )

    print(
        "DRY RUN: state.json変更なし"
    )

    print()

    all_items = []

    for source in SOURCES:
        print(
            f"Checking {source['name']}"
        )

        page = fetch(source["url"])

        candidates = extract_candidates(
            source,
            page,
        )

        print(
            f"Sale candidates: "
            f"{len(candidates)}"
        )

        for candidate in candidates:
            detail = analyze_detail(
                candidate
            )

            candidate.update(detail)

            all_items.append(candidate)

    print()
    print(
        f"Total sale candidates: "
        f"{len(all_items)}"
    )
    print()

    for item in all_items:
        print(make_preview(item))
        print()

    print(
        "V3-A DRY RUN completed."
    )


if __name__ == "__main__":

    main()
