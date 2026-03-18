"""
앱 시작 시 dist/init/*.sql 마이그레이션을 자동 실행.

- tb_schema_migration 테이블로 적용 이력 추적
- 03-* 이상 스크립트만 대상 (01-02는 Docker init 또는 수동 초기 셋업)
- 이미 적용된 DDL (테이블/컬럼/인덱스 중복) 은 자동 스킵
- MySQL advisory lock으로 멀티워커 동시 실행 방지
"""

import logging
import re
from pathlib import Path

from sqlalchemy import text

from app.rdb import likenovel_db_engine

logger = logging.getLogger(__name__)

# 배포 환경: cwd=/home/ln-admin/likenovel/api/ → init/
# 로컬 dev: cwd=fastapi_be_server/ → dist/init/
_candidates = [
    Path.cwd() / "init",
    Path.cwd() / "dist" / "init",
    Path(__file__).resolve().parent.parent.parent / "dist" / "init",
]
INIT_DIR = next((p for p in _candidates if p.exists()), _candidates[-1])

# 01-02는 Docker init 또는 수동 초기 셋업으로 처리
SKIP_PREFIXES = ("01-", "02-")

# MySQL 에러 코드: 이미 존재하는 스키마 변경 → 적용 완료로 처리
IDEMPOTENT_ERRORS = {
    1050,  # Table already exists
    1060,  # Duplicate column name
    1061,  # Duplicate key name (index)
    1068,  # Multiple primary key defined
    1826,  # Duplicate foreign key constraint name
}

# 레거시 init SQL 중 일부는 선택 기능 테이블 부재/과거 드리프트 상황에서
# 안전하게 no-op 처리해도 되는 케이스가 있다.
FILE_IDEMPOTENT_ERRORS = {
    "05-migration_tb_user_profile_apply.sql": {1091, 1146},
    "15-migration_chat_user_based.sql": {1054, 1091, 1146},
    "20-alter_store_order.sql": {1054, 1146},
    "27-alter_payment_statistics_by_user_unique_key.sql": {1091, 1146},
    "68-add-standard-keywords.sql": {1062, 1146},
}

LOCK_NAME = "likenovel_auto_migrate"


def _parse_statements(sql_content: str) -> list[str]:
    """SQL 파일을 개별 statement로 분리. 주석/빈줄/USE 제거."""
    # 블록 주석 제거
    sql_content = re.sub(r"/\*.*?\*/", "", sql_content, flags=re.DOTALL)

    # 라인 주석은 split 이전에 제거해야, 주석 안 세미콜론 때문에 statement가 깨지지 않는다.
    sql_content = "\n".join(
        line for line in sql_content.splitlines()
        if line.strip() and not line.strip().startswith("--")
    )

    statements = []
    for part in sql_content.split(";"):
        lines = [line for line in part.strip().splitlines() if line.strip()]
        stmt = "\n".join(lines).strip()
        if not stmt:
            continue
        # USE 문 스킵 (이미 likenovel DB에 연결됨)
        if re.match(r"^USE\s+", stmt, re.IGNORECASE):
            continue
        statements.append(stmt)
    return statements


async def run_auto_migrations():
    """pending SQL 마이그레이션을 자동 실행."""
    if not INIT_DIR.exists():
        logger.info("[auto_migrate] dist/init/ 디렉토리 없음 — 스킵")
        return

    async with likenovel_db_engine.connect() as conn:
        # advisory lock 획득 (non-blocking, 0초 대기)
        result = await conn.execute(
            text(f"SELECT GET_LOCK('{LOCK_NAME}', 0)")
        )
        got_lock = result.scalar()
        if not got_lock:
            logger.info("[auto_migrate] 다른 워커에서 실행 중 — 스킵")
            return

        try:
            await _execute_pending(conn)
        finally:
            await conn.execute(text(f"SELECT RELEASE_LOCK('{LOCK_NAME}')"))
            await conn.commit()


async def _execute_pending(conn):
    """lock 획득 상태에서 pending 마이그레이션 실행."""
    # 1) 트래킹 테이블 생성
    await conn.execute(text(
        "CREATE TABLE IF NOT EXISTS tb_schema_migration ("
        "  id INT AUTO_INCREMENT PRIMARY KEY,"
        "  filename VARCHAR(255) NOT NULL UNIQUE,"
        "  applied_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    ))
    await conn.commit()

    # 2) 이미 적용된 목록 조회
    result = await conn.execute(
        text("SELECT filename FROM tb_schema_migration")
    )
    applied = {row[0] for row in result.fetchall()}

    # 3) 대상 SQL 파일 수집 (번호순)
    sql_files = sorted(INIT_DIR.glob("*.sql"))
    pending = [
        f for f in sql_files
        if f.name not in applied
        and not f.name.startswith(SKIP_PREFIXES)
    ]

    if not pending:
        logger.info("[auto_migrate] pending 마이그레이션 없음")
        return

    logger.info(f"[auto_migrate] {len(pending)}건 pending 마이그레이션 발견")

    # 4) 순서대로 실행
    for sql_file in pending:
        statements = _parse_statements(sql_file.read_text(encoding="utf-8"))
        if not statements:
            await conn.execute(
                text("INSERT IGNORE INTO tb_schema_migration (filename) VALUES (:fn)"),
                {"fn": sql_file.name},
            )
            await conn.commit()
            continue

        all_ok = True
        for stmt in statements:
            try:
                await conn.exec_driver_sql(stmt)
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                error_code = None
                if hasattr(e, "orig") and hasattr(e.orig, "args"):
                    error_code = e.orig.args[0]

                allowed_errors = IDEMPOTENT_ERRORS | FILE_IDEMPOTENT_ERRORS.get(
                    sql_file.name, set()
                )

                if error_code in allowed_errors:
                    logger.info(
                        f"[auto_migrate] {sql_file.name} — 이미 적용된 DDL 스킵 "
                        f"(MySQL {error_code})"
                    )
                else:
                    logger.error(f"[auto_migrate] {sql_file.name} 실패: {e}")
                    all_ok = False
                    break

        if all_ok:
            await conn.execute(
                text("INSERT IGNORE INTO tb_schema_migration (filename) VALUES (:fn)"),
                {"fn": sql_file.name},
            )
            await conn.commit()
            logger.info(f"[auto_migrate] {sql_file.name} 적용 완료")
        else:
            logger.warning(
                f"[auto_migrate] {sql_file.name} 실패 — 다음 시작 시 재시도"
            )
