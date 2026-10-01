import hashlib
import html
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin


STATE_FILE = Path("data/state.json")

SOURCES = [
    {
        "id": "pokemon-card-news",
        "name": "ポケモンカード公式",
        "url": "https://www.pokemon-card.com/info/index.html",
    },
]

KEYWORDS = [
    "抽選",
    "抽選販売",
    "予約",
    "予約販売",
    "受注販売",
    "追加販売",
    "再販売",
    "再販",
    "販売方法",
    "販売について",
    "販売開始",
    "受付開始",
    "受け付け",
    "ポケモンセンターオンライン",
]

USER_AGENT = (
    "Mozilla/5.0 (compatible; pokemon-card-x-monitor/1.0; "
    "+https://github.com/yougiry/pokemon-card-x-monitor)"
)


def fetch(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
        },
    )

    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8", errors="replace")


def clean_text(value):
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def extract_candidates(source, page):
    """
    公式ニュースページからリンクを抽出し、
    販売関連キーワードを含む告知だけを候補化。
    """
    links = re.findall(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        page,
        flags=re.I | re.S,
    )

    results = []

    for href, body in links:
        title = clean_text(body)

        if not title:
            continue

        if not any(word in title for word in KEYWORDS):
            continue

        url = urljoin(source["url"], href)

        # ポケカ公式または公式告知からリンクされたページだけ
        if not (
            "pokemon-card.com" in url
            or "pokemoncenter-online.com" in url
        ):
            continue

        event_id = hashlib.sha256(
            f'{source["id"]}|{url}'.encode("utf-8")
        ).hexdigest()[:24]

        results.append(
            {
                "id": event_id,
                "source": source["name"],
                "title": title,
                "url": url,
            }
        )

    # 同一URL排除
    unique = {}

    for item in results:
        unique[item["id"]] = item

    return list(unique.values())


def fingerprint(item):
    text = json.dumps(
        {
            "source": item["source"],
            "title": item["title"],
            "url": item["url"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_state():
    if not STATE_FILE.exists():
        return {
            "initialized": False,
            "events": {},
        }

    try:
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return {
            "initialized": False,
            "events": {},
        }


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

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


def make_post(item, change_type):
    prefix = (
        "【ポケカ販売情報・新着】"
        if change_type == "new"
        else "【ポケカ販売情報・更新】"
    )

    text = (
        f"{prefix}\n"
        f"{item['source']}\n"
        f"{item['title']}\n\n"
        f"▼公式\n"
        f"{item['url']}\n\n"
        f"#ポケカ #ポケモンカード"
    )

    # X向け安全側
    if len(text) > 270:
        max_title = max(
            20,
            270
            - len(prefix)
            - len(item["source"])
            - len(item["url"])
            - 35,
        )

        short_title = item["title"][:max_title] + "…"

        text = (
            f"{prefix}\n"
            f"{item['source']}\n"
            f"{short_title}\n\n"
            f"▼公式\n"
            f"{item['url']}\n\n"
            f"#ポケカ #ポケモンカード"
        )

    return text


def post_buffer(text):
    api_key = os.environ["BUFFER_API_KEY"]
    channel_id = os.environ["BUFFER_CHANNEL_ID"]

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
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as res:
        result = json.loads(
            res.read().decode("utf-8")
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
        result.get("data", {})
        .get("createPost", {})
        .get("__typename")
    )

    if typename != "PostActionSuccess":
        raise RuntimeError(
            f"Buffer returned {typename}"
        )

    return True


def main():
    state = load_state()
    old_events = state.get("events", {})

    current = {}

    for source in SOURCES:
        print(f"Checking: {source['name']}")

        try:
            page = fetch(source["url"])
            candidates = extract_candidates(source, page)

            print(
                f"Candidates: {len(candidates)}"
            )

            for item in candidates:
                item["fingerprint"] = fingerprint(item)
                current[item["id"]] = item

        except Exception as exc:
            print(
                f"ERROR fetching {source['name']}: {exc}"
            )

    if not current:
        raise RuntimeError(
            "No monitoring candidates found. "
            "Refusing to overwrite state."
        )

    now = datetime.now(timezone.utc).isoformat()

    # 初回はbaselineだけ作る
    if not state.get("initialized"):
        print(
            "First run: creating baseline. "
            "No X posts will be sent."
        )

        for item in current.values():
            item["first_seen"] = now
            item["last_seen"] = now
            item["posted_fingerprint"] = item["fingerprint"]

        save_state(
            {
                "initialized": True,
                "updated_at": now,
                "events": current,
            }
        )

        return

    notifications = []

    for event_id, item in current.items():

        old = old_events.get(event_id)

        if old is None:
            item["first_seen"] = now
            item["last_seen"] = now

            notifications.append(
                ("new", item)
            )

        else:
            item["first_seen"] = old.get(
                "first_seen",
                now,
            )
            item["last_seen"] = now

            old_fp = old.get("fingerprint")

            if old_fp != item["fingerprint"]:
                notifications.append(
                    ("updated", item)
                )

            item["posted_fingerprint"] = old.get(
                "posted_fingerprint"
            )

    print(
        f"New/changed events: {len(notifications)}"
    )

    # 1回の異常変更で大量投稿しない
    MAX_POSTS_PER_RUN = 3

    for change_type, item in notifications[
        :MAX_POSTS_PER_RUN
    ]:
        text = make_post(item, change_type)

        print("Posting:")
        print(text)

        post_buffer(text)

        item["posted_fingerprint"] = item["fingerprint"]
        item["posted_at"] = now

    # 過去イベントも保持
    merged = dict(old_events)
    merged.update(current)

    save_state(
        {
            "initialized": True,
            "updated_at": now,
            "events": merged,
        }
    )

    print("Monitor completed successfully.")


if __name__ == "__main__":
    main()
