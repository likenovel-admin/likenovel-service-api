import asyncio
import unittest
import sys
from types import ModuleType, SimpleNamespace


fastapi_stub = ModuleType("fastapi")
fastapi_stub.status = SimpleNamespace(
    HTTP_400_BAD_REQUEST=400,
    HTTP_401_UNAUTHORIZED=401,
    HTTP_403_FORBIDDEN=403,
    HTTP_404_NOT_FOUND=404,
    HTTP_422_UNPROCESSABLE_ENTITY=422,
)
sys.modules.setdefault("fastapi", fastapi_stub)

sqlalchemy_stub = ModuleType("sqlalchemy")
sqlalchemy_stub.RowMapping = object
sqlalchemy_stub.text = lambda value: value
sys.modules.setdefault("sqlalchemy", sqlalchemy_stub)

sqlalchemy_exc_stub = ModuleType("sqlalchemy.exc")
sqlalchemy_exc_stub.OperationalError = Exception
sqlalchemy_exc_stub.SQLAlchemyError = Exception
sys.modules.setdefault("sqlalchemy.exc", sqlalchemy_exc_stub)

sqlalchemy_ext_stub = ModuleType("sqlalchemy.ext")
sys.modules.setdefault("sqlalchemy.ext", sqlalchemy_ext_stub)

sqlalchemy_asyncio_stub = ModuleType("sqlalchemy.ext.asyncio")
sqlalchemy_asyncio_stub.AsyncSession = object
sys.modules.setdefault("sqlalchemy.ext.asyncio", sqlalchemy_asyncio_stub)

const_stub = ModuleType("app.const")
const_stub.CommonConstants = SimpleNamespace(COMPANY_LIKENOVEL="라이크노벨")
const_stub.ErrorMessages = SimpleNamespace(
    EXPIRED_ACCESS_TOKEN="expired",
    FORBIDDEN="forbidden",
    LOGIN_REQUIRED="login required",
)
const_stub.LOGGER_TYPE = SimpleNamespace(LOGGER_FILE_NAME_FOR_SERVICE_ERROR="test.log")
const_stub.settings = SimpleNamespace(DB_DML_DEFAULT_ID=0)
sys.modules.setdefault("app.const", const_stub)

exceptions_stub = ModuleType("app.exceptions")


class CustomResponseException(Exception):
    def __init__(self, status_code=None, message=None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


exceptions_stub.CustomResponseException = CustomResponseException
sys.modules.setdefault("app.exceptions", exceptions_stub)

schemas_partner_stub = ModuleType("app.schemas.partner")
schemas_partner_stub.PutProductReqBody = object
sys.modules.setdefault("app.schemas", ModuleType("app.schemas"))
sys.modules.setdefault("app.schemas.partner", schemas_partner_stub)

schemas_product_stub = ModuleType("app.schemas.product")
schemas_product_stub.PostProductsReqBody = object
schemas_product_stub.PutProductsProductIdReqBody = object
schemas_product_stub.PostProductReportReqBody = object
schemas_product_stub.GetProductsGenresToCamel = object
sys.modules.setdefault("app.schemas.product", schemas_product_stub)

schemas_user_giftbook_stub = ModuleType("app.schemas.user_giftbook")
sys.modules.setdefault("app.schemas.user_giftbook", schemas_user_giftbook_stub)

utils_time_stub = ModuleType("app.utils.time")
utils_time_stub.convert_to_kor_time = lambda value: value
sys.modules.setdefault("app.utils.time", utils_time_stub)

utils_response_stub = ModuleType("app.utils.response")
utils_response_stub.CustomResponseException = type(
    "CustomResponseException", (Exception,), {}
)
utils_response_stub.build_list_response = lambda *args, **kwargs: {}
utils_response_stub.build_paginated_response = lambda *args, **kwargs: {}
utils_response_stub.check_exists_or_404 = lambda *args, **kwargs: None
sys.modules.setdefault("app.utils.response", utils_response_stub)

utils_query_stub = ModuleType("app.utils.query")
utils_query_stub.build_update_query = lambda *args, **kwargs: ("", {})
utils_query_stub.get_file_path_sub_query = lambda *args, **kwargs: "NULL"
utils_query_stub.get_pagination_params = lambda *args, **kwargs: (1, 20, 0)
sys.modules.setdefault("app.utils.query", utils_query_stub)

cp_link_stub = ModuleType("app.services.common.cp_link_service")
cp_link_stub.get_accepted_cp_info_map_by_user_ids = None
cp_link_stub.get_accepted_cp_info_by_nickname = None
cp_link_stub.get_accepted_cp_info_by_user_id = None
cp_link_stub.normalize_cp_nickname = lambda value: value.strip() if isinstance(value, str) and value.strip() else None
sys.modules.setdefault("app.services.common", ModuleType("app.services.common"))
sys.modules.setdefault("app.services.common.cp_link_service", cp_link_stub)

comm_service_stub = ModuleType("app.services.common.comm_service")
comm_service_stub.get_user_from_kc = None
sys.modules.setdefault("app.services.common.comm_service", comm_service_stub)

log_config_stub = ModuleType("app.config.log_config")
log_config_stub.service_error_logger = lambda *args, **kwargs: None
sys.modules.setdefault("app.config", ModuleType("app.config"))
sys.modules.setdefault("app.config.log_config", log_config_stub)

statistics_service_stub = ModuleType("app.services.common.statistics_service")
sys.modules.setdefault("app.services.common.statistics_service", statistics_service_stub)

user_giftbook_service_stub = ModuleType("app.services.user.user_giftbook_service")
sys.modules.setdefault("app.services.user", ModuleType("app.services.user"))
sys.modules.setdefault(
    "app.services.user.user_giftbook_service", user_giftbook_service_stub
)

event_reward_service_stub = ModuleType("app.services.event.event_reward_service")
sys.modules.setdefault("app.services.event", ModuleType("app.services.event"))
sys.modules.setdefault(
    "app.services.event.event_reward_service", event_reward_service_stub
)


from app.services.partner.partner_product_service import (
    _can_update_paid_monopoly,
    _is_paid_apply_monopoly_locked,
    _resolve_cp_link_update_values,
)
from app.services.product.product_service import (
    get_products_validate_cp_nickname,
    _resolve_reenabled_websochat_context_status,
    _resolve_product_cp_link_update_values,
)
import app.services.product.product_service as product_service_module


for _stubbed_module_name in [
    "fastapi",
    "sqlalchemy",
    "sqlalchemy.exc",
    "sqlalchemy.ext",
    "sqlalchemy.ext.asyncio",
    "app.const",
    "app.exceptions",
    "app.schemas",
    "app.schemas.partner",
    "app.schemas.product",
    "app.schemas.user_giftbook",
    "app.utils.time",
    "app.utils.response",
    "app.utils.query",
    "app.services.common",
    "app.services.common.cp_link_service",
    "app.services.common.comm_service",
    "app.config",
    "app.config.log_config",
    "app.services.common.statistics_service",
    "app.services.user",
    "app.services.user.user_giftbook_service",
    "app.services.event",
    "app.services.event.event_reward_service",
]:
    sys.modules.pop(_stubbed_module_name, None)


class ProductMonopolyPolicyUnitTest(unittest.TestCase):
    def test_omitted_cp_company_preserves_existing_cp_link(self):
        contract_yn, cp_user_id = _resolve_cp_link_update_values(
            fields_set={"monopoly_yn"},
            cp_company_name=None,
            resolved_cp_user_id=None,
            current_contract_yn="Y",
            current_cp_user_id=123,
        )

        self.assertEqual(contract_yn, "Y")
        self.assertEqual(cp_user_id, 123)

    def test_provided_cp_company_uses_resolved_cp_link(self):
        contract_yn, cp_user_id = _resolve_cp_link_update_values(
            fields_set={"cp_company_name"},
            cp_company_name="출판사",
            resolved_cp_user_id=456,
            current_contract_yn="N",
            current_cp_user_id=None,
        )

        self.assertEqual(contract_yn, "Y")
        self.assertEqual(cp_user_id, 456)

    def test_only_admin_can_update_paid_monopoly(self):
        self.assertTrue(_can_update_paid_monopoly({"role": "admin"}))
        self.assertFalse(_can_update_paid_monopoly({"role": "CP"}))
        self.assertFalse(_can_update_paid_monopoly({"role": "author"}))
        self.assertFalse(_can_update_paid_monopoly(None))

    def test_pending_paid_apply_locks_free_product_monopoly_change(self):
        self.assertTrue(_is_paid_apply_monopoly_locked("free", "review"))
        self.assertTrue(_is_paid_apply_monopoly_locked("free", "accepted"))
        self.assertFalse(_is_paid_apply_monopoly_locked("paid", "accepted"))
        self.assertFalse(_is_paid_apply_monopoly_locked("free", None))

    def test_free_monopoly_change_preserves_existing_product_cp_link(self):
        contract_yn, cp_user_id = _resolve_product_cp_link_update_values(
            current_monopoly_yn="Y",
            requested_monopoly_yn="N",
            current_contract_yn="Y",
            current_cp_user_id=123,
            requested_contract_yn="N",
            requested_cp_user_id=None,
        )

        self.assertEqual(contract_yn, "Y")
        self.assertEqual(cp_user_id, 123)

    def test_reenabled_websochat_ready_when_all_existing_context_is_ready(self):
        self.assertEqual(
            _resolve_reenabled_websochat_context_status(
                ready_episode_count=10,
                total_episode_count=10,
            ),
            "ready",
        )

    def test_reenabled_websochat_returns_pending_when_context_needs_rebuild(self):
        self.assertEqual(
            _resolve_reenabled_websochat_context_status(
                ready_episode_count=3,
                total_episode_count=10,
            ),
            "pending",
        )

    def test_admin_can_validate_cp_nickname_like_update_flow(self):
        async def fake_get_user_from_kc(kc_user_id, db):
            return 1063

        async def fake_resolve_current_user_role(kc_user_id, db):
            return "admin"

        async def fake_get_accepted_cp_info_by_nickname(nickname, db):
            return {"user_id": 9, "nickname": nickname}

        original_get_user_from_kc = product_service_module.comm_service.get_user_from_kc
        original_resolve_current_user_role = (
            product_service_module._resolve_current_user_role
        )
        original_get_accepted_cp_info_by_nickname = (
            product_service_module.get_accepted_cp_info_by_nickname
        )
        try:
            product_service_module.comm_service.get_user_from_kc = fake_get_user_from_kc
            product_service_module._resolve_current_user_role = (
                fake_resolve_current_user_role
            )
            product_service_module.get_accepted_cp_info_by_nickname = (
                fake_get_accepted_cp_info_by_nickname
            )

            result = asyncio.run(
                get_products_validate_cp_nickname("bart", "kc-admin", object())
            )

            self.assertEqual(result, {"data": {"valid": True}})
        finally:
            product_service_module.comm_service.get_user_from_kc = (
                original_get_user_from_kc
            )
            product_service_module._resolve_current_user_role = (
                original_resolve_current_user_role
            )
            product_service_module.get_accepted_cp_info_by_nickname = (
                original_get_accepted_cp_info_by_nickname
            )


if __name__ == "__main__":
    unittest.main()
