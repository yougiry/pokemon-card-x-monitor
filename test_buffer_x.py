import json
import os
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")

BUFFER_API_URL = "https://api.buffer.com/graphql"


def main():
    api_key = os.environ.get("BUFFER_API_KEY")
    channel_id = os.environ.get("BUFFER_CHANNEL_ID")

    if not api_key:
        raise RuntimeError(
            "BUFFER_API_KEY is missing"
        )

    if not channel_id:
        raise RuntimeError(
            "BUFFER_CHANNEL_ID is missing"
        )

    now = datetime.now(JST)

    text = (
        "【ポケカ監視システム 動作テスト】\n\n"
        "新しい販売情報を検出した場合に、"
        "自動でXへ投稿できるか確認するテストです。\n\n"
        f"テスト日時：{now:%Y/%m/%d %H:%M} JST\n\n"
        "※これは実際の販売・抽選情報ではありません。\n"
        "#ポケカ"
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
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "PokemonCardMonitor/3C7",
        },
        method="POST",
    )

    print("Sending test post to Buffer...")
    print("Channel ID:", channel_id)

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        result = json.loads(
            response.read().decode("utf-8")
        )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )

    if result.get("errors"):
        raise RuntimeError(
            "Buffer GraphQL error"
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

    if not post:
        raise RuntimeError(
            "Buffer returned no post"
        )

    print()
    print("==============================")
    print("BUFFER TEST SUCCESS")
    print("Post ID:", post.get("id"))
    print("==============================")


if __name__ == "__main__":
    main()
