import unittest
from pathlib import Path

from app.services.product.episode_access_policy import (
    GUEST_FREE_EPISODE_LIMIT,
    guest_episode_login_required,
)


class GuestEpisodeAccessPolicyTest(unittest.TestCase):
    def test_guest_can_read_free_episode_at_limit(self):
        self.assertEqual(GUEST_FREE_EPISODE_LIMIT, 25)
        self.assertFalse(
            guest_episode_login_required(
                episode_price_type="free",
                episode_no=25,
            )
        )

    def test_guest_must_login_for_free_episode_after_limit(self):
        self.assertTrue(
            guest_episode_login_required(
                episode_price_type="free",
                episode_no=26,
            )
        )

    def test_guest_must_login_for_paid_episode_within_free_limit(self):
        self.assertTrue(
            guest_episode_login_required(
                episode_price_type="paid",
                episode_no=25,
            )
        )

    def test_viewer_returns_actual_next_public_episode_number(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "app/services/product/episode_service.py"
        ).read_text(encoding="utf-8")

        self.assertIn("where q.episode_id = c.next_episode_id", source)
        self.assertIn("where q.episode_id = f.next_episode_id", source)
        self.assertNotIn("else a.episode_no + 1", source)


if __name__ == "__main__":
    unittest.main()
