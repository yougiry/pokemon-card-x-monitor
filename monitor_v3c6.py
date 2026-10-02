
import hashlib
import html
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
JST = ZoneInfo("Asia/Tokyo")
from pathlib import Path
from urllib.parse import urljoin, urlparse


# ============================================================
# Pokemon Card Monitor V3-C1
# Queue DRY RUN
#
# ・Buffer/Xには投稿しない
# ・本番 data/state.json は変更しない
# ・data/state_v3_test.json のみ使用
# ============================================================

VERSION = "3C6-PRODUCTION-CANDIDATE"

TEST_STATE_FILE = Path("data/state_v3_prod.json")

# キュー確認用。
# 本番移行時には3件などへ変更する。
MAX_POSTS_PER_RUN = 1

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)


# ============================================================
# Sources
# ============================================================

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


# ============================================================
# Keywords
# ============================================================

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


# ============================================================
# HTTP
# ============================================================

def fetch(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,"
                "application/xhtml+xml,"
                "*/*;q=0.8"
            ),
            "Accept-Language": (
                "ja,en-US;q=0.7,en;q=0.3"
            ),
        },
    )

    with urllib.request.urlopen(
        request,
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


# ============================================================
# Text utilities
# ============================================================

def clean_text(value):
    if not value:
        return ""

    value = re.sub(
        r"<script\b.*?</script>"
        r"|<style\b.*?</style>"
        r"|<!--.*?-->",
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
        r"^\d{4}[./年]"
        r"\d{1,2}[./月]"
        r"\d{1,2}日?\s*",
        "",
        title,
    )

    title = re.sub(
        r"\s+\d{4}\."
        r"\d{1,2}\."
        r"\d{1,2}\s*$",
        "",
        title,
    )

    return re.sub(
        r"\s+",
        " ",
        title,
    ).strip()


def contains_pokemon(text):
    lower = text.lower()

    return any(
        keyword.lower() in lower
        for keyword in POKEMON_KEYWORDS
    )


def detect_category(text):
    lower = text.lower()

    for keyword, category in STRONG_SALE_KEYWORDS:
        if keyword.lower() in lower:
            return category

    return None


def title_excluded(title):
    lower = title.lower()

    if any(
        keyword.lower() in lower
        for keyword in EXCLUDE_TITLE_KEYWORDS
    ):
        return True

    if any(
        keyword.lower() in lower
        for keyword in TOURNAMENT_KEYWORDS
    ):
        return True

    return False


def title_is_sale_candidate(title):
    title = normalize_title(title)

    if not title:
        return False

    if title_excluded(title):
        return False

    if not contains_pokemon(title):
        return False

    if not detect_category(title):
        return False

    return True


# ============================================================
# URL utilities
# ============================================================

def same_domain(url, domain):
    host = urlparse(url).netloc.lower()

    return (
        host == domain
        or host.endswith("." + domain)
    )


def canonical_url(url):
    parsed = urlparse(url)

    result = (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
        f"{parsed.path}"
    )

    # Pokémon Center Online は
    # ?id= が記事識別子なのでqueryを保持する。
    if (
        "pokemoncenter-online.com"
        in parsed.netloc.lower()
        and parsed.query
    ):
        result += "?" + parsed.query

    return result


def article_url_allowed(source, url):
    parsed = urlparse(url)
    path = parsed.path

    if source["type"] == "pokemon_official":
        if same_domain(
            url,
            source["domain"],
        ):
            return "/info/" in path

        return (
            "pokemoncenter-online.com"
            in parsed.netloc.lower()
        )

    if not same_domain(
        url,
        source["domain"],
    ):
        return False

    if source["type"] == "geo":
        return bool(
            re.fullmatch(
                r"/news/\d+/?",
                path,
            )
        )

    if source["type"] == "tsutaya":
        return bool(
            re.fullmatch(
                r"/article/\d+\.html",
                path,
            )
        )

    if source["type"] == "sanyodo":
        if parsed.query:
            return False

        return (
            path.startswith("/news/")
            and path.rstrip("/") != "/news"
        )

    return False


# ============================================================
# Link extraction
# ============================================================

def extract_all_links(source, page):
    pattern = re.compile(
        r'<a\b[^>]*'
        r'href\s*=\s*["\']([^"\']+)["\']'
        r'[^>]*>(.*?)</a>',
        flags=re.I | re.S,
    )

    results = {}

    for href, body in pattern.findall(page):
        title = clean_text(body)

        if not title:
            continue

        raw_url = urljoin(
            source["url"],
            html.unescape(href),
        )

        if not raw_url.startswith(
            ("https://", "http://")
        ):
            continue

        if not same_domain(
            raw_url,
            source["domain"],
        ):
            is_pokemon_center = (
                source["type"]
                == "pokemon_official"
                and "pokemoncenter-online.com"
                in urlparse(
                    raw_url
                ).netloc.lower()
            )

            if not is_pokemon_center:
                continue

        key = canonical_url(raw_url)

        results[key] = {
            "title": title,
            "url": key,
            "raw_url": raw_url,
        }

    return list(
        results.values()
    )


def extract_article_links(
    source,
    page,
):
    all_links = extract_all_links(
        source,
        page,
    )

    return [
        item
        for item in all_links
        if article_url_allowed(
            source,
            item["url"],
        )
    ]


# ============================================================
# Sanyodo diagnostics
# ============================================================

def print_sanyodo_diagnostics(
    source,
    page,
):
    print(
        "SANYODO URL DIAGNOSTICS:"
    )

    matches = []

    for item in extract_all_links(
        source,
        page,
    ):
        text = item["title"]

        if (
            contains_pokemon(text)
            or "抽選" in text
            or "販売" in text
            or "予約" in text
        ):
            matches.append(item)

    for item in matches[:30]:
        print(
            f"  TITLE: "
            f"{item['title'][:120]}"
        )

        print(
            f"  HREF : "
            f"{item['raw_url']}"
        )

    print(
        "SANYODO DIAGNOSTIC LINKS: "
        f"{len(matches)}"
    )


# ============================================================
# Detail extraction
# ============================================================

def extract_price(text):
    if not text:
        return None

    patterns = [
        (
            r"(?:販売価格|税込価格|"
            r"希望小売価格|価格)"
            r"[\s：:]*"
            r"([0-9]{1,3}"
            r"(?:,[0-9]{3})+円)"
        ),
        (
            r"(?:販売価格|税込価格|価格)"
            r"[\s：:]*"
            r"([0-9]{3,6}円)"
        ),
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
        )

        if match:
            return match.group(1)

    return None


DATE_PATTERN = (
    r"(?:(\d{4})[年/])?"
    r"(\d{1,2})[月/]"
    r"(\d{1,2})日?"
    r"(?:\([^)]+\))?"
    r"(?:\s*"
    r"(\d{1,2})"
    r"(?::|時)"
    r"(\d{1,2})?"
    r"分?"
    r")?"
)

PERIOD_LABELS = [
    "応募期間は",
    "応募期間",
    "応募受付期間",
    "受付期間",
    "抽選受付期間",
    "抽選期間",
    "予約受付期間",
]


def parse_date_groups(groups, default_year):
    year = (
        int(groups[0])
        if groups[0]
        else default_year
    )

    month = int(groups[1])
    day = int(groups[2])

    hour = (
        int(groups[3])
        if groups[3]
        else 0
    )

    minute = (
        int(groups[4])
        if groups[4]
        else 0
    )

    try:
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=JST,
        )
    except ValueError:
        return None


def extract_period(text):
    result = {
        "application_start": None,
        "application_end": None,
    }

    if not text:
        return result

    now = datetime.now(JST)

    for label in PERIOD_LABELS:
        pattern = re.compile(
            re.escape(label)
            + r"[^0-9]{0,80}"
            + r"[「『\"]?\s*"
            + DATE_PATTERN
            + r"\s*"
            + r"(?:～|〜|~|－|-|から)"
            + r"\s*"
            + DATE_PATTERN,
            flags=re.I,
        )

        match = pattern.search(text)

        if not match:
            continue

        groups = match.groups()

        start = parse_date_groups(
            groups[0:5],
            now.year,
        )

        end = parse_date_groups(
            groups[5:10],
            now.year,
        )

        if start:
            result["application_start"] = (
                start.isoformat()
            )

        if end:
            result["application_end"] = (
                end.isoformat()
            )

        return result

    return result


def parse_iso_datetime(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def determine_status(event):
    now = datetime.now(JST)

    start = parse_iso_datetime(
        event.get("application_start")
    )

    end = parse_iso_datetime(
        event.get("application_end")
    )

    if start and end:
        if now < start:
            return "upcoming"

        if start <= now <= end:
            return "open"

        return "closed"

    if end:
        return (
            "open"
            if now <= end
            else "closed"
        )

    if start:
        return (
            "upcoming"
            if now < start
            else "unknown"
        )

    return "unknown"

# ============================================================
# Event
# ============================================================

def make_event(
    source,
    item,
    detail_text,
    detail_status,
):
    title = normalize_title(
        item["title"]
    )

    # 本文にキーワードが存在するだけでは
    # Eventへ昇格させない。
    if not title_is_sale_candidate(
        title
    ):
        return None

    category = detect_category(
        title
    )

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

    event_id_source = (
        retailer
        + "|"
        + item["url"]
    )

    event_id = hashlib.sha256(
        event_id_source.encode(
            "utf-8"
        )
    ).hexdigest()[:24]

    event = {
        "id": event_id,
        "product_name": title,
        "retailer": retailer,
        "category": category,
        "application_start": (
            periods[
                "application_start"
            ]
        ),
        "application_end": (
            periods[
                "application_end"
            ]
        ),
        "sale_datetime": None,
        "price": (
            extract_price(
                detail_text
            )
            if detail_text
            else None
        ),
        "conditions": None,
        "official_url": item["url"],
        "source_url": source["url"],
        "status": "unknown",
        "verified": True,
        "detail_status": detail_status,
    }
    event["status"] = determine_status(

        event

    )
    # fingerprintには
    # 安定した意味情報だけを使用する。
    fingerprint_data = {
        "product_name": (
            event.get(
                "product_name"
            )
        ),
        "retailer": (
            event.get(
                "retailer"
            )
        ),
        "category": (
            event.get(
                "category"
            )
        ),
        "application_start": (
            event.get(
                "application_start"
            )
        ),
        "application_end": (
            event.get(
                "application_end"
            )
        ),
        "sale_datetime": (
            event.get(
                "sale_datetime"
            )
        ),
        "price": (
            event.get(
                "price"
            )
        ),
        "conditions": (
            event.get(
                "conditions"
            )
        ),
        "official_url": (
            event.get(
                "official_url"
            )
        ),

    }

    fingerprint_source = json.dumps(
        fingerprint_data,
        ensure_ascii=False,
        sort_keys=True,
    )

    event["fingerprint"] = (
        hashlib.sha256(
            fingerprint_source.encode(
                "utf-8"
            )
        ).hexdigest()
    )

    return event


# ============================================================
# Individual article
# ============================================================

def inspect_item(
    source,
    item,
):
    # タイトル段階で除外。
    if not title_is_sale_candidate(
        item["title"]
    ):
        return None

    try:
        page = fetch(
            item["url"]
        )

        text = clean_text(
            page
        )

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

        # Pokémon Center Online等、
        # 403でも一覧タイトルが公式に
        # 確認できる場合はEventを保持。
        return make_event(
            source,
            item,
            "",
            f"http_{exc.code}",
        )

    except Exception as exc:
        print(
            "  ERROR "
            f"{type(exc).__name__}: "
            f"{item['url']} "
            f"{exc}"
        )

        return None


# ============================================================
# Source scan
# ============================================================

def scan_source(source):
    print()
    print("=" * 72)
    print(
        f"Checking "
        f"{source['name']}"
    )

    page = fetch(
        source["url"]
    )

    if (
        source["type"]
        == "sanyodo"
    ):
        print_sanyodo_diagnostics(
            source,
            page,
        )

    links = extract_article_links(
        source,
        page,
    )

    print(
        f"Article links: "
        f"{len(links)}"
    )

    title_candidates = [
        item
        for item in links
        if title_is_sale_candidate(
            item["title"]
        )
    ]

    print(
        "Title-qualified candidates: "
        f"{len(title_candidates)}"
    )

    events = []

    for item in title_candidates[:30]:
        event = inspect_item(
            source,
            item,
        )

        if event:
            events.append(
                event
            )

    print(
        f"Verified sale events: "
        f"{len(events)}"
    )

    return events


# ============================================================
# State
# ============================================================

def empty_state():
    return {
        "version": 3,
        "initialized": False,
        "events": {},
        "pending": {},
        "posted": {},
    }


def load_test_state():
    if not TEST_STATE_FILE.exists():
        return empty_state()

    try:
        with TEST_STATE_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            state = json.load(
                file
            )

    except Exception as exc:
        print(
            "WARNING: "
            "state_v3_test.json "
            "could not be loaded:"
        )
        print(
            f"  {type(exc).__name__}: "
            f"{exc}"
        )

        return empty_state()

    if not isinstance(
        state,
        dict,
    ):
        return empty_state()

    state.setdefault(
        "version",
        3,
    )

    state.setdefault(
        "initialized",
        False,
    )

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

    return state


def save_test_state(state):
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
            sort_keys=True,
        )

        file.write("\n")


# ============================================================
# X preview
# ============================================================

def build_preview(event):
    lines = [
        (
            f"【ポケカ"
            f"{event['category']}】"
        ),
        "",
        event["product_name"],
        (
            f"販売店："
            f"{event['retailer']}"
        ),
    ]

    if event.get("price"):
        lines.append(
            f"価格："
            f"{event['price']}"
        )

    if event.get(
        "application_start"
    ):
        lines.append(
            "受付開始："
            + event[
                "application_start"
            ]
        )

    if event.get(
        "application_end"
    ):
        lines.append(
            "締切："
            + event[
                "application_end"
            ]
        )

    lines.extend(
        [
            "",
            "▼公式",
            event["official_url"],
            "",
            (
                "#ポケカ "
                "#ポケモンカード"
            ),
        ]
    )

    return "\n".join(
        lines
    )


# ============================================================
# Queue
# ============================================================
def queue_new_or_changed(
    state,
    current,
):
    pending = state.setdefault(
        "pending",
        {},
    )

    posted = state.setdefault(
        "posted",
        {},
    )

    old_events = state.get(
        "events",
        {},
    )

    added = []

    for event_id, event in current.items():
        status = event.get(
            "status",
            "unknown",
        )

        if status not in (
            "open",
            "upcoming",
        ):
            print(
                "QUEUE SKIP STATUS: "
                f"{status} | "
                f"{event['retailer']} | "
                f"{event['product_name'][:60]}"
            )

            # C1時代に作られた古いpendingも除去
            pending.pop(
                event_id,
                None,
            )

            continue

        old = old_events.get(
            event_id
        )

        old_fingerprint = (
            old.get("fingerprint")
            if old
            else None
        )

        new_fingerprint = (
            event["fingerprint"]
        )

        if old is None:
            print(
                "QUEUE DEBUG: NEW | "
                f"{event['retailer']} | "
                f"{event['product_name'][:60]}"
            )

        elif (
            old_fingerprint
            != new_fingerprint
        ):
            print(
                "QUEUE DEBUG: CHANGED | "
                f"{event['retailer']} | "
                f"{event['product_name'][:60]}"
            )

            print(
                f"  OLD: "
                f"{old_fingerprint}"
            )

            print(
                f"  NEW: "
                f"{new_fingerprint}"
            )

        else:
            print(
                "QUEUE DEBUG: SAME | "
                f"{event['retailer']} | "
                f"{event['product_name'][:60]}"
            )

        changed = (
            old is None
            or old_fingerprint
            != new_fingerprint
        )

        if not changed:
            continue

        # 同じfingerprintを既に投稿済みなら再投稿しない
        posted_record = posted.get(
            event_id
        )

        if (
            posted_record
            and posted_record.get(
                "fingerprint"
            )
            == new_fingerprint
        ):
            print(
                "  SKIP: already posted"
            )
            continue

        # 同じfingerprintがpendingなら重複登録しない
        pending_record = pending.get(
            event_id
        )

        if (
            pending_record
            and pending_record.get(
                "fingerprint"
            )
            == new_fingerprint
        ):
            print(
                "  SKIP: already pending"
            )
            continue

        pending[event_id] = {
            "event": event,
            "fingerprint": (
                new_fingerprint
            ),
            "queued_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "reason": (
                "new"
                if old is None
                else "changed"
            ),
        }

        added.append(
            event_id
        )

    return added

# ============================================================
# Queue DRY RUN
# ============================================================

def simulate_pending_posts(
    state,
):
    pending = state.setdefault(
        "pending",
        {},
    )

    posted = state.setdefault(
        "posted",
        {},
    )

    selected = list(
        pending.items()
    )[:MAX_POSTS_PER_RUN]

    simulated = []

    for (
        event_id,
        record,
    ) in selected:
        event = record[
            "event"
        ]

        print()
        print("=" * 72)
        print(
            "WOULD POST TO X"
        )
        print("=" * 72)

        print(
            build_preview(
                event
            )
        )

        # DRY RUNなので実際には
        # Bufferへ送らない。
        #
        # キュー動作検証のため、
        # 投稿成功したものとして
        # test stateのpostedへ移動する。
        posted[event_id] = {
            "fingerprint": (
                record[
                    "fingerprint"
                ]
            ),
            "posted_at": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "mode": (
                "dry_run_simulation"
            ),
        }

        simulated.append(
            event_id
        )

    # 「投稿成功」したものだけ
    # pendingから削除する。
    for event_id in simulated:
        pending.pop(
            event_id,
            None,
        )

    return simulated


# ============================================================
# Main
# ============================================================
def main():
    print(
        "Pokemon Card Monitor "
        f"{VERSION}"
    )

    print(
        "DRY RUN: "
        "Buffer/X投稿なし"
    )

    print(
        "DRY RUN: "
        "本番state.json変更なし"
    )

    print(
        "MAX_POSTS_PER_RUN="
        f"{MAX_POSTS_PER_RUN}"
    )

    state = load_test_state()

    print()
    print("STATE BEFORE:")

    print(
        "  events="
        f"{len(state['events'])}"
    )

    print(
        "  pending="
        f"{len(state['pending'])}"
    )

    print(
        "  posted="
        f"{len(state['posted'])}"
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
                "SOURCE ERROR "
                f"{source['name']}: "
                f"{type(exc).__name__}: "
                f"{exc}"
            )

    print()
    print("=" * 72)

    print(
        "TOTAL VERIFIED EVENTS: "
        f"{len(current)}"
    )

    # ========================================================
    # C6 first-run baseline
    # ========================================================

    first_run = not state.get(
        "initialized",
        False,
    )

    if first_run:
        print()
        print(
            "FIRST RUN / BASELINE MODE"
        )

        print(
            "No posts will be sent."
        )

        added = []

    else:
        added = queue_new_or_changed(
            state,
            current,
        )

    print()
    print(
        "ADDED TO PENDING: "
        f"{len(added)}"
    )

    print(
        "PENDING BEFORE POST: "
        f"{len(state['pending'])}"
    )

    # 初回baselineでは投稿処理を行わない。
    if first_run:
        simulated = []

    else:
        simulated = simulate_pending_posts(
            state
        )

    print()
    print(
        "WOULD POST COUNT: "
        f"{len(simulated)}"
    )

    print(
        "REMAINING PENDING: "
        f"{len(state['pending'])}"
    )

    # 今回取得したイベントを保存
    state["events"] = current

    state["initialized"] = True

    state["version"] = 3

    state["updated_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    # C6専用stateへ保存
    save_test_state(
        state
    )

    print()
    print("STATE AFTER:")

    print(
        "  events="
        f"{len(state['events'])}"
    )

    print(
        "  pending="
        f"{len(state['pending'])}"
    )

    print(
        "  posted="
        f"{len(state['posted'])}"
    )

    print()
    print(
        "V3-C6 PRODUCTION BASELINE "
        "completed."
    )


if __name__ == "__main__":
    main()
