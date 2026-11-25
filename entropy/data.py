"""Official source adapters, transactional ingestion and schedule auditing."""

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

START = date(2015, 10, 7)
DOUBLE_START = date(2021, 8, 23)
DAY = timedelta(days=1)
NY = "https://data.ny.gov/resource/d6yy-54nr.json"
ARCHIVE = "https://www.powerball.com/previous-results"
TABLES = ("powerball", "double_play")
MULTIPLIERS = (2, 3, 4, 5, 10)


@dataclass(frozen=True)
class Draw:
    day: date
    balls: tuple
    multiplier: int = None


def scheduled(day):
    return day.weekday() in (2, 5) or (day >= DOUBLE_START and day.weekday() == 0)


def draw_days(start, end):
    return {start + i * DAY for i in range((end - start).days + 1)
            if scheduled(start + i * DAY)}


def cutoff(now=None):
    eastern = ZoneInfo("America/New_York")
    now = datetime.now(eastern) if now is None else now.astimezone(eastern)
    day = now.date()
    if now.time() < time(22, 59):
        day -= DAY
    while not scheduled(day):
        day -= DAY
    return day


def connect(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS raw_sources (
            id INTEGER PRIMARY KEY,
            url TEXT NOT NULL,
            retrieved_utc TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            body BLOB NOT NULL,
            UNIQUE(url, sha256)
        );
        CREATE TABLE IF NOT EXISTS issues (
            source_id INTEGER NOT NULL REFERENCES raw_sources(id),
            game TEXT NOT NULL,
            kind TEXT NOT NULL,
            detail TEXT NOT NULL,
            PRIMARY KEY(source_id, game, kind, detail)
        );
    """)
    for table in TABLES:
        multiplier = (", multiplier INTEGER NOT NULL CHECK(multiplier IN (2,3,4,5,10))"
                      if table == "powerball" else "")
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                draw_date TEXT PRIMARY KEY NOT NULL,
                w1 INTEGER NOT NULL, w2 INTEGER NOT NULL, w3 INTEGER NOT NULL,
                w4 INTEGER NOT NULL, w5 INTEGER NOT NULL,
                red INTEGER NOT NULL CHECK(red BETWEEN 1 AND 26),
                source_id INTEGER NOT NULL REFERENCES raw_sources(id)
                {multiplier},
                CHECK(1 <= w1 AND w1 < w2 AND w2 < w3 AND
                      w3 < w4 AND w4 < w5 AND w5 <= 69)
            )
        """)
    return db


def validated_draw(day, values, multiplier=None):
    balls = tuple(int(value) for value in values)
    if (len(balls) != 6 or len(set(balls[:5])) != 5
            or any(not 1 <= ball <= 69 for ball in balls[:5])
            or not 1 <= balls[-1] <= 26):
        raise ValueError(f"invalid ball values {balls}")
    if multiplier is not None and multiplier not in MULTIPLIERS:
        raise ValueError(f"invalid Power Play multiplier {multiplier}")
    return Draw(day, (*sorted(balls[:5]), balls[-1]), multiplier)


def ny_rows(raw):
    for row in json.loads(raw):
        stamp = row.get("draw_date")
        yield "powerball", stamp, row.get("winning_numbers"), row.get("multiplier")
        if row.get("double_play_winning_numbers"):
            yield "double_play", stamp, row["double_play_winning_numbers"], None


class ArchiveParser(HTMLParser):
    """Read results cards using game-specific ball classes and dated links."""

    def __init__(self, game):
        super().__init__(convert_charrefs=True)
        self.game = game
        self.rows = []
        self.day = self.field = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "a" and "card" in classes:
            link = urlsplit(attrs.get("href", ""))
            query = parse_qs(link.query)
            if link.path == "/draw-result" and query.get("gc") == [self.game]:
                self.day = query.get("date", [""])[0]
                self.balls, self.multiplier = [], []
        elif self.day is not None:
            if set(classes) & {"white-balls", "powerball", "black-balls", "dp-powerball"}:
                self.field = self.balls
            elif "multiplier" in classes:
                self.field = self.multiplier

    def handle_data(self, value):
        value = value.strip()
        if self.field is not None and value:
            self.field.append(value)

    def handle_endtag(self, tag):
        if tag in ("div", "span"):
            self.field = None
        if tag == "a" and self.day is not None:
            table = "powerball" if self.game == "powerball" else "double_play"
            multiplier = "".join(self.multiplier).removesuffix("x")
            self.rows.append((table, self.day, " ".join(self.balls), multiplier))
            self.day = self.field = None


def archive_rows(raw, game):
    parser = ArchiveParser(game)
    parser.feed(raw.decode("utf-8"))
    parser.close()
    return parser.rows


def fetch(url):
    request = Request(url, headers={"User-Agent": "ProjectEntropy/1.0 research archive"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def issue(db, source_id, table, kind, detail):
    db.execute("INSERT OR IGNORE INTO issues VALUES (?, ?, ?, ?)",
               (source_id, table, kind, detail))


def store(db, url, raw, parser, start, end):
    digest = hashlib.sha256(raw).hexdigest()
    with db:
        db.execute("INSERT OR IGNORE INTO raw_sources VALUES (NULL, ?, ?, ?, ?)",
                   (url, datetime.now(timezone.utc).isoformat(), digest, raw))
        source_id, = db.execute(
            "SELECT id FROM raw_sources WHERE url = ? AND sha256 = ?", (url, digest)
        ).fetchone()
        try:
            rows = list(parser(raw))
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            issue(db, source_id, "source", "parse_error", str(error))
            return
        if not rows:
            issue(db, source_id, "source", "empty_response", "No results parsed")
        seen = set()
        for table, stamp, values, multiplier in rows:
            try:
                day = datetime.fromisoformat(stamp).date()
                if not start <= day <= end:
                    continue
                key = (table, day)
                if key in seen:
                    issue(db, source_id, table, "duplicate_date", str(day))
                seen.add(key)
                if not scheduled(day) or (table == "double_play" and day < DOUBLE_START):
                    raise ValueError("date outside game schedule")
                multiplier = int(multiplier) if table == "powerball" else None
                draw = validated_draw(day, values.split(), multiplier)
            except (AttributeError, TypeError, ValueError) as error:
                issue(db, source_id, table, "invalid_row", f"{stamp}: {error}")
                continue
            balls = draw.balls + ((draw.multiplier,) if table == "powerball" else ())
            columns = "w1,w2,w3,w4,w5,red" + (",multiplier" if table == "powerball" else "")
            stored = db.execute(f"SELECT {columns} FROM {table} WHERE draw_date = ?",
                                (day.isoformat(),)).fetchone()
            if stored is None:
                marks = ",".join("?" for _ in balls)
                db.execute(
                    f"INSERT INTO {table} (draw_date,source_id,{columns}) VALUES (?, ?, {marks})",
                    (day.isoformat(), source_id, *balls),
                )
            elif stored != balls:
                issue(db, source_id, table, "conflicting_result",
                      f"{day}: stored {stored}; received {balls}")


def audit(db, end):
    report = {"through": str(end), "sqlite_integrity": db.execute(
        "PRAGMA integrity_check").fetchone()[0],
        "foreign_key_violations": len(db.execute("PRAGMA foreign_key_check").fetchall()),
        "raw_responses": db.execute("SELECT count(*) FROM raw_sources").fetchone()[0],
        "raw_checksum_mismatches": [
            {"id": source_id, "url": url}
            for source_id, url, digest, body in db.execute(
                "SELECT id,url,sha256,body FROM raw_sources ORDER BY id"
            )
            if type(body) is not bytes or hashlib.sha256(body).hexdigest() != digest
        ],
        "source_issues": [dict(zip(("url", "game", "kind", "detail"), row)) for row in db.execute(
            "SELECT url,game,kind,detail FROM issues JOIN raw_sources ON id=source_id "
            "ORDER BY source_id,game,kind,detail")]}
    for table, start in zip(TABLES, (START, DOUBLE_START)):
        dates = {date.fromisoformat(row[0]) for row in db.execute(
            f"SELECT draw_date FROM {table} WHERE draw_date <= ?", (end.isoformat(),)
        )}
        expected = draw_days(start, end)
        report[table] = {
            "records": len(dates), "expected": len(expected),
            "first": str(min(dates)) if dates else None,
            "last": str(max(dates)) if dates else None,
            "missing": sorted(map(str, expected - dates)),
            "off_schedule": sorted(map(str, dates - expected)),
        }
    return report


def archive_update(db, table, start, end, download):
    game = "powerball" if table == "powerball" else "pb-double-play"
    while start <= end:
        last = min(end, start + 48 * DAY)
        url = ARCHIVE + "?" + urlencode({"gc": game, "sd": start, "ed": last + DAY})
        store(db, url, download(url), lambda raw: archive_rows(raw, game), start, last)
        start = last + DAY


def update(db, end, full=False, download=fetch):
    before = audit(db, end)
    recent = max(START, end - 48 * DAY)
    start = START if full else min(
        [recent] + [date.fromisoformat(day) for day in before["powerball"]["missing"]]
    )
    # One calendar year per request keeps each response well below the API limit.
    while start <= end:
        last = min(end, start + 364 * DAY)
        clause = f"draw_date >= '{start}T00:00:00' AND draw_date < '{last + DAY}T00:00:00'"
        url = NY + "?" + urlencode({"$where": clause, "$order": "draw_date", "$limit": 500})
        store(db, url, download(url), ny_rows, start, last)
        start = last + DAY
    # Check recent main results and repair any gaps left by the state feed.
    after_ny = audit(db, end)
    for day in after_ny["powerball"]["missing"]:
        if date.fromisoformat(day) < recent:
            archive_update(db, "powerball", date.fromisoformat(day), date.fromisoformat(day), download)
    archive_update(db, "powerball", recent, end, download)
    double_start = DOUBLE_START if full else max(DOUBLE_START, min(
        [recent] + [date.fromisoformat(day) for day in before["double_play"]["missing"]]
    ))
    archive_update(db, "double_play", double_start, end, download)
    return audit(db, end)
