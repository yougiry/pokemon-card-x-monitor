import html
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

VERSION = "3C3-STATUS-QUEUE-DRY-RUN"

JST = ZoneInfo("Asia/Tokyo")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0 Safari/537.36"
)


TEST_URLS = [
    {
        "retailer": "ポケモンカード公式",
        "url": "https://www.pokemon-card.com/info/005069.html",
    },
    {
        "retailer": "GEO",
        "url": "https://geo-online.co.jp/news/783",
    },
    {
        "retailer": "GEO",
        "url": "https://geo-online.co.jp/news/785",
    },
]


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


START_LABELS = [
    "応募受付開始",
    "応募開始",
    "受付開始",
    "抽選受付開始",
    "予約受付開始",
    "予約開始",
]


END_LABELS = [
    "応募受付終了",
    "応募終了",
    "応募締切",
    "応募〆切",
    "受付終了",
    "受付締切",
    "抽選受付終了",
    "予約受付終了",
    "予約締切",
]


PERIOD_LABELS = [
    "応募期間は",
    "応募期間",
    "応募受付期間",
    "受付期間",
    "抽選受付期間",
    "抽選期間",
    "予約受付期間",
]


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
            "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
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


def clean_text(value):
    value = re.sub(
        r"<script\b.*?</script>|"
        r"<style\b.*?</style>|"
        r"<!--.*?-->",
        " ",
        value,
        flags=re.I | re.S,
    )

    value = re.sub(
        r"<br\s*/?>",
        "\n",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"</(?:p|div|li|tr|h[1-6])>",
        "\n",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"<[^>]+>",
        " ",
        value,
    )

    value = html.unescape(value)

    value = value.replace("　", " ")

    value = re.sub(
        r"[ \t]+",
        " ",
        value,
    )

    value = re.sub(
        r"\n\s*\n+",
        "\n",
        value,
    )

    return value.strip()




def parse_date_match(match, default_year):

    year = (

        int(match.group(1))

        if match.group(1)

        else default_year

    )

    month = int(match.group(2))

    day = int(match.group(3))

    hour = (

        int(match.group(4))

        if match.group(4)

        else 0

    )

    minute = (

        int(match.group(5))

        if match.group(5)

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

        first = groups[0:5]

        second = groups[5:10]

        class MatchProxy:

            def __init__(self, values):

                self.values = values

            def group(self, number):

                return self.values[number - 1]

        start = parse_date_match(

            MatchProxy(first),

            now.year,

        )

        end = parse_date_match(

            MatchProxy(second),

            now.year,

        )

        if start:

            result["application_start"] = start.isoformat()

        if end:

            result["application_end"] = end.isoformat()

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

        if now <= end:

            return "open"

        return "closed"

    if start:

        if now < start:

            return "upcoming"

        return "unknown"

    return "unknown"


def find_context_lines(text):
    keywords = [
        "応募",
        "受付",
        "抽選",
        "予約",
        "販売期間",
        "販売開始",
        "締切",
    ]

    lines = []

    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        if any(
            keyword in line
            for keyword in keywords
        ):
            lines.append(line)

    return lines[:30]


def format_dt(value):
    if not value:
        return "None"

    return value.strftime(
        "%Y-%m-%d %H:%M JST"
    )


def inspect_url(item):
    print()
    print("=" * 72)

    print(
        "RETAILER:",
        item["retailer"],
    )

    print(
        "URL:",
        item["url"],
    )

    try:
        page = fetch(
            item["url"]
        )

    except urllib.error.HTTPError as exc:
        print(
            "FETCH:",
            f"HTTP {exc.code}",
        )

        return

    except Exception as exc:
        print(
            "FETCH ERROR:",
            type(exc).__name__,
            exc,
        )

        return

    print("FETCH: HTTP 200")

    text = clean_text(page)

    now = datetime.now(JST)

    start, end, raw = (
        extract_application_period(
            text,
            now,
        )
    )

    status = determine_status(
        start,
        end,
        now,
    )

    print(
        "NOW:",
        format_dt(now),
    )

    print(
        "APPLICATION START:",
        format_dt(start),
    )

    print(
        "APPLICATION END:",
        format_dt(end),
    )

    print(
        "STATUS:",
        status,
    )

    print(
        "MATCHED TEXT:",
        raw,
    )

    print()
    print(
        "--- RELEVANT TEXT ---"
    )

    lines = find_context_lines(
        text
    )

    if not lines:
        print(
            "(no relevant lines found)"
        )

    for line in lines:
        print(
            line[:500]
        )


def main():
    print(
        "Pokemon Card Monitor "
        + VERSION
    )

    print(
        "DIAGNOSTIC ONLY"
    )

    print(
        "Buffer/X投稿なし"
    )

    print(
        "state変更なし"
    )

    for item in TEST_URLS:
        inspect_url(
            item
        )

    print()
    print("=" * 72)

    print(
        "V3-C2 diagnostic completed."
    )


if __name__ == "__main__":
    main()
