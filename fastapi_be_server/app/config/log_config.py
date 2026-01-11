from fastapi import Request
# from fastapi.security import HTTPAuthorizationCredentials
# from fastapi.responses import JSONResponse
# from fastapi.background import BackgroundTask

# from enum import Enum
from datetime import datetime
from app.const import settings, LOGGER_TYPE
from app.utils.time import datatime_formatted_by_timezone

# import os
import logging
import logging.handlers
import json

# BASE_DIR = os.path.dirname(os.path.abspath(__file__))

### 서비스 데이터 로거 설정
data_logger = logging.getLogger(LOGGER_TYPE.LOGGER_INSTANCE_NAME_FOR_SERVICE_DATA)

# class ExcludeFilter(logging.Filter):
#     """ 제외 로거 필터 """
#     def filter(self, record):
#         return "ERROR:service_error_log" not in record.getMessage()


class InfoLevelOnlyFilter(logging.Filter):
    """INFO 레벨 포함 로거 필터"""

    def filter(self, record):
        return record.levelno <= logging.INFO


def setup_service_data_logger():
    """로거 생성"""

    data_logger.setLevel(logging.INFO)
    datalog_file_date = datetime.now().strftime("%Y%m%d_%H")
    # "log_file_name": f"./logs/data/{settings.LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_DATA}_{datalog_file_date}.log"
    logger_option = {
        "log_file_name": f"./logs/data/{LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_DATA}_{datalog_file_date}.log",
        "timed_rotating_when": "h",
        "timed_rotating_interval": 1,
        "timed_rotating_backup_count": 140,
    }
    # file_handler = logging.handlers.RotatingFileHandler(
    #     logger_option.get("log_file_name")
    #     , mode="a"
    # )
    file_handler = logging.handlers.TimedRotatingFileHandler(
        logger_option.get("log_file_name"),
        logger_option.get("timed_rotating_when"),
        logger_option.get("timed_rotating_interval"),
        logger_option.get("timed_rotating_backup_count"),
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter("%(message)s")
    file_handler.setFormatter(file_formatter)
    file_handler.addFilter(InfoLevelOnlyFilter())

    data_logger.addHandler(file_handler)

    return data_logger


if len(data_logger.handlers) < 1:
    """ 생성된 logger가 없으면 데이터 로깅용 logger 생성 """
    data_logger = setup_service_data_logger()
else:
    pass


async def service_data_logger(request: Request):
    # logger = logging.getLogger("log_user_info")
    # # logging.basicConfig(filename=settings.LOG_FILE, format='%(message)s', level=logging.INFO)
    # logger.setLevel(logging.INFO)
    # logger.addHandler(logging.FileHandler("test_user_info.log"))

    try:
        """ 서비스 호출 로깅 내용 """
        service_data = builder_message_for_logging(request)
        data_logger.info(service_data)

    except Exception:
        """ 예외 처리 """
        # logger.info(e)
        pass

    # 사용자 정보 점검
    # credentials = None
    # if "authorization" in request.headers:
    #     auth_header = request.headers["authorization"]
    #     if auth_header.startswith("Bearer "):
    #         credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_header.split(" ")[1])

    #         try:
    #             # 세부 테스트
    #             decoded_token = jwt.decode(
    #                     jwt=credentials.credentials,
    #                     key=settings.KC_PUBLIC_KEY,
    #                     algorithms=settings.KC_PK_ALGORITHMS,
    #                     issuer=settings.KC_ISSUER_BASE_URL,
    #                     audience=settings.KC_AUDIENCE
    #                 )

    #             res_json = await chk_revoked_token(credentials.credentials, decoded_token)
    #             user: Dict[str, Any] = decoded_token
    #             # logger.info({"user_sub":user.get("sub"), "res_json":res_json, "user":user})
    #             # logger.info({"analysis:":request.state.analysis_params})

    #         except Exception as e:
    #             # logger.info({"decoded_token_error":e})
    #             pass

    # else:
    #     credentials = "NO_AUTH"

    return


def analysis_logger(request: Request):
    """로깅 리팩토링 함수 - ASIS와 같은 이름으로 임시 작성"""

    try:
        logger = logging.getLogger(settings.LOGGER_NAME)
        # logging.basicConfig(filename=settings.LOG_FILE, format='%(message)s', level=logging.INFO)
        logger.setLevel(logging.INFO)

        # 핸들러가 없을 때만 추가
        if len(logger.handlers) < 1:
            logger.addHandler(logging.FileHandler(settings.LOG_FILE))

        """ 서비스 호출 로깅 내용 """
        service_data = builder_message_for_logging(request)

        # data_logger.info(service_data)
        logger.info(service_data)

    except Exception as e:
        """ 예외 처리 """
        logger.info(e)
        pass

    # try:
    #     logger = logging.getLogger(settings.LOGGER_NAME)
    #     # logging.basicConfig(filename=settings.LOG_FILE, format='%(message)s', level=logging.INFO)
    #     logger.setLevel(logging.INFO)
    #     logger.addHandler(logging.FileHandler("test4.log"))

    #     """ 서비스 로깅 메세지 설정 """
    #     logging_message = dict()
    #     logging_message["timestamp"] = datatime_formatted_by_timezone("y")
    #     logging_message["trace_id"] = request.state.trace_id
    #     logging_message["span_id"] = request.state.span_id
    #     logging_message["client_ip"] = request.scope.get('client')[0]
    #     logging_message["client_host"] = request.client.host
    #     logging_message["client_port"] = str(request.client.port)
    #     logging_message["device"] = request.headers.get('user-agent')
    #     logging_message["request_path"] = request.scope.get("path")
    #     logging_message["request_method"] = str(request.method).lower()
    #     logging_message["route_name"] = request.scope.get("route").name
    #     logging_message["referer"] = str(request.headers.get('referer')).lower()
    #     logging_message["analysis_params"] = request.state.analysis_params
    #     # logging_message["logger_type"] = str(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_DATA).lower()

    #     logger.info(logging_message)
    # except Exception as e:
    #     logger.info(e)
    #     pass

    return


def service_error_logger(
    logger_name: str = LOGGER_TYPE.LOGGER_INSTANCE_NAME_FOR_SERVICE_ERROR,
):
    """서비스 오류 로깅 설정"""

    logger = logging.getLogger(logger_name)
    if len(logger.handlers) < 1:
        """ 생성된 로거가 없는 경우 생성함 """

        errorlog_file_date = datetime.now().strftime("%Y%m%d")
        logger_option = {
            "log_file_name": f"./logs/error/{LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR}_{errorlog_file_date}.log",
            "timed_rotating_when": "W6",
            "timed_rotating_interval": 1,
            "timed_rotating_backup_count": 30,
        }

        file_handler = logging.handlers.TimedRotatingFileHandler(
            logger_option.get("log_file_name"),
            logger_option.get("timed_rotating_when"),
            logger_option.get("timed_rotating_interval"),
            logger_option.get("timed_rotating_backup_count"),
        )

        file_handler.setLevel(logging.ERROR)
        logging.Formatter.formatTime = formatWithTimezone
        log_formatter = logging.Formatter(
            "[%(asctime)s|%(levelname)s|%(name)s|%(filename)s:%(lineno)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(log_formatter)
        logger.addHandler(file_handler)

    return logger


def formatWithTimezone(self, record, datefmt=None):
    """timezone 값 포함한 datetime 포맷"""
    return (
        datetime.fromtimestamp(record.created)
        .astimezone()
        .isoformat(timespec="seconds")
    )


def builder_message_for_logging(request: Request, context: dict = {}):
    """서비스 로깅 메세지 설정"""
    logging_message = dict()
    logging_message["logger_type"] = str(
        LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_DATA
    ).lower()
    logging_message["timestamp"] = datatime_formatted_by_timezone("y")
    logging_message["trace_id"] = request.state.trace_id
    logging_message["span_id"] = request.state.span_id
    logging_message["client_ip"] = (
        request.scope.get("client")[0] if request.scope.get("client")[0] else ""
    )
    logging_message["client_host"] = request.client.host if request.client.host else ""
    logging_message["client_port"] = (
        str(request.client.port) if request.client.port else ""
    )
    logging_message["device"] = (
        request.headers.get("user-agent") if request.headers.get("user-agent") else ""
    )
    logging_message["request_path"] = (
        request.scope.get("path") if request.scope.get("path") else ""
    )
    logging_message["request_method"] = (
        str(request.method).lower() if str(request.method).lower() else ""
    )
    logging_message["route_name"] = (
        request.scope.get("route").name if request.scope.get("route") else ""
    )
    logging_message["referer"] = (
        str(request.headers.get("referer")).lower()
        if request.headers.get("referer")
        else ""
    )

    # 사용자 데이터 추가
    odata = (
        json.loads(str(request.state.odata).replace("'", ""))
        if request.state.odata
        else None
    )
    logging_message["oid"] = odata.get("oid") if odata.get("oid") else ""
    logging_message["gender"] = odata.get("gender") if odata.get("gender") else ""
    logging_message["ages"] = odata.get("ages") if odata.get("ages") else ""

    return logging_message


# def service_background_logger(request: Request, response: JSONResponse):
#     """ 로깅 백그라운드 작업 """
#     task = BackgroundTask(service_data_logger, request, JSONResponse)

#     return Response(content=response, status_code=response.status_code,
#                     headers=dict(response.headers), media_type=response.media_type, background=task)
