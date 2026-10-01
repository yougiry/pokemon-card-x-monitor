import hashlib
import html
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse


VERSION = "3B2-DRY-RUN"

TEST_STATE_FILE = Path("data/state_v3_test.json")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)

SOURCES = [
    {
        "id": "pokemon-card",
        "name": "ポケモンカード公式",
        "type": "pokemon_official",
        "url": "https://www.pokemon-card.com/info/index.html",
        "domain": "pokemon-card.com",
    },
    {
        "id": "geo",
        "name": "GEO",
        "type": "geo",
        "url": "https://geo-online.co.jp/news/",
        "domain": "geo-online.co.jp",
    },
    {
        "id": "sanyodo",
        "name": "三洋堂書店",
        "type": "sanyodo",
        "url": (
            "https://www.sanyodo.co.jp/news/"
            "evt_lottery-sale?tags%5B%5D=5086"
        ),
        "domain": "sanyodo.co.jp",
    },
    {
        "id": "shibuya-tsutaya",
        "name": "SHIBUYA TSUTAYA",
        "type": "tsutaya",
        "url": "https://shibuyatsutaya.tsite.jp/",
        "domain": "shibuyatsutaya.tsite.jp",
    },
]


POKEMON_KEYWORDS = [
    "ポケモンカード",
    "ポケモンカードゲーム",
    "ポケカ",
    "pokémon card",
    "pokemon card",
]


STRONG_SALE_KEYWORDS = [
    ("抽選販売", "抽選"),
    ("抽選受付", "抽選"),
    ("抽選受け付け", "抽選"),
    ("抽選応募", "抽選"),
    ("予約受付", "予約"),
    ("予約販売", "予約"),
    ("予約受け付け", "予約"),
    ("受注販売", "受注"),
    ("招待販売", "招待"),
    ("追加販売", "追加販売"),
    ("再販売", "再販"),
    ("再販", "再販"),
    ("再入荷", "再入荷"),
    ("在庫復活", "在庫復活"),
    ("販売開始", "店頭販売"),
]


EXCLUDE_KEYWORDS = [
    "シティリーグ",
    "チャンピオンズリーグ",
    "ジャパンチャンピオンシップス",
    "pjcs",
    "ジムバトル",
    "トレーナーズリーグ",
    "対戦会",
    "交流会",
]


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
            "Cache-Control": "no-cache",
        },
    )

    with urllib.request.urlopen(
        req,
        timeout=30,
    ) as response:
        raw = response.read()

        charset = (
            response.headers.get_content_charset()
            or "utf-8"
        )

        try:
            return raw.decode(
                charset,
                errors="replace",
            )
        except LookupError:
            return raw.decode(
                "utf-8",
                errors="replace",
            )


def clean_text(value):
    value = re.sub(
        r"<script\b.*?</script>",
        " ",
        value,
        flags=re.I | re.S,
    )

    value = re.sub(
        r"<style\b.*?</style>",
        " ",
        value,
        flags=re.I | re.S,
    )

    value = re.sub(
        r"<!--.*?-->",
        " ",
        value,
        flags=re.S,
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


def same_domain(url, domain):
    host = urlparse(url).netloc.lower()

    return (
        host == domain
        or host.endswith("." + domain)
    )


def contains_pokemon(text):
    lower = text.lower()

    return any(
        keyword.lower() in lower
        for keyword in POKEMON_KEYWORDS
    )


def excluded(text):
    lower = text.lower()

    return any(
        keyword.lower() in lower
        for keyword in EXCLUDE_KEYWORDS
    )


def detect_category(text):
    for keyword, category in STRONG_SALE_KEYWORDS:
        if keyword in text:
            return category

    return None


def article_url_allowed(source, url):
    parsed = urlparse(url)
    path = parsed.path

    if not same_domain(
        url,
        source["domain"],
    ):
        # ポケカ公式からポケセン公式へのリンクは許可
        if (
            source["type"] == "pokemon_official"
            and "pokemoncenter-online.com"
            in parsed.netloc.lower()
        ):
            return True

        return False

    if source["type"] == "geo":
        return bool(
            re.fullmatch(
                r"/news/\d+/?",
                path,
            )
        )

    if source["type"] == "sanyodo":
        # タグ/カテゴリ一覧はEvent化しない
        if parsed.query:
            return False

        if path.rstrip("/") in (
            "/news",
            "/news/evt_lottery-sale",
        ):
            return False

        return path.startswith("/news/")

    if source["type"] == "tsutaya":
        return bool(
            re.fullmatch(
                r"/article/\d+\.html",
                path,
            )
        )

    if source["type"] == "pokemon_official":
        return (
            "/info/" in path
            or "pokemoncenter-online.com"
            in parsed.netloc.lower()
        )

    return False


def extract_links(source, page):
    pattern = re.compile(
        r'<a\b[^>]*href\s*=\s*'
        r'["\']([^"\']+)["\'][^>]*>'
        r'(.*?)</a>',
        flags=re.I | re.S,
    )

    results = {}

    for href, body in pattern.findall(page):
        title = clean_text(body)

        if not title:
            continue

        url = urljoin(
            source["url"],
            html.unescape(href),
        )

        if not url.startswith(
            ("https://", "http://")
        ):
            continue

        if not article_url_allowed(
            source,
            url,
        ):
            continue

        # utm等をEvent IDに影響させない
        parsed = urlparse(url)

        canonical = (
            f"{parsed.scheme}://"
            f"{parsed.netloc}"
            f"{parsed.path}"
        )

        if parsed.query and (
            "pokemoncenter-online.com"
            in parsed.netloc.lower()
        ):
            canonical += "?" + parsed.query

        results[canonical] = {
            "title": title,
            "url": canonical,
        }

    return list(results.values())


def extract_price(text):
    patterns = [
        r"(?:販売価格|価格|税込価格|希望小売価格)"
        r"[\s：:]*"
        r"([0-9]{1,3}(?:,[0-9]{3})+円)",

        r"(?:販売価格|価格|税込価格)"
        r"[\s：:]*"
        r"([0-9]{3,6}円)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
        )

        if match:
            return match.group(1)

    return None


def extract_period(text):
    result = {
        "application_start": None,
        "application_end": None,
    }

    # 2026年10月2日(金) 12:00 のような形式
    date = (
        r"\d{4}年"
        r"\d{1,2}月"
        r"\d{1,2}日"
        r"(?:\([^)]+\))?"
        r"(?:\s*"
        r"\d{1,2}"
        r"[:時]"
        r"\d{0,2}"
        r"分?"
        r")?"
    )

    patterns = [
        rf"(?:応募期間|受付期間|抽選期間|応募受付)"
        rf"[^0-9]{{0,50}}"
        rf"({date})"
        rf"\s*[～〜~\-]\s*"
        rf"({date})",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
        )

        if match:
            result["application_start"] = (
                match.group(1)
            )

            result["application_end"] = (
                match.group(2)
            )

            break

    return result


def make_event(
    source,
    item,
    detail_text,
    detail_status,
):
    combined = (
        item["title"]
        + " "
        + detail_text
    )

    # 本文取得成功時は本文にポケカ情報が必要
    # 403時は一覧タイトルをfallbackとして使う
    if detail_text:
        if not contains_pokemon(combined):
            return None
    else:
        if not contains_pokemon(item["title"]):
            # ポケセンリンクについては
            # 「ポケモンセンターオンライン」の販売告知を許可
            if not (
                "pokemoncenter-online.com"
                in item["url"]
                and detect_category(
                    item["title"]
                )
            ):
                return None

    if excluded(combined):
        return None

    category = detect_category(
        combined
    )

    if not category:
        return None

    retailer = source["name"]

    if (
        "pokemoncenter-online.com"
        in item["url"]
    ):
        retailer = (
            "ポケモンセンターオンライン"
        )

    periods = extract_period(
        detail_text
    )

    event_id = hashlib.sha256(
        (
            retailer
            + "|"
            + item["url"]
        ).encode("utf-8")
    ).hexdigest()[:24]

    event = {
        "id": event_id,
        "product_name": item["title"],
        "retailer": retailer,
        "category": category,
        "application_start": (
            periods["application_start"]
        ),
        "application_end": (
            periods["application_end"]
        ),
        "sale_datetime": None,
        "price": (
            extract_price(detail_text)
            if detail_text
            else None
        ),
        "conditions": None,
        "official_url": item["url"],
        "source_url": source["url"],
        "verified": True,
        "detail_status": detail_status,
    }

    fingerprint_data = json.dumps(
        event,
        ensure_ascii=False,
        sort_keys=True,
    )

    event["fingerprint"] = (
        hashlib.sha256(
            fingerprint_data.encode(
                "utf-8"
            )
        ).hexdigest()
    )

    return event


def inspect_item(source, item):
    try:
        page = fetch(item["url"])

        text = clean_text(page)

        return make_event(
            source,
            item,
            text,
            "fetched",
        )

    except urllib.error.HTTPError as exc:
        print(
            f"  HTTP {exc.code}: "
            f"{item['url']}"
        )

        return make_event(
            source,
            item,
            "",
            f"http_{exc.code}",
        )

    except Exception as exc:
        print(
            f"  ERROR {type(exc).__name__}: "
            f"{item['url']}"
        )

        return None


def scan_source(source):
    print()
    print("=" * 72)
    print(
        f"Checking {source['name']}"
    )

    page = fetch(
        source["url"]
    )

    links = extract_links(
        source,
        page,
    )

    print(
        f"Article links: {len(links)}"
    )

    events = []

    # テストなので負荷を抑える
    for item in links[:30]:
        event = inspect_item(
            source,
            item,
        )

        if event:
            events.append(event)

    print(
        f"Verified sale events: "
        f"{len(events)}"
    )

    return events


def load_test_state():
    if not TEST_STATE_FILE.exists():
        return {
            "version": 3,
            "initialized": False,
            "events": {},
            "pending": {},
            "posted": {},
        }

    with TEST_STATE_FILE.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def build_preview(event):
    lines = [
        f"【ポケカ{event['category']}】",
        "",
        event["product_name"],
        f"販売店：{event['retailer']}",
    ]

    if event.get("price"):
        lines.append(
            f"価格：{event['price']}"
        )

    if event.get(
        "application_start"
    ):
        lines.append(
            "受付開始："
            + event["application_start"]
        )

    if event.get(
        "application_end"
    ):
        lines.append(
            "締切："
            + event["application_end"]
        )

    lines.extend(
        [
            "",
            "▼公式",
            event["official_url"],
            "",
            "#ポケカ #ポケモンカード",
        ]
    )

    return "\n".join(lines)


def main():
    print(
        f"Pokemon Card Monitor "
        f"{VERSION}"
    )

    print(
        "DRY RUN: X/Buffer投稿なし"
    )

    print(
        "DRY RUN: 本番state.json変更なし"
    )

    state = load_test_state()

    current = {}

    for source in SOURCES:
        try:
            events = scan_source(
                source
            )

            for event in events:
                current[
                    event["id"]
                ] = event

        except Exception as exc:
            print(
                f"SOURCE ERROR "
                f"{source['name']}: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

    print()
    print("=" * 72)
    print(
        f"TOTAL VERIFIED EVENTS: "
        f"{len(current)}"
    )

    old_events = state.get(
        "events",
        {},
    )

    new_or_changed = []

    for event_id, event in (
        current.items()
    ):
        old = old_events.get(
            event_id
        )

        if (
            not old
            or old.get("fingerprint")
            != event["fingerprint"]
        ):
            new_or_changed.append(
                event
            )

    print(
        f"NEW/CHANGED: "
        f"{len(new_or_changed)}"
    )

    # 初回はbaseline扱い。
    # Xには絶対送らない。
    if not state.get(
        "initialized"
    ):
        print()
        print(
            "FIRST V3 TEST RUN "
            "- BASELINE ONLY"
        )

        preview_events = list(
            current.values()
        )

    else:
        preview_events = (
            new_or_changed
        )

    for event in preview_events:
        print()
        print("-" * 72)
        print(build_preview(event))
        print(
            f"DETAIL STATUS: "
            f"{event['detail_status']}"
        )

    # TEST stateだけ更新
    TEST_STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    test_state = {
        "version": 3,
        "initialized": True,
        "updated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "events": current,
        "pending": {},
        "posted": state.get(
            "posted",
            {},
        ),
    }

    with TEST_STATE_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            test_state,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print(
        "V3-B2 DRY RUN completed."
    )


if __name__ == "__main__":
    main()
