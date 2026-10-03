import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


VERSION = "3C8-CHATGPT-QUEUE-BUFFER"
JST = ZoneInfo("Asia/Tokyo")

QUEUE_FILE = Path("data/x_queue.json")
STATE_FILE = Path("data/state_v3c8.json")

BUFFER_API_URL = "https://api.buffer.com/graphql"

MAX_POSTS_PER_RUN = 1


def now_iso():
    return datetime.now(JST).isoformat(timespec="seconds")


def load_json(path, default):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR loading {path}: {exc}")
        raise


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    temp = path.with_suffix(path.suffix + ".tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    temp.replace(path)


def make_fingerprint(item):
    """
    event_id + revision を優先する。

    同じ案件の単なる再取得では再投稿しない。
    締切変更など重要変更時だけ revision を変更する。
    """

    event_id = str(item.get("event_id", "")).strip()
    revision = str(item.get("revision", "1")).strip()

    if not event_id:
        raise ValueError("event_id is required")

    raw = f"{event_id}|{revision}"

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def validate_item(item):
    required = [
        "event_id",
        "text",
        "official_url",
        "verified",
    ]

    for key in required:
        if key not in item:
            return False, f"missing {key}"

    if item.get("verified") is not True:
        return False, "verified is not true"

    text = str(item.get("text", "")).strip()

    if not text:
        return False, "text is empty"

    official_url = str(
        item.get("official_url", "")
    ).strip()

    if not official_url.startswith(
        ("https://", "http://")
    ):
        return False, "invalid official_url"

    return True, "OK"


def build_post_text(item):
    """
    原則として受信した完成済みX本文をそのまま使用。
    official_url が本文に無ければ末尾に追加。
    """

    text = str(item["text"]).strip()
    official_url = str(
        item["official_url"]
    ).strip()

    if official_url not in text:
        text += f"\n\n▼公式\n{official_url}"

    return text


def post_to_buffer(text):
    api_key = os.environ.get(
        "BUFFER_API_KEY"
    )
    channel_id = os.environ.get(
        "BUFFER_CHANNEL_ID"
    )

    if not api_key:
        raise RuntimeError(
            "BUFFER_API_KEY is missing"
        )

    if not channel_id:
        raise RuntimeError(
            "BUFFER_CHANNEL_ID is missing"
        )

    query = """
    mutation CreatePost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess {
          post {
            id
          }
        }
        ... on MutationError {
          message
        }
      }
    }
    """

    payload = {
        "query": query,
        "variables": {
            "input": {
                "channelId": channel_id,
                "text": text,
                "mode": "shareNow",
                "schedulingType": "automatic",
                "aiAssisted": True,
            }
        },
    }

    request = urllib.request.Request(
        BUFFER_API_URL,
        data=json.dumps(
            payload
        ).encode("utf-8"),
        headers={
            "Authorization":
                f"Bearer {api_key}",
            "Content-Type":
                "application/json",
            "User-Agent":
                "PokemonCardMonitor/3C8",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            result = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"Buffer HTTP {exc.code}: "
            f"{body}"
        ) from exc

    if result.get("errors"):
        raise RuntimeError(
            "Buffer GraphQL error: "
            + json.dumps(
                result["errors"],
                ensure_ascii=False,
            )
        )

    create_post = (
        result.get("data", {})
        .get("createPost", {})
    )

    if create_post.get("message"):
        raise RuntimeError(
            create_post["message"]
        )

    post = create_post.get("post")

    if not post or not post.get("id"):
        raise RuntimeError(
            "Buffer returned no post ID"
        )

    return post["id"]


def process_queue(queue, state):
    posted = state.setdefault(
        "posted",
        {}
    )

    remaining = []
    sent_count = 0

    for item in queue:
        valid, reason = validate_item(
            item
        )

        if not valid:
            print(
                "QUEUE REJECT:",
                reason,
                "|",
                item.get(
                    "event_id",
                    "NO-ID",
                ),
            )

            # 不正データは消さずに保持
            remaining.append(item)
            continue

        fingerprint = make_fingerprint(
            item
        )

        if fingerprint in posted:
            print(
                "ALREADY POSTED:",
                item["event_id"],
            )

            # 投稿済みなのでqueueから除去
            continue

        if sent_count >= MAX_POSTS_PER_RUN:
            remaining.append(item)
            continue

        text = build_post_text(item)

        print()
        print(
            "POSTING:",
            item["event_id"],
        )
        print("--------------------")
        print(text)
        print("--------------------")

        try:
            buffer_post_id = (
                post_to_buffer(text)
            )
        except Exception as exc:
            print(
                "BUFFER POST FAILED:",
                repr(exc),
            )

            # 失敗したものは次回再試行
            remaining.append(item)
            continue

        posted[fingerprint] = {
            "event_id":
                item["event_id"],
            "revision":
                item.get(
                    "revision",
                    "1",
                ),
            "retailer":
                item.get("retailer"),
            "category":
                item.get("category"),
            "official_url":
                item["official_url"],
            "posted_at":
                now_iso(),
            "buffer_post_id":
                buffer_post_id,
        }

        sent_count += 1

        print(
            "BUFFER POST SUCCESS:",
            buffer_post_id,
        )

    return remaining, sent_count


def main():
    print(
        "Pokemon Card Monitor",
        VERSION,
    )
    print(
        "LIVE MODE: Queue -> Buffer -> X"
    )
    print(
        "MAX_POSTS_PER_RUN="
        f"{MAX_POSTS_PER_RUN}"
    )

    queue = load_json(
        QUEUE_FILE,
        [],
    )

    state = load_json(
        STATE_FILE,
        {
            "version": 8,
            "posted": {},
        },
    )

    if not isinstance(queue, list):
        raise RuntimeError(
            "x_queue.json must be "
            "a JSON array"
        )

    print(
        "QUEUE BEFORE:",
        len(queue),
    )

    print(
        "POSTED HISTORY:",
        len(
            state.get(
                "posted",
                {},
            )
        ),
    )

    remaining, sent_count = (
        process_queue(
            queue,
            state,
        )
    )

    state["version"] = 8
    state["last_run_at"] = now_iso()

    save_json(
        QUEUE_FILE,
        remaining,
    )

    save_json(
        STATE_FILE,
        state,
    )

    print()
    print(
        "POSTED COUNT:",
        sent_count,
    )
    print(
        "QUEUE AFTER:",
        len(remaining),
    )
    print(
        "POSTED HISTORY:",
        len(
            state["posted"]
        ),
    )
    print(
        "V3C8 completed."
    )


if __name__ == "__main__":
    main()
