"""应用时间约定：数据库保存无时区 UTC，产品日界线使用北京时间。"""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc


def beijing_now() -> datetime:
    """返回带时区的当前北京时间，用于展示与本地业务规则。"""
    return datetime.now(APP_TIMEZONE)


def beijing_today() -> date:
    """返回当前北京时间日期，用于每日额度等日界线业务。"""
    return beijing_now().date()


def utc_day_start(local_day: date) -> datetime:
    """北京时间当天零点转换为数据库可比较的无时区 UTC 时间。"""
    return datetime.combine(local_day, time.min, tzinfo=APP_TIMEZONE).astimezone(UTC).replace(tzinfo=None)


def utc_day_range(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    """将包含首尾日期的北京时间范围转换为半开 UTC 查询区间。"""
    return utc_day_start(start_day), utc_day_start(end_day + timedelta(days=1))


def as_beijing(value: datetime | None) -> datetime | None:
    """将历史的无时区 UTC 时间安全转换为带时区的北京时间供 API 输出。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(APP_TIMEZONE)
