import inspect
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status
from fastapi.security import HTTPAuthorizationCredentials

from app.exceptions import CustomResponseException
from app.routers.user import user_query
from app.services.auth import auth_service
from app.schemas.auth import TokenReissueReqBody
from app.utils import auth as auth_utils


class UserQueryAuthContractTests(unittest.IsolatedAsyncioTestCase):
    def test_user_query_uses_strict_optional_auth_dependency(self):
        user_param = inspect.signature(user_query.get_user).parameters["user"]

        self.assertIs(
            user_param.default.dependency,
            auth_utils.chk_optional_cur_user_strict,
        )

    async def test_strict_optional_auth_allows_missing_credentials(self):
        result = await auth_utils.chk_optional_cur_user_strict(credentials=None)

        self.assertEqual(result, {})

    async def test_strict_optional_auth_rejects_invalid_credentials(self):
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="invalid-token",
        )

        with self.assertRaises(CustomResponseException) as exc:
            await auth_utils.chk_optional_cur_user_strict(credentials=credentials)

        self.assertEqual(exc.exception.status_code, status.HTTP_401_UNAUTHORIZED)

    async def test_strict_optional_auth_propagates_expired_credentials(self):
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="header.payload.signature",
        )

        with patch.object(
            auth_utils,
            "chk_jwt_token",
            new_callable=AsyncMock,
        ) as chk_jwt_token:
            chk_jwt_token.side_effect = CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message="expired access token",
            )

            with self.assertRaises(CustomResponseException) as exc:
                await auth_utils.chk_optional_cur_user_strict(credentials=credentials)

        self.assertEqual(exc.exception.status_code, status.HTTP_401_UNAUTHORIZED)

    async def test_access_token_validation_uses_login_clock_skew_leeway(self):
        with (
            patch.object(
                auth_utils,
                "get_kc_signing_key",
                new_callable=AsyncMock,
            ) as get_kc_signing_key,
            patch.object(auth_utils.jwt, "decode") as jwt_decode,
            patch.object(
                auth_utils,
                "chk_revoked_token",
                new_callable=AsyncMock,
            ) as chk_revoked_token,
        ):
            get_kc_signing_key.return_value = None
            jwt_decode.return_value = {"sub": "kc-user-id"}
            chk_revoked_token.return_value = {"active": True}

            result = await auth_utils.chk_jwt_token("header.payload.signature")

        self.assertEqual(result, {"sub": "kc-user-id"})
        self.assertGreaterEqual(auth_utils.KC_TOKEN_CLOCK_SKEW_LEEWAY_SECONDS, 30)
        self.assertEqual(
            jwt_decode.call_args.kwargs["leeway"],
            auth_utils.KC_TOKEN_CLOCK_SKEW_LEEWAY_SECONDS,
        )

    async def test_user_query_passes_valid_subject_to_user_service(self):
        db = object()

        with patch.object(
            user_query.user_service,
            "get_user",
            new_callable=AsyncMock,
        ) as get_user:
            get_user.return_value = {"data": {"userId": 123}}

            result = await user_query.get_user(user={"sub": "kc-user-id"}, db=db)

        self.assertEqual(result, {"data": {"userId": 123}})
        get_user.assert_awaited_once_with(kc_user_id="kc-user-id", db=db)


class TokenReissueContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_reissue_returns_rotated_refresh_token_and_expires_in_values(self):
        req_body = TokenReissueReqBody(
            access_token="expired-access-token",
            refresh_token="old-refresh-token",
        )

        with (
            patch.object(
                auth_service,
                "get_kc_signing_key",
                new_callable=AsyncMock,
            ) as get_kc_signing_key,
            patch.object(auth_service.jwt, "decode") as jwt_decode,
            patch.object(
                auth_service.comm_service,
                "kc_token_endpoint",
                new_callable=AsyncMock,
            ) as kc_token_endpoint,
        ):
            get_kc_signing_key.return_value = None
            jwt_decode.return_value = {"azp": auth_service.settings.KC_CLIENT_ID}
            kc_token_endpoint.return_value = {
                "access_token": "new-access-token",
                "expires_in": 300,
                "refresh_token": "new-refresh-token",
                "refresh_expires_in": 1800,
            }

            result = await auth_service.put_auth_token_reissue(req_body)

        self.assertEqual(
            result,
            {
                "data": {
                    "token": {
                        "accessToken": "new-access-token",
                        "accessTokenExpiresIn": 300,
                        "refreshToken": "new-refresh-token",
                        "refreshTokenExpiresIn": 1800,
                    }
                }
            },
        )
        kc_token_endpoint.assert_awaited_once_with(
            method="POST",
            type="reissue_normal",
            data_dict={"refresh_token": "old-refresh-token"},
        )
        self.assertEqual(
            jwt_decode.call_args.kwargs["leeway"],
            auth_utils.KC_TOKEN_CLOCK_SKEW_LEEWAY_SECONDS,
        )
        self.assertFalse(jwt_decode.call_args.kwargs["options"]["verify_exp"])


if __name__ == "__main__":
    unittest.main()
