import unittest

from app.services.partner import partner_basic_service
from app.utils.common import check_user


class _FakeMappings:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def one_or_none(self):
        return self._row

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, row=None, rows=None):
        self._mappings = _FakeMappings(row=row, rows=rows)

    def mappings(self):
        return self._mappings


class _RecordingDb:
    def __init__(self, results):
        self._results = list(results)
        self.queries = []

    async def execute(self, query, params=None):
        self.queries.append(" ".join(str(query).split()))
        return self._results.pop(0)


class CpApprovalRoleGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_check_user_requires_an_accepted_application_for_cp_role(self):
        db = _RecordingDb(
            [
                _FakeResult(
                    row={"user_id": 42, "role_type": "normal", "apply_type": None}
                )
            ]
        )

        result = await check_user("kc-user", db)

        self.assertEqual(result, {"user_id": 42, "role": "author"})
        query = db.queries[0].lower()
        self.assertIn("approval_code = 'accepted'", query)
        self.assertIn("approval_date is not null", query)

    async def test_check_user_keeps_accepted_cp_role(self):
        db = _RecordingDb(
            [
                _FakeResult(
                    row={"user_id": 42, "role_type": "normal", "apply_type": "cp"}
                )
            ]
        )

        result = await check_user("kc-user", db)

        self.assertEqual(result, {"user_id": 42, "role": "CP"})

    async def test_partner_profile_cp_label_requires_accepted_application(self):
        db = _RecordingDb(
            [
                _FakeResult(rows=[{"user_id": 42}]),
                _FakeResult(rows=[{"user_id": 42, "role_type": "author"}]),
            ]
        )

        result = await partner_basic_service.partner_profiles_of_partner(42, db)

        self.assertEqual(result, [{"user_id": 42, "role_type": "author"}])
        query = db.queries[1].lower()
        self.assertIn("approval_code = 'accepted'", query)
        self.assertIn("approval_date is not null", query)


if __name__ == "__main__":
    unittest.main()
