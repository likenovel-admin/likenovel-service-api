import hashlib
import inspect
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from fastapi import status

from app.exceptions import CustomResponseException
from app.routers.auth import auth_command
from app.schemas.auth import SignupReqBody, SocialSignupCompleteReqBody
from app.services.auth import auth_service


class _EmptyMappingsResult:
    def mappings(self):
        return self

    def all(self):
        return []


class _EmptyDb:
    def in_transaction(self):
        return False

    def begin(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, query, params=None):
        return _EmptyMappingsResult()


class _RecordingDb(_EmptyDb):
    def __init__(self):
        self.executions = []

    async def execute(self, query, params=None):
        self.executions.append((str(query), params or {}))
        return _EmptyMappingsResult()


class _SessionResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class _RowsResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _ExistingUserDb(_EmptyDb):
    async def execute(self, query, params=None):
        return _RowsResult(
            [{"use_yn": "Y", "latest_signed_type": "naver"}]
        )


class _SessionDb(_EmptyDb):
    def __init__(self, row, exit_error=None):
        self.row = row
        self.exit_error = exit_error
        self.execute_count = 0

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None and self.exit_error:
            raise self.exit_error
        return False

    async def execute(self, query, params=None):
        self.execute_count += 1
        if self.execute_count == 1:
            return _SessionResult(self.row)
        return _EmptyMappingsResult()


class AuthSocialSignupPendingTest(unittest.IsolatedAsyncioTestCase):
    async def test_unregistered_callbacks_redirect_with_opaque_token_without_pii(self):
        providers = ("naver", "google", "kakao", "apple")
        for provider in providers:
            with self.subTest(provider=provider):
                pending = {
                    "social_signup_pending": True,
                    "email": "private@example.com",
                    "keep_signin_yn": "Y",
                    "sns_signup_type": provider,
                    "sns_link_id": "provider-private-id",
                }
                callback = getattr(
                    auth_command, f"get_auth_signin_{provider}_callback"
                )
                service_callback_name = f"get_auth_signin_{provider}_callback"
                with (
                    patch.object(
                        auth_command.auth_service,
                        service_callback_name,
                        new=AsyncMock(return_value=pending),
                    ),
                    patch.object(
                        auth_command.auth_service,
                        "create_social_signup_session",
                        new=AsyncMock(
                            return_value=("opaque-session-token", "binding-secret")
                        ),
                    ),
                    patch.object(
                        auth_command.settings,
                        "SOCIAL_SIGNUP_COOKIE_DOMAIN",
                        "",
                    ),
                ):
                    response = await callback(
                        code="oauth-code", state="Y-likenovel", db=object()
                    )

                location = response.headers["location"]
                parsed = urlparse(location)
                query = parse_qs(parsed.query)
                self.assertEqual(parsed.path, "/sign-up")
                self.assertEqual(query["social_pending"], ["opaque-session-token"])
                self.assertEqual(query["provider"], [provider])
                self.assertNotIn("private@example.com", location)
                self.assertNotIn("provider-private-id", location)
                cookie = response.headers["set-cookie"]
                self.assertIn("ln_social_signup_binding=binding-secret", cookie)
                self.assertIn("HttpOnly", cookie)
                self.assertIn("Max-Age=600", cookie)
                self.assertIn("SameSite=lax", cookie)
                self.assertNotIn("Domain=", cookie)

    async def test_registered_callbacks_keep_existing_storage_relay_path(self):
        registered = {
            "email": "member@example.com",
            "password": "Social123!",
            "keep_signin_yn": "Y",
            "sns_signup_type": "naver",
            "sns_link_id": "keycloak-username",
        }
        relay_response = {
            "data": {"auth": {"snsId": 17, "tempIssuedKey": "relay-key"}}
        }

        for provider in ("naver", "google", "kakao", "apple"):
            with self.subTest(provider=provider):
                callback = getattr(
                    auth_command, f"get_auth_signin_{provider}_callback"
                )
                service_callback_name = f"get_auth_signin_{provider}_callback"
                provider_registered = {**registered, "sns_signup_type": provider}
                create_session = AsyncMock()
                with (
                    patch.object(
                        auth_command.auth_service,
                        service_callback_name,
                        new=AsyncMock(return_value=provider_registered),
                    ),
                    patch.object(
                        auth_command.auth_service,
                        "create_social_signup_session",
                        new=create_session,
                    ),
                    patch.object(
                        auth_command,
                        "post_auth_signin",
                        new=AsyncMock(return_value=relay_response),
                    ),
                ):
                    response = await callback(
                        code="oauth-code", state="Y-likenovel", db=object()
                    )

                location = response.headers["location"]
                self.assertIn("/storage-relay?", location)
                self.assertIn("sns_id=17", location)
                self.assertIn("temp_issued_key=relay-key", location)
                create_session.assert_not_awaited()

    async def test_pending_cookie_uses_configured_parent_domain_and_secure(self):
        pending = {
            "social_signup_pending": True,
            "email": "private@example.com",
            "keep_signin_yn": "Y",
            "sns_signup_type": "naver",
            "sns_link_id": "naver-id",
            "birthdate": "1988-04-05",
            "gender": "M",
        }
        with (
            patch.object(
                auth_command.auth_service,
                "create_social_signup_session",
                new=AsyncMock(return_value=("pending-token", "binding-secret")),
            ),
            patch.object(
                auth_command.settings,
                "SOCIAL_SIGNUP_COOKIE_DOMAIN",
                ".likenovel.net",
            ),
            patch.object(
                auth_command.settings, "FE_DOMAIN", "https://www.likenovel.net"
            ),
        ):
            response = await auth_command._social_signup_pending_redirect(
                pending, object()
            )

        cookie = response.headers["set-cookie"]
        self.assertIn("Domain=.likenovel.net", cookie)
        self.assertIn("Secure", cookie)

    async def _get_unregistered_callback(self, provider, profile, state):
        token_response = (
            {"id_token": "apple-id-token"}
            if provider == "apple"
            else {"access_token": "provider-access-token"}
        )
        service_callback = getattr(
            auth_service, f"get_auth_signin_{provider}_callback"
        )
        patches = [
            patch.object(
                auth_service.comm_service,
                "sns_token_endpoint",
                new=AsyncMock(return_value=token_response),
            )
        ]
        if provider == "apple":
            patches.append(
                patch.object(
                    auth_service.comm_service,
                    "decode_apple_token",
                    new=AsyncMock(return_value=profile),
                )
            )
        else:
            provider_profile = {"response": profile} if provider == "naver" else profile
            patches.append(
                patch.object(
                    auth_service.comm_service,
                    "sns_me_endpoint",
                    new=AsyncMock(return_value=provider_profile),
                )
            )

        with patches[0], patches[1]:
            return await service_callback(
                db=_EmptyDb(), code="oauth-code", state=state
            )

    async def test_unregistered_callbacks_preserve_provider_demographics(self):
        cases = (
            (
                "naver",
                {
                    "id": "naver-id",
                    "email": "naver@example.com",
                    "birthyear": "1988",
                    "birthday": "04-05",
                    "gender": "1",
                },
                "Y-likenovel",
                "1988-04-05",
                "M",
            ),
            (
                "kakao",
                {
                    "id": 17,
                    "kakao_account": {
                        "email": "kakao@example.com",
                        "birthyear": "1992",
                        "birthday": "06-07",
                        "gender": "female",
                    },
                },
                "Y-likenovel",
                "1992-06-07",
                "F",
            ),
            (
                "google",
                {"id": "google-id", "email": "google@example.com"},
                "Y-1995-08-09-M-likenovel",
                "1995-08-09",
                "M",
            ),
            (
                "apple",
                {"sub": "apple-id", "email": "apple@example.com"},
                "Y-1997-10-11-F-likenovel",
                "1997-10-11",
                "F",
            ),
        )

        for provider, profile, state, birthdate, gender in cases:
            with self.subTest(provider=provider):
                pending = await self._get_unregistered_callback(
                    provider, profile, state
                )
                self.assertEqual(pending["birthdate"], birthdate)
                self.assertEqual(pending["gender"], gender)

    async def test_missing_provider_demographics_use_existing_sentinel(self):
        cases = (
            (
                "naver",
                {"id": "naver-id", "email": "naver@example.com"},
                "Y-likenovel",
            ),
            (
                "kakao",
                {"id": 17, "kakao_account": {"email": "kakao@example.com"}},
                "Y-likenovel",
            ),
            (
                "google",
                {"id": "google-id", "email": "google@example.com"},
                "Y-9999-12-31-U-likenovel",
            ),
        )

        for provider, profile, state_value in cases:
            with self.subTest(provider=provider):
                pending = await self._get_unregistered_callback(
                    provider, profile, state_value
                )
                self.assertEqual(pending["birthdate"], "9999-12-31")
                self.assertEqual(pending["gender"], "U")

    async def test_session_persists_demographics_and_binding_hash(self):
        for birthdate, gender in (("1988-04-05", "M"), ("9999-12-31", "U")):
            with self.subTest(birthdate=birthdate, gender=gender):
                db = _RecordingDb()
                with patch.object(
                    auth_service.secrets,
                    "token_urlsafe",
                    side_effect=("pending-token", "binding-secret"),
                ):
                    token, binding = await auth_service.create_social_signup_session(
                        {
                            "email": "member@example.com",
                            "keep_signin_yn": "Y",
                            "sns_signup_type": "naver",
                            "sns_link_id": "naver-id",
                            "birthdate": birthdate,
                            "gender": gender,
                        },
                        db,
                    )

                self.assertEqual((token, binding), ("pending-token", "binding-secret"))
                params = db.executions[0][1]
                self.assertEqual(params["birthdate"], birthdate)
                self.assertEqual(params["gender"], gender)
                self.assertEqual(
                    params["binding_hash"],
                    hashlib.sha256(b"binding-secret").hexdigest(),
                )

    def _session_row(self, binding_secret="correct-binding"):
        return {
            "social_signup_session_id": 10,
            "provider": "naver",
            "sns_link_id": "naver-id",
            "email": "member@example.com",
            "keep_signin_yn": "Y",
            "birthdate": "1988-04-05",
            "gender": "M",
            "binding_hash": hashlib.sha256(binding_secret.encode()).hexdigest(),
        }

    async def test_complete_rejects_missing_or_mismatched_binding_cookie(self):
        req_body = SocialSignupCompleteReqBody(
            token="opaque-session-token-12345", ad_info_agree_yn="N"
        )
        for binding_secret in (None, "wrong-binding"):
            with self.subTest(binding_secret=binding_secret):
                with self.assertRaises(CustomResponseException) as raised:
                    await auth_service.post_auth_social_signup_complete(
                        req_body=req_body,
                        binding_secret=binding_secret,
                        db=_SessionDb(self._session_row()),
                    )
                self.assertEqual(raised.exception.status_code, status.HTTP_400_BAD_REQUEST)

    async def test_complete_accepts_matching_binding_and_uses_session_demographics(self):
        req_body = SocialSignupCompleteReqBody(
            token="opaque-session-token-12345", ad_info_agree_yn="N"
        )

        async def signup_side_effect(*, req_body, db, keycloak_compensation):
            self.assertEqual(req_body.birthdate, "1988-04-05")
            self.assertEqual(req_body.gender, "M")
            keycloak_compensation.update(
                admin_acc_token="admin-token", user_id="keycloak-user-id"
            )
            return {
                "email": req_body.email,
                "password": req_body.password,
                "keep_signin_yn": "Y",
                "sns_signup_type": "naver",
                "sns_link_id": "keycloak-username",
            }

        with (
            patch.object(
                auth_service,
                "post_auth_signup",
                new=AsyncMock(side_effect=signup_side_effect),
            ),
            patch.object(
                auth_service,
                "post_auth_signin",
                new=AsyncMock(return_value={"data": {"auth": {"snsId": 1}}}),
            ),
        ):
            response = await auth_service.post_auth_social_signup_complete(
                req_body=req_body,
                binding_secret="correct-binding",
                db=_SessionDb(self._session_row()),
            )

        self.assertEqual(response["keep_signin_yn"], "Y")

    async def test_complete_compensates_keycloak_user_and_preserves_original_error(self):
        req_body = SocialSignupCompleteReqBody(
            token="opaque-session-token-12345", ad_info_agree_yn="N"
        )
        original_error = RuntimeError("signin failed")

        async def signup_side_effect(*, req_body, db, keycloak_compensation):
            keycloak_compensation.update(
                admin_acc_token="admin-token", user_id="keycloak-user-id"
            )
            return {
                "email": req_body.email,
                "password": req_body.password,
                "keep_signin_yn": "Y",
                "sns_signup_type": "naver",
                "sns_link_id": "keycloak-username",
            }

        delete_user = AsyncMock()
        with (
            patch.object(
                auth_service,
                "post_auth_signup",
                new=AsyncMock(side_effect=signup_side_effect),
            ),
            patch.object(
                auth_service,
                "post_auth_signin",
                new=AsyncMock(side_effect=original_error),
            ),
            patch.object(
                auth_service.comm_service,
                "kc_users_id_endpoint",
                new=delete_user,
            ),
        ):
            with self.assertRaises(RuntimeError) as raised:
                await auth_service.post_auth_social_signup_complete(
                    req_body=req_body,
                    binding_secret="correct-binding",
                    db=_SessionDb(self._session_row()),
                )

        self.assertIs(raised.exception, original_error)
        delete_user.assert_awaited_once_with(
            method="DELETE", admin_acc_token="admin-token", id="keycloak-user-id"
        )

    async def test_complete_logs_compensation_failure_and_preserves_original_error(self):
        req_body = SocialSignupCompleteReqBody(
            token="opaque-session-token-12345", ad_info_agree_yn="N"
        )
        original_error = RuntimeError("commit failed")

        async def signup_side_effect(*, req_body, db, keycloak_compensation):
            keycloak_compensation.update(
                admin_acc_token="admin-token", user_id="keycloak-user-id"
            )
            return {
                "email": req_body.email,
                "password": req_body.password,
                "keep_signin_yn": "Y",
                "sns_signup_type": "naver",
                "sns_link_id": "keycloak-username",
            }

        with (
            patch.object(
                auth_service,
                "post_auth_signup",
                new=AsyncMock(side_effect=signup_side_effect),
            ),
            patch.object(
                auth_service,
                "post_auth_signin",
                new=AsyncMock(return_value={"data": {"auth": {"snsId": 1}}}),
            ),
            patch.object(
                auth_service.comm_service,
                "kc_users_id_endpoint",
                new=AsyncMock(side_effect=RuntimeError("cleanup failed")),
            ),
            patch.object(auth_service, "error_logger") as compensation_logger,
        ):
            with self.assertRaises(RuntimeError) as raised:
                await auth_service.post_auth_social_signup_complete(
                    req_body=req_body,
                    binding_secret="correct-binding",
                    db=_SessionDb(self._session_row(), exit_error=original_error),
                )

        self.assertIs(raised.exception, original_error)
        compensation_logger.error.assert_called_once()

    async def test_complete_response_expires_binding_cookie_on_success_and_failure(self):
        req_body = SocialSignupCompleteReqBody(
            token="opaque-session-token-12345", ad_info_agree_yn="N"
        )
        outcomes = (
            {"data": {"auth": {"snsId": 1}}},
            CustomResponseException(
                status_code=status.HTTP_409_CONFLICT,
                message="server conflict message",
            ),
        )

        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__):
                complete = (
                    AsyncMock(side_effect=outcome)
                    if isinstance(outcome, Exception)
                    else AsyncMock(return_value=outcome)
                )
                with patch.object(
                    auth_command.auth_service,
                    "post_auth_social_signup_complete",
                    new=complete,
                ):
                    response = await auth_command.post_auth_social_signup_complete(
                        req_body=req_body,
                        binding_secret="correct-binding",
                        db=object(),
                    )

                cookie = response.headers["set-cookie"]
                self.assertIn("ln_social_signup_binding=", cookie)
                self.assertIn("Max-Age=0", cookie)
                if isinstance(outcome, CustomResponseException):
                    self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
                    self.assertIn(b"server conflict message", response.body)

    async def test_existing_email_conflict_keeps_server_login_method_message(self):
        req_body = SignupReqBody(
            email="member@example.com",
            password="Password123!",
            birthdate="1988-04-05",
            gender="M",
            ad_info_agree_yn="N",
        )

        with self.assertRaises(CustomResponseException) as raised:
            await auth_service.post_auth_signup(
                req_body=req_body, db=_ExistingUserDb()
            )

        self.assertEqual(raised.exception.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            raised.exception.message,
            "이미 네이버로 가입된 계정입니다. 네이버로 로그인해주세요.",
        )

    def test_session_contract_is_hashed_ten_minute_single_use(self):
        service_source = inspect.getsource(auth_service)
        self.assertIn('hashlib.sha256(token.encode("utf-8")).hexdigest()', service_source)
        self.assertIn(
            'hashlib.sha256(binding_secret.encode("utf-8")).hexdigest()',
            service_source,
        )
        self.assertIn("DATE_ADD(NOW(), INTERVAL 10 MINUTE)", service_source)
        self.assertIn("FOR UPDATE", service_source)
        self.assertIn("SET use_yn = 'N'", service_source)
        self.assertIn('state[2:12] != "9999-12-31"', service_source)
        self.assertIn('state[13] not in ("M", "F", "U")', service_source)
        self.assertIn('google_gender = "U"', service_source)

        migration = (
            Path(__file__).resolve().parents[1]
            / "dist/init/107-create-social-signup-session.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS tb_social_signup_session", migration)
        self.assertIn("binding_hash CHAR(64) NOT NULL", migration)
        self.assertIn("birthdate VARCHAR(10) NOT NULL", migration)
        self.assertIn("gender VARCHAR(1) NOT NULL", migration)
        self.assertIn("UNIQUE KEY uk_social_signup_session_token_hash", migration)

    def test_existing_signup_password_validation_remains_attached(self):
        with self.assertRaises(ValueError):
            SignupReqBody(
                email="member@example.com",
                password="nospecial123",
                birthdate="2000-01-01",
                gender="M",
                ad_info_agree_yn="N",
            )
