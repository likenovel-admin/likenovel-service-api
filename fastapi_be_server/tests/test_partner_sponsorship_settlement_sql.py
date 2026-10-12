from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
BATCH_DIR = ROOT / "dist" / "batch"


def _sql(name: str) -> str:
    return (BATCH_DIR / name).read_text(encoding="utf-8").lower()


def _statements(sql: str) -> list[str]:
    without_comments = re.sub(r"--[^\n]*", "", sql)
    return [part.strip() for part in without_comments.split(";") if part.strip()]


def _income_settlement_insert(sql: str) -> str:
    matches = [
        stmt
        for stmt in _statements(sql)
        if stmt.startswith("insert into tb_ptn_income_settlement ")
    ]
    assert len(matches) == 1, matches
    return matches[0]


class PartnerSponsorshipSettlementSqlTest(unittest.TestCase):
    def test_daily_batch_does_not_rewrite_realtime_sponsorship_records(self):
        statements = _statements(_sql("partner_report_daily_batch.sql"))

        writes = [
            stmt
            for stmt in statements
            if re.match(r"(insert into|delete from|update)\s+tb_ptn_sponsorship_recodes\b", stmt)
        ]
        self.assertEqual(writes, [])

    def test_monthly_batch_settles_sponsorship_with_ten_percent_fee(self):
        insert = _income_settlement_insert(_sql("partner_report_monthly_batch.sql"))

        self.assertRegex(insert, r"when b\.item_type = 'sponsorship' then 10\b")
        self.assertIn("round(b.sum_income_price * (100 - b.total_fee_rate) / 100, 1)", insert)
        self.assertIn("3.3 as withholding_tax_rate", insert)
        self.assertIn("* 0.967", insert)

    def test_monthly_batch_keeps_sales_fee_formula_for_other_income(self):
        insert = _income_settlement_insert(_sql("partner_report_monthly_batch.sql"))

        self.assertIn("else (c.fee_rate + (100 - c.settlement_rate))", insert)


if __name__ == "__main__":
    unittest.main()
