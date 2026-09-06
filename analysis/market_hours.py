"""Regular-session state for the two underlying venues. Holidays are not modelled.

KRX regular session 09:00-15:30 Asia/Seoul; Nasdaq 09:30-16:00 America/New_York; both Mon-Fri.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Session:
    name: str
    tz: str
    open: time
    close: time

    @property
    def hours_label(self) -> str:
        return f"Mon–Fri {self.open:%H:%M}–{self.close:%H:%M}"


KRX = Session("KRX", "Asia/Seoul", time(9, 0), time(15, 30))
NASDAQ = Session("Nasdaq", "America/New_York", time(9, 30), time(16, 0))


@dataclass(frozen=True)
class SessionState:
    is_open: bool
    until: timedelta          # time to close if open, else time to next open
    local: datetime           # current wall-clock time at the venue

    @property
    def until_label(self) -> str:
        m = int(self.until.total_seconds() // 60)
        h, m = divmod(m, 60)
        return f"{h}h {m:02d}m" if h else f"{m}m"


def _at(day: datetime, t: time) -> datetime:
    return day.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)


def session_state(s: Session, now: datetime | None = None) -> SessionState:
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo(s.tz))
    weekday = local.weekday() < 5
    open_dt, close_dt = _at(local, s.open), _at(local, s.close)
    if weekday and open_dt <= local < close_dt:
        return SessionState(True, close_dt - local, local)
    if weekday and local < open_dt:
        return SessionState(False, open_dt - local, local)
    day = local + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return SessionState(False, _at(day, s.open) - local, local)
