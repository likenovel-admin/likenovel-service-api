from pathlib import Path
import re


def _summary_daily_batch_sql() -> str:
    batch_path = (
        Path(__file__).resolve().parents[1]
        / "dist"
        / "batch"
        / "summary_daily_batch.sql"
    )
    return batch_path.read_text(encoding="utf-8")


def _reading_rate_sql_section() -> str:
    sql = _summary_daily_batch_sql()
    start = sql.index("-- 전체연독률 = 15화 이상 작품만 계산")
    end = sql.index("-- 주평균 연재횟수", start)
    return sql[start:end].lower()


def test_reading_rate_batch_uses_visible_episodes_only():
    section = _reading_rate_sql_section()

    assert re.search(
        r"from tb_product_episode\s+where episode_no = 4\s+and use_yn = 'y'\s+and open_yn = 'y'",
        section,
    )
    assert re.search(
        r"select product_id, max\(episode_no\) - 3 as target_no\s+from tb_product_episode\s+where use_yn = 'y'\s+and open_yn = 'y'",
        section,
    )
    assert re.search(
        r"where pe\.use_yn = 'y'\s+and pe\.open_yn = 'y'",
        section,
    )
    assert "having count(*) >= 15" in section
