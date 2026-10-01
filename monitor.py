import hashlib
import html
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse


STATE_FILE = Path("data/state.json")

SOURCES = [
    {
        "id": "pokemon-card-news",
        "name": "ポケモンカード公式",
        "url": "https://www.pokemon-card.com/info/index.html",
    },
]


# ============================================================
# 商品販売情報として拾いたいキーワード
# ============================================================

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


# ============================================================
# 大会・イベント参加情報として除外するキーワード
# ============================================================

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
    "(compatible; pokemon-card-x-monitor/2.0; "
    "+https://github.com/yougiry/pokemon-card-x-monitor)"
)


# ============================================================
# HTTP
# ============================================================

def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )

    with urllib.request.urlopen(
        req,
        timeout=30,
    ) as res:
        return res.read().decode(
            "utf-8",
            errors="replace",
        )


# ============================================================
# テキスト整形
# ============================================================

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


# ============================================================
# 販売情報かどうか
# ============================================================

def is_sale_candidate(title):
    if not title:
        return False

    # 大会・イベント系を先に除外
    if any(
        word.lower() in title.lower()
        for word in EXCLUDE_KEYWORDS
    ):
        return False

    return any(
        word.lower() in title.lower()
        for word in SALE_KEYWORDS
    )


# ============================================================
# 公式ニュース一覧から候補抽出
# ============================================================

def extract_candidates(source, page):
    links = re.findall(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>'
        r'(.*?)</a>',
        page,
        flags=re.I | re.S,
    )

    results = []

    for href, body in links:
        title = clean_text(body)

        if not is_sale_candidate(title):
            continue

        url = urljoin(
            source["url"],
            href,
        ).strip()

        # 公式ドメインのみ
        if not (
            "pokemon-card.com" in url
            or "pokemoncenter-online.com" in url
        ):
            continue

        event_id = hashlib.sha256(
            f'{source["id"]}|{url}'.encode(
                "utf-8"
            )
        ).hexdigest()[:24]

        results.append(
            {
                "id": event_id,
                "source": source["name"],
                "title": title,
                "url": url,
            }
        )

    # URL単位で重複排除
    unique = {}

    for item in results:
        unique[item["id"]] = item

    return list(unique.values())


# ============================================================
# 販売元推定
# ============================================================

def detect_retailer(url):
    host = urlparse(url).netloc.lower()

    if "pokemoncenter-online.com" in host:
        return "ポケモンセンターオンライン"

    if "pokemon-card.com" in host:
        return "ポケモンカード公式"

    if "amazon.co.jp" in host:
        return "Amazon.co.jp"

    if "rakuten.co.jp" in host:
        return "楽天"

    if "yodobashi.com" in host:
        return "ヨドバシカメラ"

    if "biccamera.com" in host:
        return "ビックカメラ"

    return host


# ============================================================
# 販売形式推定
# ============================================================

def detect_sale_type(text):
    if "抽選" in text:
        return "抽選販売"

    if "予約" in text:
        return "予約販売"

    if "受注" in text:
        return "受注販売"

    if "招待" in text:
        return "招待販売"

    if "追加販売" in text:
        return "追加販売"

    if "再販売" in text or "再販" in text:
        return "再販売"

    if "再入荷" in text:
        return "再入荷"

    if "在庫" in text:
        return "在庫情報"

    return "販売情報"


# ============================================================
# 価格抽出
# ============================================================

def extract_price(text):
    patterns = [
        r"([0-9]{1,3}(?:,[0-9]{3})+円)",
        r"([0-9]{3,6}円)",
        r"税込\s*([0-9]{1,3}(?:,[0-9]{3})+円)",
        r"税込\s*([0-9]{3,6}円)",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.I,
        )

        if match:
            return match.group(1)

    return None


# ============================================================
# 詳細ページ解析
# ============================================================

def extract_detail(item):
    detail = {
        "retailer": detect_retailer(
            item["url"]
        ),
        "sale_type": None,
        "price": None,
        "detail_text": "",
    }

    try:
        page = fetch(item["url"])
        text = clean_text(page)

        combined = (
            item["title"]
            + " "
            + text
        )

        detail["sale_type"] = (
            detect_sale_type(combined)
        )

        detail["price"] = (
            extract_price(text)
        )

        # state.jsonが巨大化しすぎないよう制限
        detail["detail_text"] = text[:4000]

    except Exception as exc:
        print(
            f"WARNING detail fetch failed: "
            f"{item['url']} : {exc}"
        )

        detail["sale_type"] = (
            detect_sale_type(
                item["title"]
            )
        )

    return detail


# ============================================================
# 差分判定用fingerprint
# detail_text全文はfingerprintに含めない
# ============================================================

def fingerprint(item):
    important = {
        "source": item.get("source"),
        "title": item.get("title"),
        "url": item.get("url"),
        "retailer": item.get("retailer"),
        "sale_type": item.get("sale_type"),
        "price": item.get("price"),
    }

    text = json.dumps(
        important,
        ensure_ascii=False,
        sort_keys=True,
    )

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


# ============================================================
# state
# ============================================================

def load_state():
    if not STATE_FILE.exists():
        return {
            "version": 2,
            "initialized": False,
            "events": {},
        }

    try:
        return json.loads(
            STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return {
            "version": 2,
            "initialized": False,
            "events": {},
        }


def save_state(state):
    STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


# ============================================================
# X投稿文
# ============================================================

def make_post(item, change_type):
    if change_type == "new":
        prefix = "【ポケカ販売情報・新着】"
    else:
        prefix = "【ポケカ販売情報・更新】"

    lines = [
        prefix,
        item.get(
            "retailer",
            item["source"],
        ),
        item["title"],
    ]

    sale_type = item.get("sale_type")

    if sale_type:
        lines.append(
            f"販売形式：{sale_type}"
        )

    price = item.get("price")

    if price:
        lines.append(
            f"価格：{price}"
        )

    lines.extend(
        [
            "",
            "▼公式",
            item["url"],
            "",
            "#ポケカ #ポケモンカード",
        ]
    )

    text = "\n".join(lines)

    # X向けに安全側で短縮
    if len(text) > 270:
        title = item["title"]

        overflow = len(text) - 260

        new_length = max(
            30,
            len(title) - overflow,
        )

        short_title = (
            title[:new_length]
            + "…"
        )

        lines[2] = short_title

        text = "\n".join(lines)

    return text


# ============================================================
# Buffer投稿
# ============================================================

def post_buffer(text):
    api_key = os.environ[
        "BUFFER_API_KEY"
    ]

    channel_id = os.environ[
        "BUFFER_CHANNEL_ID"
    ]

    query = """
    mutation PublishPost($input: CreatePostInput!) {
      createPost(input: $input) {
        __typename
      }
    }
    """

    variables = {
        "input": {
            "channelId": channel_id,
            "text": text,
            "mode": "shareNow",
            "schedulingType": "automatic",
            "aiAssisted": True,
        }
    }

    payload = json.dumps(
        {
            "query": query,
            "variables": variables,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://api.buffer.com",
        data=payload,
        headers={
            "Authorization":
                f"Bearer {api_key}",
            "Content-Type":
                "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        req,
        timeout=30,
    ) as res:
        result = json.loads(
            res.read().decode(
                "utf-8"
            )
        )

    if result.get("errors"):
        raise RuntimeError(
            "Buffer GraphQL error: "
            + json.dumps(
                result["errors"],
                ensure_ascii=False,
            )
        )

    typename = (
        result
        .get("data", {})
        .get("createPost", {})
        .get("__typename")
    )

    if typename != "PostActionSuccess":
        raise RuntimeError(
            f"Buffer returned {typename}"
        )

    return True


# ============================================================
# Main
# ============================================================

def main():
    state = load_state()

    old_events = state.get(
        "events",
        {},
    )

    current = {}

    for source in SOURCES:
        print(
            f"Checking {source['name']}"
        )

        try:
            page = fetch(
                source["url"]
            )

            candidates = (
                extract_candidates(
                    source,
                    page,
                )
            )

            print(
                "Sale candidates: "
                f"{len(candidates)}"
            )

            for item in candidates:
                detail = extract_detail(
                    item
                )

                item.update(detail)

                item["fingerprint"] = (
                    fingerprint(item)
                )

                current[
                    item["id"]
                ] = item

        except Exception as exc:
            print(
                f"ERROR fetching "
                f"{source['name']}: "
                f"{exc}"
            )

    # 取得失敗時にstateを空にしない
    if not current:
        raise RuntimeError(
            "No sale candidates found. "
            "State was NOT overwritten."
        )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    # ========================================================
    # V2初回
    # ========================================================

    if (
        not state.get("initialized")
        or state.get("version") != 2
    ):
        print(
            "FIRST RUN / BASELINE MODE"
        )

        print(
            "No posts will be sent to X."
        )

        for item in current.values():
            item["first_seen"] = now
            item["last_seen"] = now

            item[
                "posted_fingerprint"
            ] = item["fingerprint"]

        save_state(
            {
                "version": 2,
                "initialized": True,
                "updated_at": now,
                "events": current,
            }
        )

        print(
            f"Baseline saved: "
            f"{len(current)} events"
        )

        return

    # ========================================================
    # 差分検出
    # ========================================================

    notifications = []

    for event_id, item in (
        current.items()
    ):
        old = old_events.get(
            event_id
        )

        if old is None:
            item["first_seen"] = now
            item["last_seen"] = now

            notifications.append(
                (
                    "new",
                    item,
                )
            )

        else:
            item["first_seen"] = (
                old.get(
                    "first_seen",
                    now,
                )
            )

            item["last_seen"] = now

            old_fp = old.get(
                "fingerprint"
            )

            if (
                old_fp
                != item["fingerprint"]
            ):
                notifications.append(
                    (
                        "updated",
                        item,
                    )
                )

            item[
                "posted_fingerprint"
            ] = old.get(
                "posted_fingerprint"
            )

            if old.get("posted_at"):
                item["posted_at"] = (
                    old["posted_at"]
                )

    print(
        "New/changed sale events: "
        f"{len(notifications)}"
    )

    # ========================================================
    # 安全装置
    # ========================================================

    MAX_POSTS_PER_RUN = 3

    for (
        change_type,
        item,
    ) in notifications[
        :MAX_POSTS_PER_RUN
    ]:
        text = make_post(
            item,
            change_type,
        )

        print(
            "Posting to Buffer/X:"
        )

        print(text)

        post_buffer(text)

        item[
            "posted_fingerprint"
        ] = item["fingerprint"]

        item["posted_at"] = now

    # ========================================================
    # state保存
    # ========================================================

    merged = dict(
        old_events
    )

    merged.update(
        current
    )

    save_state(
        {
            "version": 2,
            "initialized": True,
            "updated_at": now,
            "events": merged,
        }
    )

    print(
        "Monitor V2 completed successfully."
    )


if __name__ == "__main__":
    main()
