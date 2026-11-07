"""Wall-clock scheduling, including a single catch-up after downtime/sleep."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def slot_at(now, interval_minutes=30):
    local = now.astimezone(VN_TZ)
    return local.replace(minute=(local.minute // interval_minutes) * interval_minutes,
                         second=0, microsecond=0)


def next_slot(now, interval_minutes=30):
    return slot_at(now, interval_minutes) + timedelta(minutes=interval_minutes)


def clock_now():
    return datetime.now(VN_TZ)
