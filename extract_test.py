import html
import re
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse


VERSION = "V3-B1"

SOURCES = [
    {
        "name": "GEO",
        "url": "https://geo-online.co.jp/news/",
        "domains": ["geo-online.co.jp"],
    },
    {
        "name": "三洋堂書店",
        "url": (
            "https://www.sanyodo.co.jp/news/"
            "evt_lottery-sale?tags%5B%5D=5086"
        ),
        "domains": ["sanyodo.co.jp"],
    },
    {
        "name": "SHIBUYA TSUTAYA",
        "url": "https://shibuyatsutaya.tsite.jp/",
        "domains": ["shibuyatsutaya.tsite.jp"],
    },
]


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)


POKEMON_KEYWORDS = [
    "ポケモンカード",
    "ポケモンカードゲーム",
    "ポケカ",
    "pokemon card",
    "pokémon card",
]


SALE_KEYWORDS = [
    "抽選",
    "予約",
    "受注",
    "招待",
    "追加販売",
    "再販売",
    "再販",
    "再入荷",
    "入荷",
    "販売",
    "発売",
]


EXCLUDE_KEYWORDS = [
    "大会",
    "シティリーグ",
    "チャンピオンズリーグ",
    "pjcs",
    "イベント参加",
    "対戦会",
    "交流会",
    "ジムバトル",
    "トレーナーズリーグ",
]


def fetch(url):
    request = urllib.request.Request(
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
        request,
        timeout=30,
    ) as response:

        raw = response.read()

        charset = response.headers.get_content_charset()

        if not charset:
            charset = "utf-8"

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


def normalize(value):
    return clean_text(value).lower()


def contains_pokemon(text):
    lower = text.lower()

    return any(
        keyword.lower() in lower
        for keyword in POKEMON_KEYWORDS
    )


def contains_sale(text):
    lower = text.lower()

    return any(
        keyword.lower() in lower
        for keyword in SALE_KEYWORDS
    )


def is_excluded(text):
    lower = text.lower()

    return any(
        keyword.lower() in lower
        for keyword in EXCLUDE_KEYWORDS
    )


def allowed_domain(url, domains):
    host = urlparse(url).netloc.lower()

    return any(
        host == domain
        or host.endswith("." + domain)
        for domain in domains
    )


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
            ("http://", "https://")
        ):
            continue

        if not allowed_domain(
            url,
            source["domains"],
        ):
            continue

        key = (url, title)

        results[key] = {
            "title": title,
            "url": url,
        }

    return list(results.values())


def score_link(item):
    text = item["title"]

    score = 0

    if contains_pokemon(text):
        score += 10

    if contains_sale(text):
        score += 5

    if is_excluded(text):
        score -= 20

    return score


def inspect_detail(source, item):
    result = {
        "detail_status": "not_checked",
        "pokemon": False,
        "sale": False,
        "excluded": False,
        "detail_chars": 0,
        "sample": "",
    }

    try:
        page = fetch(item["url"])
        text = clean_text(page)

        result["detail_status"] = "fetched"
        result["detail_chars"] = len(text)

        combined = (
            item["title"]
            + " "
            + text
        )

        result["pokemon"] = (
            contains_pokemon(combined)
        )

        result["sale"] = (
            contains_sale(combined)
        )

        result["excluded"] = (
            is_excluded(combined)
        )

        # ログが巨大化しないよう先頭500文字だけ
        result["sample"] = text[:500]

    except urllib.error.HTTPError as exc:
        result["detail_status"] = (
            f"http_{exc.code}"
        )

    except Exception as exc:
        result["detail_status"] = (
            f"error:{type(exc).__name__}"
        )

    return result


def find_candidates(source):
    print()
    print("=" * 72)
    print(f"SOURCE: {source['name']}")
    print(f"INDEX : {source['url']}")

    page = fetch(source["url"])

    links = extract_links(
        source,
        page,
    )

    print(
        f"Internal links extracted: "
        f"{len(links)}"
    )

    # 一覧タイトルだけで有力なものを先に調査
    ranked = sorted(
        links,
        key=score_link,
        reverse=True,
    )

    interesting = []

    # 全リンクを叩かない。
    # タイトルに販売/ポケカ系語があるリンクを優先。
    for item in ranked:
        score = score_link(item)

        if score <= 0:
            continue

        interesting.append(item)

    # タイトルが弱いサイト用に上位リンクも少量見る
    if len(interesting) < 10:
        for item in ranked[:20]:
            if item not in interesting:
                interesting.append(item)

            if len(interesting) >= 20:
                break

    # 負荷防止
    interesting = interesting[:20]

    print(
        f"Detail pages to inspect: "
        f"{len(interesting)}"
    )

    matches = []

    for number, item in enumerate(
        interesting,
        start=1,
    ):
        print(
            f"  [{number}/{len(interesting)}] "
            f"{item['title'][:70]}"
        )

        detail = inspect_detail(
            source,
            item,
        )

        combined_ok = (
            detail["pokemon"]
            and detail["sale"]
            and not detail["excluded"]
        )

        if combined_ok:
            matches.append(
                {
                    **item,
                    **detail,
                }
            )

    print()
    print(
        f"POKEMON SALE MATCHES: "
        f"{len(matches)}"
    )

    for index, item in enumerate(
        matches,
        start=1,
    ):
        print("-" * 72)
        print(f"MATCH #{index}")
        print(f"TITLE : {item['title']}")
        print(f"URL   : {item['url']}")
        print(
            f"DETAIL: {item['detail_status']}"
        )
        print(
            f"CHARS : {item['detail_chars']}"
        )
        print(
            f"SAMPLE: {item['sample']}"
        )

    return matches


def main():
    print(
        f"Pokemon Card Extraction Test "
        f"{VERSION}"
    )

    print(
        "DRY RUN - no Buffer/X posts"
    )

    print(
        "DRY RUN - state.json unchanged"
    )

    total = 0

    for source in SOURCES:
        try:
            matches = find_candidates(
                source
            )

            total += len(matches)

        except Exception as exc:
            print()
            print(
                f"SOURCE ERROR "
                f"{source['name']}: "
                f"{type(exc).__name__}: {exc}"
            )

    print()
    print("=" * 72)
    print(
        f"TOTAL MATCHES: {total}"
    )
    print(
        "V3-B1 extraction test completed."
    )


if __name__ == "__main__":
    main()
