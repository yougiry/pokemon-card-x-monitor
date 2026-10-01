import urllib.error
import urllib.request
from datetime import datetime, timezone


SOURCES = [
    {
        "name": "ポケモンカード公式",
        "url": "https://www.pokemon-card.com/info/index.html",
    },
    {
        "name": "ポケモンセンターオンライン",
        "url": "https://www.pokemoncenter-online.com/",
    },
    {
        "name": "GEO公式ニュース",
        "url": "https://geo-online.co.jp/news/",
    },
    {
        "name": "三洋堂書店 抽選販売",
        "url": (
            "https://www.sanyodo.co.jp/news/"
            "evt_lottery-sale?tags%5B%5D=5086"
        ),
    },
    {
        "name": "SHIBUYA TSUTAYA",
        "url": "https://shibuyatsutaya.tsite.jp/",
    },
    {
        "name": "Joshin web ポケモン",
        "url": "https://joshinweb.jp/game/18745/",
    },
]


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)


def test_source(source):
    print("=" * 70)
    print(f"SOURCE : {source['name']}")
    print(f"URL    : {source['url']}")

    request = urllib.request.Request(
        source["url"],
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

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:

            data = response.read()

            print(f"RESULT : HTTP {response.status}")
            print(f"FINAL  : {response.geturl()}")
            print(f"BYTES  : {len(data):,}")

            content_type = response.headers.get(
                "Content-Type",
                ""
            )

            print(f"TYPE   : {content_type}")

            text = data.decode(
                "utf-8",
                errors="replace",
            )

            # HTMLが実体を持っているかの簡易判定
            lower = text.lower()

            if "<html" in lower:
                print("HTML   : detected")
            else:
                print("HTML   : not detected")

            # JavaScript依存ページの簡易チェック
            script_count = lower.count("<script")

            print(
                f"SCRIPTS: {script_count}"
            )

            if len(text) < 5000:
                print(
                    "NOTE   : HTML is very small; "
                    "possible JS-rendered or blocked page"
                )

            print("STATUS : FETCHABLE")

    except urllib.error.HTTPError as exc:
        print(f"RESULT : HTTP {exc.code}")
        print("STATUS : HTTP_ERROR")

    except urllib.error.URLError as exc:
        print(f"RESULT : URL ERROR: {exc.reason}")
        print("STATUS : URL_ERROR")

    except Exception as exc:
        print(
            f"RESULT : {type(exc).__name__}: {exc}"
        )
        print("STATUS : ERROR")

    print()


def main():
    print("Pokemon Card Source Connectivity Test")
    print(
        "UTC:",
        datetime.now(timezone.utc).isoformat(),
    )
    print()

    for source in SOURCES:
        test_source(source)

    print("=" * 70)
    print("Source test completed.")


if __name__ == "__main__":
    main()
