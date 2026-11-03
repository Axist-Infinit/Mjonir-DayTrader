"""The one clock (P9) and the NYSE calendar. Stdlib only.

Every ``now`` in ``mjonir/`` comes from ``now_et()`` / ``today_et()``. The box clock is Mountain;
``date.today()`` there is the EARLIER date for two hours every night, so it is never used here.
``--now`` text is parsed like upstream's scripts: a naive time is New York time, ``Z`` or an offset
makes it absolute, a bare ``HH:MM`` is today in New York.

Holidays and 1:00 p.m. early closes, in order of trust:
  1. ``trader/calendar.json`` (or ``TRADER_CALENDAR``), written by ``build_calendar_doc`` from
     Massive's ``/v1/marketstatus/upcoming`` and ``/now``;
  2. the seed lists copied once from upstream (2026 and 2027, nyse.com, read 2026-10-13);
  3. outside the covered years, the NYSE rules (``rule_holidays``, ``rule_early_closes``), so a past
     session can be LABELLED; an early close from the rules is confirmed from the bar count (42 vs 78)
     and recorded ``verified`` or ``rule_only``.
"""

import datetime as _dt
import json
import os
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = _dt.timezone.utc
OPEN = _dt.time(9, 30)
CLOSE = _dt.time(16, 0)
EARLY = _dt.time(13, 0)
BAR_MIN = 5
FULL_BARS = 78     # 9:30 to 16:00 in 5-minute bars
EARLY_BARS = 42    # 9:30 to 13:00
DEFAULT_PATH = os.path.join("trader", "calendar.json")

# Copied once from upstream (trader-*/ hold the same lists; nyse.com read 2026-10-13).
SEED_HOLIDAYS = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King, Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth National Independence Day",
    "2026-07-03": "Independence Day (observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day",
    "2027-01-18": "Martin Luther King, Jr. Day",
    "2027-02-15": "Washington's Birthday",
    "2027-03-26": "Good Friday",
    "2027-05-31": "Memorial Day",
    "2027-06-18": "Juneteenth National Independence Day (observed)",
    "2027-07-05": "Independence Day (observed)",
    "2027-09-06": "Labor Day",
    "2027-11-25": "Thanksgiving Day",
    "2027-12-24": "Christmas Day (observed)",
}
SEED_EARLY_CLOSE = {  # 1:00 p.m. ET
    "2026-11-27": "day after Thanksgiving",
    "2026-12-24": "Christmas Eve",
    "2027-11-26": "day after Thanksgiving",
}
SEED_YEARS = (2026, 2027)
#: One-off closures the rules cannot know (the exchange's own notices).
SPECIAL_CLOSURES = {
    "2012-10-29": "Hurricane Sandy",
    "2012-10-30": "Hurricane Sandy",
    "2018-12-05": "National Day of Mourning (George H. W. Bush)",
    "2025-01-09": "National Day of Mourning (Jimmy Carter)",
}


class CalendarError(ValueError):
    pass


# ---------------------------------------------------------------- the clock

def parse_now(text=None, clock=None):
    """``--now`` text (or the real clock) -> an aware New York datetime.

    ``clock`` (tests): an aware or naive datetime (naive = New York), a string parsed like ``text``,
    or a callable returning either."""
    if text:
        t = str(text).strip()
        if t.upper().endswith(" ET"):
            t = t[:-3].strip()
        if len(t) <= 5 and ":" in t:
            t = "%s %s" % (now_et(clock).date().isoformat(), t.zfill(5))
        try:
            dt = _dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
        except ValueError:
            raise CalendarError('--now wants a New York time like "2026-10-19 10:15" (or ...Z for UTC), not %r'
                                % text)
        return dt.replace(tzinfo=ET) if dt.tzinfo is None else dt.astimezone(ET)
    if clock is None:
        return _dt.datetime.now(UTC).astimezone(ET)
    c = clock() if callable(clock) else clock
    if isinstance(c, str):
        return parse_now(c)
    if isinstance(c, _dt.datetime):
        return c.replace(tzinfo=ET) if c.tzinfo is None else c.astimezone(ET)
    raise CalendarError("clock must give a datetime or a --now string")


def now_et(clock=None):
    """The one clock: an aware datetime in New York."""
    return parse_now(None, clock)


def today_et(clock=None):
    """Today's date in New York (never the box's Mountain date)."""
    return now_et(clock).date()


def as_date(d):
    if isinstance(d, _dt.datetime):
        return d.astimezone(ET).date() if d.tzinfo else d.date()
    if isinstance(d, _dt.date):
        return d
    try:
        return _dt.date.fromisoformat(str(d)[:10])
    except ValueError:
        raise CalendarError("not a date: %r" % (d,))


def ms_of(dt):
    return int(round(dt.timestamp() * 1000))


def et_of_ms(ms):
    return _dt.datetime.fromtimestamp(int(ms) / 1000.0, tz=ET)


def tz_label(d):
    """('EDT', -14400) or ('EST', -18000) for noon New York on date d."""
    noon = _dt.datetime.combine(as_date(d), _dt.time(12, 0), tzinfo=ET)
    off = int(noon.utcoffset().total_seconds())
    return noon.tzname(), off


# ---------------------------------------------------------------- the NYSE rules

def easter(year):
    """Gregorian Easter Sunday (the anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return _dt.date(year, month, day)


def _nth_weekday(year, month, weekday, n):
    d = _dt.date(year, month, 1)
    d += _dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + _dt.timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    d = _dt.date(year + (month == 12), month % 12 + 1, 1) - _dt.timedelta(days=1)
    return d - _dt.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d, saturday_to_friday=True):
    if d.weekday() == 5:
        return d - _dt.timedelta(days=1) if saturday_to_friday else None
    if d.weekday() == 6:
        return d + _dt.timedelta(days=1)
    return d


def rule_holidays(year):
    """{date: name} by the NYSE rules for one year (plus the one-off closures)."""
    out = {}

    def put(d, name):
        if d is not None:
            out[d.isoformat()] = name
    ny = _dt.date(year, 1, 1)
    put(_observed(ny, saturday_to_friday=False), "New Year's Day" + (" (observed)" if ny.weekday() == 6 else ""))
    put(_nth_weekday(year, 1, 0, 3), "Martin Luther King, Jr. Day")
    put(_nth_weekday(year, 2, 0, 3), "Washington's Birthday")
    put(easter(year) - _dt.timedelta(days=2), "Good Friday")
    put(_last_weekday(year, 5, 0), "Memorial Day")
    if year >= 2022:
        j = _dt.date(year, 6, 19)
        put(_observed(j), "Juneteenth National Independence Day" + (" (observed)" if j.weekday() >= 5 else ""))
    j4 = _dt.date(year, 7, 4)
    put(_observed(j4), "Independence Day" + (" (observed)" if j4.weekday() >= 5 else ""))
    put(_nth_weekday(year, 9, 0, 1), "Labor Day")
    put(_nth_weekday(year, 11, 3, 4), "Thanksgiving Day")
    x = _dt.date(year, 12, 25)
    put(_observed(x), "Christmas Day" + (" (observed)" if x.weekday() >= 5 else ""))
    for k, v in SPECIAL_CLOSURES.items():
        if k.startswith("%d-" % year):
            out[k] = v
    return dict(sorted(out.items()))


def rule_early_closes(year):
    """{date: label} of the 1:00 p.m. closes by rule: the day after Thanksgiving, and Dec 24 and
    Jul 3 when they fall Monday to Thursday. A LABEL for past sessions; the bar count confirms it."""
    out = {}
    tg = _nth_weekday(year, 11, 3, 4)
    out[(tg + _dt.timedelta(days=1)).isoformat()] = "day after Thanksgiving"
    for d, name in ((_dt.date(year, 12, 24), "Christmas Eve"), (_dt.date(year, 7, 3), "Independence Day eve")):
        if d.weekday() <= 3:
            out[d.isoformat()] = name
    return dict(sorted(out.items()))


# ---------------------------------------------------------------- the vendor's calendar

def calendar_path():
    return os.environ.get("TRADER_CALENDAR") or DEFAULT_PATH


def build_calendar_doc(client, clock=None, rule_years_ahead=1):
    """trader/calendar.json from ``/v1/marketstatus/upcoming`` and ``/now``, over the seeds.

    The vendor lists the NEXT holidays only (on 2026-11-02: 2026-11-26 to 2027-09-06). Each year gets
    a ``basis``: ``seed`` (upstream's nyse.com lists), ``vendor`` (seen in the upcoming list),
    ``rule`` (the NYSE rules, for the `rule_years_ahead` years after the vendor's last listed year;
    nyse.com publishes about three years ahead, so check it). ``covered_years`` are the years whose
    whole list the doc holds: those years stop warning in the scripts. ``known_through`` is the
    vendor's last listed date."""
    now = now_et(clock)
    upcoming = client.market_status_upcoming()
    status = client.market_status_now()
    holidays, early, rows = {}, {}, 0
    for r in upcoming:
        if not isinstance(r, dict) or str(r.get("exchange") or "").upper() not in ("NYSE", "NASDAQ"):
            continue
        d, name, st = str(r.get("date") or "")[:10], str(r.get("name") or "").strip(), str(r.get("status") or "")
        try:
            _dt.date.fromisoformat(d)
        except ValueError:
            continue
        rows += 1
        if st == "closed":
            holidays.setdefault(d, name)
        elif st == "early-close":
            early.setdefault(d, name)
    if not rows:
        from .massive import Refused
        raise Refused("marketstatus/upcoming: no NYSE or NASDAQ rows; the calendar was not rebuilt")
    known = max(list(holidays) + list(early))
    basis = {}
    for y in SEED_YEARS:
        basis[y] = "seed"
    for d in list(holidays) + list(early):
        y = int(d[:4])
        basis[y] = "seed+vendor" if y in SEED_YEARS else "vendor"
    merged_h = dict(SEED_HOLIDAYS)
    merged_e = dict(SEED_EARLY_CLOSE)
    for y in range(int(known[:4]) + 1, int(known[:4]) + 1 + int(rule_years_ahead)):
        if y in basis:
            continue
        merged_h.update(rule_holidays(y))
        merged_e.update(rule_early_closes(y))
        basis[y] = "rule"
    merged_h.update(holidays)
    merged_e.update(early)
    # a vendor-only year is whole only when the vendor reaches its last holiday (Christmas)
    covered = sorted(y for y, b in basis.items()
                     if b != "vendor" or known >= _observed(_dt.date(y, 12, 25)).isoformat())
    return {"created_by": "mjonir.calendar", "generated_at": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "massive /v1/marketstatus/upcoming + /now, over the upstream seeds and the NYSE rules",
            "holidays": dict(sorted(merged_h.items())), "early_closes": dict(sorted(merged_e.items())),
            "covered_years": covered, "basis": {str(y): b for y, b in sorted(basis.items())},
            "known_through": known,
            "vendor": {"holidays": len(holidays), "early_closes": len(early), "rows": rows},
            "market_now": {"market": status.get("market"), "serverTime": status.get("serverTime"),
                           "exchanges": status.get("exchanges")},
            "note": "Years with basis 'rule' come from the NYSE rules (a one-off closure cannot be known): "
                    "check nyse.com. Years outside covered_years fall back to the rules with a warning."}


# ---------------------------------------------------------------- the calendar

class Calendar(object):
    def __init__(self, holidays=None, early_closes=None, covered_years=None, doc=None):
        self.holidays = dict(SEED_HOLIDAYS if holidays is None else holidays)
        self.early_closes = dict(SEED_EARLY_CLOSE if early_closes is None else early_closes)
        self.covered_years = set(SEED_YEARS if covered_years is None else covered_years)
        self.doc = doc

    @classmethod
    def load(cls, path=None):
        """The seeds, extended by trader/calendar.json (or TRADER_CALENDAR) when it exists."""
        cal = cls()
        p = path or calendar_path()
        try:
            with open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            return cal
        if isinstance(doc, dict):
            cal.holidays.update(doc.get("holidays") or {})
            cal.early_closes.update(doc.get("early_closes") or {})
            cal.covered_years |= set(int(y) for y in doc.get("covered_years") or ())
            cal.doc = doc
        return cal

    # -- one day
    def holiday_name(self, d):
        d = as_date(d)
        iso = d.isoformat()
        if iso in self.holidays:
            return self.holidays[iso]
        if d.year not in self.covered_years:
            return rule_holidays(d.year).get(iso)
        return None

    def why_closed(self, d):
        d = as_date(d)
        if d.weekday() >= 5:
            return "weekend"
        name = self.holiday_name(d)
        return ("NYSE holiday: " + name) if name else None

    def is_session(self, d):
        return self.why_closed(d) is None

    def is_early_close(self, d):
        d = as_date(d)
        iso = d.isoformat()
        if iso in self.early_closes:
            return True
        return d.year not in self.covered_years and iso in rule_early_closes(d.year)

    def early_close_label(self, d):
        d = as_date(d)
        return self.early_closes.get(d.isoformat()) or (rule_early_closes(d.year).get(d.isoformat())
                                                        if d.year not in self.covered_years else None)

    def early_close_basis(self, d, n_bars=None):
        """'calendar' (vendor or seed list), 'verified' (rule, and the bar count agrees), 'rule_only'
        (rule, nothing to confirm it), 'contradicted' (rule says early, the bars say a full day), or
        None (not an early close)."""
        d = as_date(d)
        if d.isoformat() in self.early_closes:
            return "calendar"
        if not self.is_early_close(d):
            return None
        if n_bars is None:
            return "rule_only"
        return "verified" if n_bars <= EARLY_BARS else "contradicted"

    def session_bounds(self, d):
        """(open, close) as aware New York datetimes, or None on a closed day."""
        d = as_date(d)
        if not self.is_session(d):
            return None
        return (_dt.datetime.combine(d, OPEN, tzinfo=ET),
                _dt.datetime.combine(d, EARLY if self.is_early_close(d) else CLOSE, tzinfo=ET))

    def expected_bars(self, d, interval_min=BAR_MIN):
        """78 (or 42 on an early close) five-minute bars; 390 / 210 one-minute bars."""
        b = self.session_bounds(d)
        if b is None:
            raise CalendarError("%s is not a session (%s)" % (as_date(d), self.why_closed(d)))
        return int((b[1] - b[0]).total_seconds() // (60 * interval_min))

    # -- ranges
    def sessions_between(self, a, b):
        """Every session from a to b, both included, oldest first."""
        a, b = as_date(a), as_date(b)
        out, d = [], a
        while d <= b:
            if self.is_session(d):
                out.append(d)
            d += _dt.timedelta(days=1)
        return out

    def prev_session(self, d):
        d = as_date(d) - _dt.timedelta(days=1)
        for _ in range(30):
            if self.is_session(d):
                return d
            d -= _dt.timedelta(days=1)
        raise CalendarError("no session in the 30 days before %s" % d)

    def next_session(self, d):
        d = as_date(d) + _dt.timedelta(days=1)
        for _ in range(30):
            if self.is_session(d):
                return d
            d += _dt.timedelta(days=1)
        raise CalendarError("no session in the 30 days after %s" % d)

    def sessions_back(self, end, n):
        """The n sessions ending at `end` (included when it is a session), oldest first."""
        d = as_date(end)
        out = []
        if self.is_session(d):
            out.append(d)
        while len(out) < n:
            d = self.prev_session(d)
            out.append(d)
        return sorted(out)

    def last_complete_session(self, clock=None):
        """The newest session whose regular hours are over as of now (today after its close)."""
        now = now_et(clock)
        b = self.session_bounds(now.date())
        if b and now >= b[1]:
            return now.date()
        return self.prev_session(now.date())

    def session_complete(self, d, clock=None):
        """True once a session's date is strictly before today in New York: extended hours are over
        too, so nothing about it can still change (the cache's rule)."""
        return as_date(d) < today_et(clock)

    # -- bars
    def rth_filter(self, rows, t_key="t"):
        """Rows (``t`` = bar START in ms) inside the regular session of their own New York date,
        on the 5-minute grid of that session's open."""
        out = []
        bounds = {}
        for r in rows:
            et = et_of_ms(r[t_key])
            d = et.date()
            if d not in bounds:
                bounds[d] = self.session_bounds(d)
            b = bounds[d]
            if b is None or not (b[0] <= et < b[1]):
                continue
            out.append(r)
        return out
