from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.const import settings

"""
시간 관련 유틸 함수 모음
"""


def get_cur_time(format: str):
    if format == "iso":
        now = (
            datetime.now(ZoneInfo(settings.KOREA_TIMEZONE))
            .isoformat()
            .split("+")[0]
            .split(".")[0]
        )
    elif format == "dt":
        now = datetime.now(ZoneInfo(settings.KOREA_TIMEZONE))

    return now


def get_full_age(date: str):
    current_date = get_cur_time(format="dt")
    cmp_date = datetime.strptime(date, "%Y-%m-%d")

    age = (
        current_date.year
        - cmp_date.year
        - ((current_date.month, current_date.day) < (cmp_date.month, cmp_date.day))
    )

    return age


def convert_to_kor_time(format: datetime):
    dt = format + timedelta(hours=9)

    return dt


def datatime_formatted_by_timezone(
    display_tz_yn: str = "y", tz_info: str = "Asia/Seoul"
) -> datetime:
    """
    타임존, UTC 시간
    :param display_tz_yn:
    :param tz_info:
    :return:
    """
    if tz_info is not None and tz_info.lower() != "utc":
        """ Timezone 시간 """
        if display_tz_yn.lower() != "y":
            """ 타임존 정보 제거 """
            formatted_datetime = datetime.now(ZoneInfo(tz_info)).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
        else:
            """ 타임존 정보 포함 """
            formatted_datetime = (
                datetime.now(ZoneInfo(tz_info)).replace(microsecond=0).isoformat()
            )
    else:
        """ UTC 시간 """
        formatted_datetime = datetime.utcnow().isoformat()

    return formatted_datetime


def utc_to_local(utc_datetime: datetime, timezone: str = "Asia/Seoul") -> datetime:
    return utc_datetime.replace(tzinfo=ZoneInfo(timezone))


def local_to_utc(local_datetime: datetime):
    return local_datetime.astimezone(ZoneInfo("UTC"))
