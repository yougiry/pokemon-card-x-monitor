import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openai import OpenAI


VERSION = "1.0-OPENAI-WEB-COLLECTOR"

JST = ZoneInfo("Asia/Tokyo")

QUEUE_FILE = Path("data/x_queue.json")
STATE_FILE = Path("data/state_v3c8.json")

MODEL = os.environ.get(
    "OPENAI_MODEL",
    "gpt-6-luna",
)

MAX_EVENTS = 5


MONITOR_PROMPT = """
あなたは日本国内のポケモンカード販売情報を監視する調査担当者です。

現在日時（日本時間）:
{now}

Web検索を必ず実行してください。

前回までにXへ投稿済みのイベント情報:
{posted_history}

日本国内でポケモンカードを販売する主要な公式・正規販売チャネルを
横断チェックしてください。

明示的な監視対象:

・ポケモンセンターオンライン
・ポケモンカード公式
・Amazon.co.jp
・楽天ブックス
・GEO
・TSUTAYA
・古本市場
・三洋堂書店
・ヨドバシカメラ
・ビックカメラ
・ヤマダデンキ
・イオン
・イトーヨーカドー
・トイザらス
・Joshin
・エディオン
・ノジマ
・HMV
・セブンネットショッピング
・駿河屋
・カードラボ
・ドラゴンスター
・フルコンプ
・BOOKOFF
・WonderGOO

これ以外でも、日本国内でポケモンカードを正規販売する主要EC、
量販店、書店、カードショップに新規情報があれば対象にしてください。

探す情報:

・抽選受付
・予約受付
・招待販売
・再販
・再入荷
・在庫復活
・追加販売
・店頭販売告知

最重要ルール:

1. 現在応募・購入できる情報を最優先する。

2. 締切が近いものを優先する。

3. メーカー公式、販売店公式、公式EC、公式アプリ、
   公式告知を可能な限り確認する。

4. 非公式まとめサイトやSNSは発見目的には使ってよいが、
   公式情報で確認できなければ verified=false とする。

5. verified=false のイベントはX投稿対象にしない。

6. 以下は除外する。

・転売価格
・プレミア価格
・非正規販売
・マーケットプレイス第三者出品
・中古品
・オリパ
・福袋

7. 過去に投稿済みで内容変更のないイベントは返さない。

8. 同じイベントでも、締切、価格、販売日時、条件などに
   重要な変更があった場合だけ revision を増やして返す。

9. 単なる文章表現の違いではrevisionを増やさない。

10. official_url は可能な限り販売店またはメーカーの
    公式ページURLにする。

11. event_id は同じ販売案件なら将来の監視でも同じ値になるよう、
    retailer・商品・販売方式などから安定した短いIDを作る。

12. text はそのままXへ投稿できる日本語本文にする。

13. textには最低限以下を含める。

販売店
商品名
区分
受付期間または販売日時
価格（確認できる場合）
主要条件
#ポケカ

14. URLはtextに無理に入れなくてよい。
    C8側でofficial_urlを追加する。

15. 情報がない場合はeventsを空配列にする。

最大 {max_events} 件まで返してください。
"""


SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "maxItems": MAX_EVENTS,
            "items": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string"
                    },
                    "revision": {
                        "type": "string"
                    },
                    "retailer": {
                        "type": "string"
                    },
                    "product_name": {
                        "type": "string"
                    },
                    "category": {
                        "type": "string",
                        "enum": [
                            "抽選",
                            "予約",
                            "招待",
                            "再販",
                            "再入荷",
                            "在庫復活",
                            "追加販売",
                            "店頭販売"
                        ]
                    },
                    "application_start": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "application_end": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "sale_datetime": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "price": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "conditions": {
                        "type": [
                            "string",
                            "null"
                        ]
                    },
                    "official_url": {
                        "type": "string"
                    },
                    "verified": {
                        "type": "boolean"
                    },
                    "text": {
                        "type": "string"
                    }
                },
                "required": [
                    "event_id",
                    "revision",
                    "retailer",
                    "product_name",
                    "category",
                    "application_start",
                    "application_end",
                    "sale_datetime",
                    "price",
                    "conditions",
                    "official_url",
                    "verified",
                    "text"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": [
        "events"
    ],
    "additionalProperties": False
}


def now_iso():
    return datetime.now(
        JST
    ).isoformat(
        timespec="seconds"
    )


def load_json(path, default):
    if not path.exists():
        return default

    with path.open(
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp = path.with_suffix(
        path.suffix + ".tmp"
    )

    with temp.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp.replace(path)


def get_posted_history():
    state = load_json(
        STATE_FILE,
        {
            "posted": {}
        }
    )

    posted = state.get(
        "posted",
        {}
    )

    history = []

    for item in posted.values():
        history.append({
            "event_id":
                item.get("event_id"),
            "revision":
                item.get("revision"),
            "retailer":
                item.get("retailer"),
            "category":
                item.get("category"),
            "official_url":
                item.get(
                    "official_url"
                ),
            "posted_at":
                item.get("posted_at")
        })

    return history[-100:]


def collect_events():
    api_key = os.environ.get(
        "OPENAI_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is missing"
        )

    client = OpenAI(
        api_key=api_key
    )

    history = get_posted_history()

    prompt = MONITOR_PROMPT.format(
        now=now_iso(),
        posted_history=json.dumps(
            history,
            ensure_ascii=False,
            indent=2
        ),
        max_events=MAX_EVENTS
    )

    print(
        "Calling OpenAI Responses API..."
    )
    print(
        "MODEL:",
        MODEL
    )

    response = client.responses.create(
        model=MODEL,

        tools=[
            {
                "type": "web_search",
                "search_context_size":
                    "medium",
                "external_web_access":
                    True
            }
        ],

        tool_choice="required",

        input=[
            {
                "role": "user",
                "content": prompt
            }
        ],

        text={
            "format": {
                "type":
                    "json_schema",
                "name":
                    "pokemon_card_events",
                "strict":
                    True,
                "schema":
                    SCHEMA
            }
        }
    )

    if not response.output_text:
        raise RuntimeError(
            "OpenAI returned empty output"
        )

    result = json.loads(
        response.output_text
    )

    return result.get(
        "events",
        []
    )


def append_to_queue(events):
    queue = load_json(
        QUEUE_FILE,
        []
    )

    if not isinstance(queue, list):
        raise RuntimeError(
            "x_queue.json must "
            "contain a JSON array"
        )

    existing = {
        (
            str(item.get("event_id")),
            str(item.get(
                "revision",
                "1"
            ))
        )
        for item in queue
    }

    added = 0

    for event in events:

        if event.get(
            "verified"
        ) is not True:
            print(
                "SKIP UNVERIFIED:",
                event.get(
                    "event_id"
                )
            )
            continue

        key = (
            str(
                event.get(
                    "event_id"
                )
            ),
            str(
                event.get(
                    "revision",
                    "1"
                )
            )
        )

        if key in existing:
            print(
                "QUEUE DUPLICATE:",
                key
            )
            continue

        queue.append(event)

        existing.add(key)

        added += 1

        print(
            "QUEUE ADD:",
            event.get(
                "retailer"
            ),
            "|",
            event.get(
                "product_name"
            )
        )

    save_json(
        QUEUE_FILE,
        queue
    )

    return added


def main():
    print(
        "Pokemon Card OpenAI Collector",
        VERSION
    )

    events = collect_events()

    print(
        "COLLECTED EVENTS:",
        len(events)
    )

    added = append_to_queue(
        events
    )

    print(
        "ADDED TO C8 QUEUE:",
        added
    )

    print(
        "Collector completed."
    )


if __name__ == "__main__":
    main()
