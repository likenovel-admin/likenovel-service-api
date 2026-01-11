from fastapi import FastAPI, Request, Response, status
# from fastapi.middleware.cors import CORSMiddleware  # Nginx에서 CORS 처리
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import MutableHeaders

from app.const import settings, ErrorMessages
from app.tags import tags_metadata
from app.exceptions import CustomResponseException

import uuid
import logging
import importlib
import pkgutil
from pathlib import Path
from fastapi import APIRouter
import app.routers as routers_pkg


be_app = FastAPI(openapi_tags=tags_metadata)  # swagger
# be_app = FastAPI(
#     # docs_url=None,
#     redoc_url=None,
#     # openapi_url=None
# )

# 허용할 도메인(CORS) - Nginx에서 CORS 처리하므로 주석 처리
# _allowed_origins = list(set([
#     "http://localhost:3000",
#     "https://localhost:3000",
#     "http://localhost:3001",
#     "https://localhost:3001",
#     "http://localhost:3002",
#     "https://localhost:3002",
#     "http://cloud.aiaracorp.com:3300",
#     "http://dadmin-likenovel.aiaracorp.com",
#     "https://dadmin-likenovel.aiaracorp.com",
#     "http://dlikenovel-partner.aiaracorp.com",
#     "https://dlikenovel-partner.aiaracorp.com",
#     "http://duser-likenovel.aiaracorp.com",
#     "http://duser-likenovel.aiaracorp.com:3300",
#     "https://duser-likenovel.aiaracorp.com",
#     settings.FE_WWW_DOMAIN,
#     settings.FE_DOMAIN,
# ]))

# be_app.add_middleware(
#     CORSMiddleware,
#     allow_origins=_allowed_origins,
#     allow_credentials=True,
#     allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
#     allow_headers=["*"],
# )


@be_app.exception_handler(CustomResponseException)
async def custom_response_exception_handler(
    request: Request, exc: CustomResponseException
):
    content = dict()
    if exc.code:
        content["code"] = exc.code
    if exc.message:
        content["message"] = exc.message

    return JSONResponse(
        content=content, status_code=exc.status_code, media_type="application/json"
    )


# 커스텀 예외 생성(pydantic)
@be_app.exception_handler(RequestValidationError)
async def custom_validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    # 사용자 validation 규칙이 추가된 값에 한해 별도 422 관련 커스텀 코드 지정
    errors = exc.errors()

    for error in errors:
        loc = error.get("loc", [])
        error_type = error.get("type", "")

        # 특정 필드에 대한 커스텀 메시지
        if "email" in loc:
            message = ErrorMessages.INVALID_EMAIL_FORMAT
            break
        elif "password" in loc:
            message = ErrorMessages.INVALID_PASSWORD_FORMAT
            break
        # 필수 값 누락 (missing)
        elif error_type == "missing":
            field_name = loc[-1] if loc else "unknown"
            message = ErrorMessages.required_field_missing(field_name)
            break
        # 타입 불일치
        elif error_type in [
            "int_parsing",
            "float_parsing",
            "bool_parsing",
            "string_type",
            "int_type",
        ]:
            field_name = loc[-1] if loc else "unknown"
            message = ErrorMessages.invalid_data_type(field_name)
            break
        # 기타 validation 에러
        else:
            field_name = loc[-1] if loc else "unknown"
            error_msg = error.get("msg", "유효하지 않은 값")
            message = ErrorMessages.invalid_field_value(field_name, error_msg)
            break
    else:
        # 에러가 없거나 모든 에러를 처리하지 못한 경우
        message = ErrorMessages.INVALID_REQUEST_DATA

    raise CustomResponseException(
        status_code=status.HTTP_400_BAD_REQUEST,
        message=message,
    )


## 미들웨어를 사용해 traceId 발급
class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        """
        trace_id, span_id 생성
        :param request:
        :param call_next:
        :return:
        """

        # 요청 파라미터 읽기
        params = dict()
        if request.query_params:
            params = dict(request.query_params)

        # 요청 바디 읽기
        body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.json()
            except Exception:
                pass

        # 요청 상태에 파라미터 저장
        request.state.params = params
        request.state.body = body
        request.state.analysis_params = params if params is not None else body

        if request.headers.get("trace_id") is None:
            trace_id = str(uuid.uuid4().hex)  # traceId 생성
        else:
            trace_id = request.headers.get("trace_id")

        span_id = uuid.uuid4().int >> 64

        # 요청 상태에 trace_id 저장
        request.state.trace_id = trace_id
        # 요청 상태에 span_id 저장
        request.state.span_id = str(f"{span_id:016x}")

        request.state.odata = request.headers.get("odata")

        # 요청을 처리한 후 응답을 받음
        response = await call_next(request)

        # 응답 헤더에 traceId를 추가
        response.headers["trace_id"] = trace_id

        # return response

        res_body = b""
        async for chunk in response.body_iterator:
            res_body += chunk

        headers = MutableHeaders(response.headers)

        return Response(
            content=res_body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )


# TraceId 미들웨어 추가
be_app.add_middleware(TraceIdMiddleware)

# 데이터 분석용 파일 로그
# import logging
# logger = logging.getLogger(settings.LOGGER_NAME)
# logging.basicConfig(filename=settings.LOG_FILE, format='%(message)s', level=logging.INFO)


def auto_include_routers(app: FastAPI) -> None:
    """
    app.routers 패키지 내 모든 모듈(하위 디렉토리 포함)을 순회하며 `router` 심볼을 자동 등록.
    파일명이 *_query.py / *_command.py 인 경우 prefix를 각각 /v1/query / /v1/command 로 설정.
    그 외는 prefix 없이 등록.
    """
    routers_path = Path(routers_pkg.__path__[0])

    for module_info in pkgutil.walk_packages(
        path=[str(routers_path)], prefix="app.routers."
    ):
        name = module_info.name

        # __init__ 파일은 스킵
        if name.endswith("__init__"):
            continue

        try:
            module = importlib.import_module(name)
        except Exception as e:
            logging.warning(f"Failed to import module {name}: {e}")
            continue

        router_obj = getattr(module, "router", None)
        if isinstance(router_obj, APIRouter):
            # 모듈 이름의 마지막 부분으로 prefix 결정
            module_basename = name.split(".")[-1]
            if module_basename.endswith("_query"):
                prefix = "/v1/query"
            elif module_basename.endswith("_command"):
                prefix = "/v1/command"
            else:
                prefix = ""
            app.include_router(router_obj, prefix=prefix)


# routing(URL) 자동 등록
auto_include_routers(be_app)


@be_app.get("/health")
async def health_check():
    return {"status": "ok"}
