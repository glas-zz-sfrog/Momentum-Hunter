from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from zoneinfo import ZoneInfo


CENTRAL_TZ = ZoneInfo("America/Chicago")


def now_central() -> datetime:
    return datetime.now(CENTRAL_TZ)


def format_central(value: datetime | None = None) -> str:
    value = value or now_central()
    if value.tzinfo is None:
        value = value.replace(tzinfo=CENTRAL_TZ)
    return value.astimezone(CENTRAL_TZ).strftime("%Y-%m-%d %I:%M %p CT")


def next_market_session(value: datetime | None = None) -> datetime:
    session = value or now_central()
    session = session.astimezone(CENTRAL_TZ) + timedelta(days=1)
    while session.weekday() >= 5:
        session += timedelta(days=1)
    return session
