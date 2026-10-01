import hashlib
import html
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse


VERSION = "3C1-QUEUE-DRY-RUN"

TEST_STATE_FILE = Path("data/state_v3_test.json")

# キュー動作確認のため一時的に1件。

# 本番では3に変更する。

MAX_POSTS_PER_RUN = 1
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
    ("受注販売", "受注"),
    ("招待販売", "招待"),
    ("追加販売", "追加販売"),
    ("再販売", "再販"),
    ("再販", "再販"),
    ("再入荷", "再入荷"),
    ("在庫復活", "在庫復活"),
    ("販売開始", "販売"),
]

EXCLUDE_TITLE_KEYWORDS = [
    "よくあるお問い合わせ",
    "よくあるご質問",
    "プライバシーポリシー",
    "なりすまし",
    "ponta",
    "障害",
    "メンテナンス",
    "営業時間",
    "貸切営業",
    "weekly event calendar",
]

TOURNAMENT_KEYWORDS = [
    "シティリーグ",
    "チャンピオンズリーグ",
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
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"

        try:
            return raw.decode(charset, errors="replace")
        except LookupError:
            return raw.decode("utf-8", errors="replace")


def clean_text(value):
    value = re.sub(
        r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->",
        " ",
        value,
        flags=re.I | re.S,
    )
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_title(title):
    title = clean_text(title)

    title = re.sub(
        r"^\s*(?:その他|ニュース|お知らせ)\s+",
        "",
        title,
    )

    title = re.sub(
        r"\s*\(外部リンク\)\s*",
        " ",
        title,
        flags=re.I,
    )

    title = re.sub(
        r"^\d{4}[./年]\d{1,2}[./月]\d{1,2}日?\s*",
        "",
        title,
    )

    title = re.sub(
        r"\s+\d{4}\.\d{1,2}\.\d{1,2}\s*$",
        "",
        title,
    )

    return re.sub(r"\s+", " ", title).strip()


def contains_pokemon(text):
    lower = text.lower()
    return any(k.lower() in lower for k in POKEMON_KEYWORDS)


def detect_category(text):
    lower = text.lower()

    for keyword, category in STRONG_SALE_KEYWORDS:
        if keyword.lower() in lower:
            return category

    return None


def title_excluded(title):
    lower = title.lower()

    if any(k.lower() in lower for k in EXCLUDE_TITLE_KEYWORDS):
        return True

    if any(k.lower() in lower for k in TOURNAMENT_KEYWORDS):
        return True

    return False


def title_is_sale_candidate(title):
    """
    最重要:
    本文全体ではなく、まず記事タイトルそのものを判定する。
    """
    title = normalize_title(title)

    if title_excluded(title):
        return False

    if not contains_pokemon(title):
        return False

    if not detect_category(title):
        return False

    return True


def same_domain(url, domain):
    host = urlparse(url).netloc.lower()
    return host == domain or host.endswith("." + domain)


def canonical_url(url):
    parsed = urlparse(url)

    result = (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
        f"{parsed.path}"
    )

    # ポケセンは ?id= が記事識別子なので残す
    if "pokemoncenter-online.com" in parsed.netloc.lower():
        if parsed.query:
            result += "?" + parsed.query

    return result


def article_url_allowed(source, url):
    parsed = urlparse(url)
    path = parsed.path

    if source["type"] == "pokemon_official":
        if same_domain(url, source["domain"]):
            return "/info/" in path

        return "pokemoncenter-online.com" in parsed.netloc.lower()

    if not same_domain(url, source["domain"]):
        return False

    if source["type"] == "geo":
        return bool(re.fullmatch(r"/news/\d+/?", path))

    if source["type"] == "tsutaya":
        return bool(re.fullmatch(r"/article/\d+\.html", path))

    if source["type"] == "sanyodo":
        # B3では診断を優先。
        # query付きタグ/カテゴリページ自体はEvent化しない。
        if parsed.query:
            return False

        return (
            path.startswith("/news/")
            and path.rstrip("/") != "/news"
        )

    return False


def extract_all_links(source, page):
    pattern = re.compile(
        r'<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        flags=re.I | re.S,
    )

    results = {}

    for href, body in pattern.findall(page):
        title = clean_text(body)

        if not title:
            continue

        url = urljoin(source["url"], html.unescape(href))

        if not url.startswith(("https://", "http://")):
            continue

        if not same_domain(url, source["domain"]):
            if not (
                source["type"] == "pokemon_official"
                and "pokemoncenter-online.com"
                in urlparse(url).netloc.lower()
            ):
                continue

        key = canonical_url(url)

        results[key] = {
            "title": title,
            "url": key,
            "raw_url": url,
        }

    return list(results.values())


def extract_article_links(source, page):
    all_links = extract_all_links(source, page)

    return [
        item
        for item in all_links
        if article_url_allowed(source, item["url"])
    ]


def print_sanyodo_diagnostics(source, page):
    """
    三洋堂だけ記事URL構造が未確定なので、
    ポケカ/抽選/販売を含むリンクをログに出す。
    """
    print("SANYODO URL DIAGNOSTICS:")

    matches = []

    for item in extract_all_links(source, page):
        text = item["title"].lower()

        if (
            contains_pokemon(text)
            or "抽選" in text
            or "販売" in text
            or "予約" in text
        ):
            matches.append(item)

    for item in matches[:30]:
        print(f"  TITLE: {item['title'][:120]}")
        print(f"  HREF : {item['raw_url']}")

    print(f"SANYODO DIAGNOSTIC LINKS: {len(matches)}")


def extract_price(text):
    patterns = [
        (
            r"(?:販売価格|税込価格|希望小売価格|価格)"
            r"[\s：:]*"
            r"([0-9]{1,3}(?:,[0-9]{3})+円)"
        ),
        (
            r"(?:販売価格|税込価格|価格)"
            r"[\s：:]*"
            r"([0-9]{3,6}円)"
        ),
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            return match.group(1)

    return None


def extract_period(text):
    result = {
        "application_start": None,
        "application_end": None,
    }

    date = (
        r"\d{4}年\d{1,2}月\d{1,2}日"
        r"(?:\([^)]+\))?"
        r"(?:\s*\d{1,2}[:時]\d{0,2}分?)?"
    )

    patterns = [
        (
            rf"(?:応募期間|受付期間|抽選期間|応募受付)"
            rf"[^0-9]{{0,80}}"
            rf"({date})"
            rf"\s*[～〜~\-]\s*"
            rf"({date})"
        ),
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            result["application_start"] = match.group(1)
            result["application_end"] = match.group(2)
            break

    return result


def make_event(source, item, detail_text, detail_status):
    title = normalize_title(item["title"])

    # B3の核心。
    # 一覧に表示された記事タイトル自体が
    # ポケカ販売案件でなければ本文を理由に昇格させない。
    if not title_is_sale_candidate(title):
        return None

    category = detect_category(title)

    retailer = source["name"]

    if "pokemoncenter-online.com" in item["url"]:
        retailer = "ポケモンセンターオンライン"

    periods = extract_period(detail_text)

    event_id = hashlib.sha256(
        (retailer + "|" + item["url"]).encode("utf-8")
    ).hexdigest()[:24]

    event = {
        "id": event_id,
        "product_name": title,
        "retailer": retailer,
        "category": category,
        "application_start": periods["application_start"],
        "application_end": periods["application_end"],
        "sale_datetime": None,
        "price": extract_price(detail_text) if detail_text else None,
        "conditions": None,
        "official_url": item["url"],
        "source_url": source["url"],
        "status": "unknown",
        "verified": True,
        "detail_status": detail_status,
    }

    fingerprint_source = json.dumps(
        event,
        ensure_ascii=False,
        sort_keys=True,
    )

    event["fingerprint"] = hashlib.sha256(
        fingerprint_source.encode("utf-8")
    ).hexdigest()

    return event


def inspect_item(source, item):
    # タイトル段階で落とす。
    # 不要な詳細ページへのアクセスも削減できる。
    if not title_is_sale_candidate(item["title"]):
        return None

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
        print(f"  HTTP {exc.code}: {item['url']}")

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
    print(f"Checking {source['name']}")

    page = fetch(source["url"])

    if source["type"] == "sanyodo":
        print_sanyodo_diagnostics(source, page)

    links = extract_article_links(source, page)

    print(f"Article links: {len(links)}")

    title_candidates = [
        item
        for item in links
        if title_is_sale_candidate(item["title"])
    ]

    print(
        f"Title-qualified candidates: "
        f"{len(title_candidates)}"
    )

    events = []

    for item in title_candidates[:30]:
        event = inspect_item(source, item)

        if event:
            events.append(event)

    print(f"Verified sale events: {len(events)}")

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

    with TEST_STATE_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def build_preview(event):
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

    if event.get("application_start"):
        lines.append(
            "受付開始："
            + event["application_start"]
        )

    if event.get("application_end"):
        lines.append(
            "締切："
            + event["application_end"]
        )

    lines.extend([
        "",
        "▼公式",
        event["official_url"],
        "",
        "#ポケカ #ポケモンカード",
    ])

    return "\n".join(lines)
    def queue_new_or_changed(state, current):
        """
    新規または内容変更されたEventをpendingへ入れる。

    postedに同じfingerprintが存在する場合は再投入しない。
    pendingに同じfingerprintが既に存在する場合も重複させない。
    """

    pending = state.setdefault("pending", {})
    posted = state.setdefault("posted", {})
    old_events = state.get("events", {})

    added = []

    for event_id, event in current.items():
        old = old_events.get(event_id)

        changed = (
            old is None
            or old.get("fingerprint")
            != event["fingerprint"]
        )

        if not changed:
            continue

        fingerprint = event["fingerprint"]

        posted_record = posted.get(event_id)

        if (
            posted_record
            and posted_record.get("fingerprint")
            == fingerprint
        ):
            continue

        pending_record = pending.get(event_id)

        if (
            pending_record
            and pending_record.get("fingerprint")
            == fingerprint
        ):
            continue

        pending[event_id] = {
            "event": event,
            "fingerprint": fingerprint,
            "queued_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "reason": (
                "new"
                if old is None
                else "changed"
            ),
        }

        added.append(event_id)

    return added


def simulate_pending_posts(state):
    """
    Bufferには送らない。

    pendingから最大MAX_POSTS_PER_RUN件を
    投稿したものとしてpostedへ移動する。
    """

    pending = state.setdefault(
        "pending",
        {},
    )

    posted = state.setdefault(
        "posted",
        {},
    )

    queue = list(
        pending.items()
    )

    selected = queue[
        :MAX_POSTS_PER_RUN
    ]

    simulated = []

    for event_id, record in selected:
        event = record["event"]

        print()
        print("=" * 72)
        print("WOULD POST TO X")
        print("=" * 72)
        print(build_preview(event))

        posted[event_id] = {
            "fingerprint": (
                record["fingerprint"]
            ),
            "posted_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "mode": "dry_run_simulation",
        }

        simulated.append(
            event_id
        )

    for event_id in simulated:
        pending.pop(
            event_id,
            None,
        )

    return simulated
    
    lines = [
        f"【ポケカ{event['category']}】",
        "",
        event["product_name"],
        f"販売店：{event['retailer']}",
    ]

    if event.get("price"):
        lines.append(f"価格：{event['price']}")

    if event.get("application_start"):
        lines.append(
            "受付開始：" + event["application_start"]
        )

    if event.get("application_end"):
        lines.append(
            "締切：" + event["application_end"]
        )

    lines.extend([
        "",
        "▼公式",
        event["official_url"],
        "",
        "#ポケカ #ポケモンカード",
    ])

    return "\n".join(lines)

def queue_new_or_changed(state, current):
    pending = state.setdefault("pending", {})
    posted = state.setdefault("posted", {})
    old_events = state.get("events", {})

    added = []

    for event_id, event in current.items():
        old = old_events.get(event_id)

        changed = (
            old is None
            or old.get("fingerprint") != event["fingerprint"]
        )

        if not changed:
            continue

        fingerprint = event["fingerprint"]

        posted_record = posted.get(event_id)

        if (
            posted_record
            and posted_record.get("fingerprint") == fingerprint
        ):
            continue

        pending_record = pending.get(event_id)

        if (
            pending_record
            and pending_record.get("fingerprint") == fingerprint
        ):
            continue

        pending[event_id] = {
            "event": event,
            "fingerprint": fingerprint,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "reason": "new" if old is None else "changed",
        }

        added.append(event_id)

    return added


def simulate_pending_posts(state):
    pending = state.setdefault("pending", {})
    posted = state.setdefault("posted", {})

    selected = list(pending.items())[:MAX_POSTS_PER_RUN]

    simulated = []

    for event_id, record in selected:
        event = record["event"]

        print()
        print("=" * 72)
        print("WOULD POST TO X")
        print("=" * 72)
        print(build_preview(event))

        posted[event_id] = {
            "fingerprint": record["fingerprint"],
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "mode": "dry_run_simulation",
        }

        simulated.append(event_id)

    for event_id in simulated:
        pending.pop(event_id, None)

    return simulated

def main():
    print(
        f"Pokemon Card Monitor "
        f"{VERSION}"
    )

    print(
        "DRY RUN: Buffer/X投稿なし"
    )

    print(
        "DRY RUN: 本番state.json変更なし"
    )

    print(
        f"MAX_POSTS_PER_RUN="
        f"{MAX_POSTS_PER_RUN}"
    )

    state = load_test_state()

    state.setdefault(
        "events",
        {},
    )

    state.setdefault(
        "pending",
        {},
    )

    state.setdefault(
        "posted",
        {},
    )

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

    added = queue_new_or_changed(
        state,
        current,
    )

    print(
        f"ADDED TO PENDING: "
        f"{len(added)}"
    )

    print(
        f"PENDING BEFORE POST: "
        f"{len(state['pending'])}"
    )

    simulated = simulate_pending_posts(
        state
    )

    print()
    print(
        f"WOULD POST COUNT: "
        f"{len(simulated)}"
    )

    print(
        f"REMAINING PENDING: "
        f"{len(state['pending'])}"
    )

    # 現在確認できたEventを最後に保存する
    state["events"] = current

    state["version"] = 3
    state["initialized"] = True

    state["updated_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    TEST_STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with TEST_STATE_FILE.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print(
        "V3-C1 QUEUE DRY RUN completed."
    )


if __name__ == "__main__":
    main()
