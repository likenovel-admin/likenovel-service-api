import unittest
from pathlib import Path


EPISODE_SERVICE_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "product"
    / "episode_service.py"
)


class EpisodeInterestUsageTest(unittest.TestCase):
    def test_viewer_refreshes_usage_updated_date_for_interest_status(self):
        source = EPISODE_SERVICE_PATH.read_text()

        self.assertIn("update tb_user_product_usage", source.lower())
        self.assertIn("updated_date = NOW()", source)
