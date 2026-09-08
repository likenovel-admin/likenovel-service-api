"""Opt-in, real MySQL action/transaction tests; never connects to DEV or PROD."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
import subprocess

import pymysql
import pytest
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.services.ai.reader_agent_action_service import ReaderQueuedAction, process_claimed_action
from app.services.product.product_comment_service import delete_products_comments_comment_id


pytestmark = pytest.mark.skipif(
    os.getenv("LN_READER_COMMENTS_MYSQL_TEST") != "1", reason="isolated local MySQL opt-in required",
)
SCHEMA = "ln_reader_comments_test_20260908"
ROOT = Path(__file__).resolve().parents[1]
MYSQL_OWNER = "/home/hongsan/work/likenovel/likenovel-service-api/likenovel-service-api/fastapi_be_server"


@pytest.fixture
def mysql():
    assert os.getenv("DB_IP") == "127.0.0.1" and os.getenv("DB_PORT") == "1"
    result = subprocess.run(["docker", "inspect", "likenovel-mysql"], check=True, capture_output=True, text=True)
    metadata = json.loads(result.stdout)[0]
    config = metadata["Config"]
    labels = config.get("Labels") or {}
    ports = metadata["NetworkSettings"]["Ports"].get("3306/tcp") or []
    assert metadata["Name"] == "/likenovel-mysql" and config["Image"] == "mysql:8.0"
    assert metadata["State"].get("Health", {}).get("Status") == "healthy"
    assert labels.get("com.docker.compose.project.working_dir") == MYSQL_OWNER
    assert labels.get("com.docker.compose.service") == "mysql"
    assert ports and all(binding["HostPort"] == "3806" for binding in ports)
    environment = dict(item.split("=", 1) for item in config["Env"] if "=" in item)
    password = environment["MYSQL_ROOT_PASSWORD"]
    control = pymysql.connect(host="127.0.0.1", port=3806, user="root", password=password,
                              charset="utf8mb4", autocommit=True, connect_timeout=5)
    created = False
    engine = None
    try:
        with control.cursor() as cur:
            cur.execute("SELECT @@hostname, @@port, @@transaction_isolation")
            assert cur.fetchone() == (config["Hostname"], 3306, "REPEATABLE-READ")
            cur.execute("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=%s", (SCHEMA,))
            assert cur.fetchone()[0] == 0, "refusing to adopt or remove a pre-existing database"
            cur.execute(f"CREATE DATABASE `{SCHEMA}` CHARACTER SET utf8mb4")
            created = True
            cur.execute(f"USE `{SCHEMA}`")
            for filename, tables in (
                ("02-create_tables.sql", ("tb_user", "tb_user_social", "tb_user_profile", "tb_product",
                                          "tb_product_episode", "tb_product_comment", "tb_user_product_usage")),
                ("87-create-ai-reader-agent-phase1-tables.sql", ("tb_ai_reader_agent", "tb_ai_reader_daily_schedule", "tb_ai_reader_product_state",
                                                               "tb_ai_reader_action_queue")),
            ):
                source = (ROOT / "dist/init" / filename).read_text()
                for table in tables:
                    ddl = re.search(r"CREATE TABLE (?:IF NOT EXISTS )?" + table + r" \([\s\S]*?\n\)[^;]*;", source)
                    assert ddl, table
                    cur.execute(ddl.group())
            cur.execute((ROOT / "dist/init/60-alter_product_add_blind_yn.sql").read_text())
            cur.execute("INSERT INTO tb_product (product_id,title,price_type,status_code,ratings_code,user_id,author_id,publish_days,primary_genre_id,open_yn) VALUES (200,'test','free','ongoing','all',1,1,'',1,'Y')")
            cur.execute("INSERT INTO tb_product_episode (episode_id,product_id,episode_no,price_type,open_yn,comment_open_yn,count_hit) VALUES (300,200,1,'free','Y','Y',50)")
            for user in range(1, 5):
                cur.execute("INSERT INTO tb_user (user_id,kc_user_id,email,latest_signed_type) VALUES (%s,%s,%s,'likenovel')",
                            (user, f"comment-test-{user}", f"test-{user}@ai-reader.likenovel.dev"))
                cur.execute("INSERT INTO tb_user_profile (profile_id,user_id,nickname,role_type,default_yn) VALUES (%s,%s,%s,'user','Y')", (user, user, f"댓글검증{user}"))
                cur.execute("INSERT INTO tb_ai_reader_agent (ai_reader_agent_id,user_id,agent_key,age_group,gender,persona_json,activity_pattern_json) VALUES (%s,%s,%s,'adult','unknown','{}','{}')", (user, user, f"comment-test-{user}"))
                cur.execute("INSERT INTO tb_ai_reader_product_state (ai_reader_agent_id,product_id,read_episode_count) VALUES (%s,200,1)", (user,))
                cur.execute("INSERT INTO tb_user_product_usage (user_id,product_id,episode_id) VALUES (%s,200,300)", (user,))
                cur.execute("INSERT INTO tb_ai_reader_action_queue (ai_reader_action_id,idempotency_key,ai_reader_agent_id,user_id,product_id,episode_id,action_type,target_value,status,locked_by) VALUES (%s,%s,%s,%s,200,300,'comment','감사합니다.','running','mysql-test')", (user, str(user).zfill(64), user, user))
        url = URL.create("mysql+aiomysql", username="root", password=password, host="127.0.0.1", port=3806, database=SCHEMA)
        engine = create_async_engine(url, poolclass=NullPool, isolation_level="REPEATABLE READ", connect_args={"init_command": "SET innodb_lock_wait_timeout=5"})
        yield engine
    finally:
        try:
            if engine is not None:
                asyncio.run(engine.dispose())
            if created:
                with control.cursor() as cur:
                    cur.execute(f"DROP DATABASE `{SCHEMA}`")
                    cur.execute("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=%s", (SCHEMA,))
                    assert cur.fetchone()[0] == 0
                print(f"cleanup schema={SCHEMA} absent=true")
        finally:
            control.close()


async def post(engine, user, *, pinned_session_factory=None):
    async with AsyncSession(engine) as db:
        return await process_claimed_action(
            ReaderQueuedAction(user, user, user, 200, 300, "comment", "감사합니다."),
            db, worker_id="mysql-test", pinned_session_factory=pinned_session_factory,
        )


@pytest.mark.parametrize("existing,loser", [(0, "comment_interval_limit"), (2, "comment_24h_limit")])
def test_concurrent_workers_cannot_overfill_episode(mysql, existing, loser):
    asyncio.run(check_concurrent_workers(mysql, existing, loser))


async def check_concurrent_workers(mysql, existing, loser):
    async with mysql.begin() as db:
        for user in range(3, 3 + existing):
            await db.execute(text("INSERT INTO tb_product_comment (product_id,episode_id,user_id,profile_id,content,use_yn,created_date) VALUES (200,300,:user,:user,'건필하세요.','N',timestampadd(hour,-:user,current_timestamp))"), {"user": user})
    results = await asyncio.wait_for(asyncio.gather(post(mysql, 1), post(mysql, 2)), timeout=10)
    assert sorted(result.reason for result in results) == sorted(["applied", loser])
    async with mysql.connect() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM tb_product_comment"))).scalar_one() == existing + 1
        assert (await db.execute(text("SELECT count_comment FROM tb_product_episode WHERE episode_id=300"))).scalar_one() == 1
        assert sorted((await db.execute(text("SELECT status FROM tb_ai_reader_action_queue WHERE ai_reader_action_id IN (1,2)"))).scalars().all()) == ["applied", "skipped"]


def test_committed_close_while_worker_waits_prevents_insert(mysql):
    asyncio.run(check_committed_close(mysql))


async def check_committed_close(mysql):
    async with mysql.connect() as closing:
        transaction = await closing.begin()
        await closing.execute(text("UPDATE tb_product_episode SET comment_open_yn='N' WHERE episode_id=300"))
        task = asyncio.create_task(post(mysql, 1))
        try:
            # Observe an actual InnoDB waiter, not just a timer or mocked lock.
            async with mysql.connect() as observer:
                for _ in range(100):
                    waits = await observer.execute(text("SELECT COUNT(*) FROM performance_schema.data_lock_waits w JOIN performance_schema.data_locks l ON l.ENGINE_LOCK_ID=w.REQUESTING_ENGINE_LOCK_ID WHERE l.OBJECT_SCHEMA=:schema"), {"schema": SCHEMA})
                    if waits.scalar_one():
                        break
                    await asyncio.sleep(0.02)
                else:
                    pytest.fail("worker never reached the competing episode row lock")
            assert not task.done()
            await transaction.commit()
            result = await asyncio.wait_for(task, timeout=10)
            assert result.reason == "comment_closed"
        finally:
            if transaction.is_active:
                await transaction.rollback()
            if not task.done():
                await asyncio.wait_for(task, timeout=10)
    async with mysql.connect() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM tb_product_comment"))).scalar_one() == 0


def test_expired_queue_is_terminal_without_a_comment(mysql):
    asyncio.run(check_expired_queue(mysql))


@pytest.mark.parametrize("count_hit,expected", [(19, "comment_view_count_too_low"), (20, "applied")])
def test_barely_viewed_episode_is_skipped(mysql, count_hit, expected):
    asyncio.run(check_low_view_episode(mysql, count_hit, expected))


async def check_low_view_episode(mysql, count_hit, expected):
    async with mysql.begin() as db:
        await db.execute(text("UPDATE tb_product_episode SET count_hit=:hit WHERE episode_id=300"), {"hit": count_hit})
    result = await post(mysql, 1)
    assert result.reason == expected
    async with mysql.connect() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM tb_product_comment"))).scalar_one() == int(expected == "applied")
        assert (await db.execute(text("SELECT status FROM tb_ai_reader_action_queue WHERE ai_reader_action_id=1"))).scalar_one() == ("applied" if expected == "applied" else "skipped")


async def check_expired_queue(mysql):
    async with mysql.begin() as db:
        await db.execute(text("UPDATE tb_ai_reader_action_queue SET available_at=timestampadd(second,-301,current_timestamp) WHERE ai_reader_action_id=1"))
    assert (await post(mysql, 1)).reason == "comment_expired"
    async with mysql.connect() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM tb_product_comment"))).scalar_one() == 0
        assert (await db.execute(text("SELECT status FROM tb_ai_reader_action_queue WHERE ai_reader_action_id=1"))).scalar_one() == "skipped"


@pytest.mark.parametrize("elapsed,expected", [(1, "applied"), (2, "comment_expired")])
def test_expiry_is_checked_at_final_insert(mysql, elapsed, expected):
    asyncio.run(check_final_expiry(mysql, elapsed, expected))


async def check_final_expiry(mysql, elapsed, expected):
    async with mysql.begin() as db:
        epoch = int((await db.execute(text("SELECT UNIX_TIMESTAMP()"))).scalar_one())
        await db.execute(text("UPDATE tb_ai_reader_action_queue SET available_at=FROM_UNIXTIME(:due) WHERE ai_reader_action_id=1"), {"due": epoch - 299})

    class ClockSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if "insert into tb_product_comment" in str(statement):
                await super().execute(text("SET timestamp=:clock"), {"clock": epoch + elapsed})
            return await super().execute(statement, *args, **kwargs)

    @asynccontextmanager
    async def clock_session(_):
        async with mysql.connect() as connection:
            await connection.execute(text("SET timestamp=:clock"), {"clock": epoch})
            await connection.commit()
            async with ClockSession(bind=connection) as db:
                yield db

    result = await post(mysql, 1, pinned_session_factory=clock_session)
    assert result.reason == expected
    async with mysql.connect() as db:
        assert (await db.execute(text("SELECT COUNT(*) FROM tb_product_comment"))).scalar_one() == int(expected == "applied")
        assert (await db.execute(text("SELECT count_comment FROM tb_product_episode WHERE episode_id=300"))).scalar_one() == int(expected == "applied")
        queue = (await db.execute(text("SELECT status,UNIX_TIMESTAMP(available_at) AS due FROM tb_ai_reader_action_queue WHERE ai_reader_action_id=1"))).mappings().one()
        assert queue["status"] == ("applied" if expected == "applied" else "skipped")
        assert queue["due"] == epoch - 299


def test_human_delete_and_ai_insert_use_consistent_locks(mysql):
    asyncio.run(check_delete_lock_order(mysql))


async def check_delete_lock_order(mysql):
    async with mysql.begin() as db:
        await db.execute(text("INSERT INTO tb_product_comment (comment_id,product_id,episode_id,user_id,profile_id,content,created_date) VALUES (100,200,300,3,3,'원래 댓글',timestampadd(hour,-25,current_timestamp)),(101,200,300,4,4,'다른 댓글',timestampadd(hour,-25,current_timestamp))"))
        await db.execute(text("UPDATE tb_product_episode SET count_comment=2 WHERE episode_id=300"))
    episode_locked = asyncio.Event()
    resume_ai = asyncio.Event()

    class BarrierSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            result = await super().execute(statement, *args, **kwargs)
            if "select e.product_id, e.comment_open_yn" in str(statement):
                episode_locked.set()
                await resume_ai.wait()
            return result

    @asynccontextmanager
    async def barrier_session(_):
        async with mysql.connect() as connection:
            async with BarrierSession(bind=connection) as db:
                yield db

    async def delete():
        async with AsyncSession(mysql) as db:
            return await delete_products_comments_comment_id("100", "comment-test-3", db)

    ai = asyncio.create_task(post(mysql, 1, pinned_session_factory=barrier_session))
    deletion = None
    try:
        await asyncio.wait_for(episode_locked.wait(), timeout=5)
        deletion = asyncio.create_task(delete())
        async with mysql.connect() as observer:
            for _ in range(100):
                waits = await observer.execute(text("SELECT COUNT(*) FROM performance_schema.data_lock_waits w JOIN performance_schema.data_locks l ON l.ENGINE_LOCK_ID=w.REQUESTING_ENGINE_LOCK_ID WHERE l.OBJECT_SCHEMA=:schema"), {"schema": SCHEMA})
                if waits.scalar_one():
                    break
                await asyncio.sleep(0.02)
            else:
                pytest.fail("deletion never reached the competing lock")
        resume_ai.set()
        ai_result, delete_result = await asyncio.wait_for(asyncio.gather(ai, deletion), timeout=10)
        assert ai_result.applied
        assert delete_result["data"]["commentCount"] == 2
        async with mysql.connect() as db:
            assert (await db.execute(text("SELECT COUNT(*) FROM tb_product_comment WHERE use_yn='Y'"))).scalar_one() == 2
            assert (await db.execute(text("SELECT count_comment FROM tb_product_episode WHERE episode_id=300"))).scalar_one() == 2
    finally:
        resume_ai.set()
        await asyncio.gather(*[task for task in (ai, deletion) if task is not None], return_exceptions=True)


def test_worker_recovers_invalidated_session_before_processing_comments(mysql, monkeypatch):
    monkeypatch.setenv("AI_READER_WORKER_ENABLED", "Y")
    asyncio.run(check_worker_invalidated_session(mysql))


async def check_worker_invalidated_session(mysql):
    from app.services.ai import reader_agent_session_service as sessions
    from app.services.ai import reader_agent_worker_service as worker

    async with mysql.begin() as db:
        await db.execute(text("UPDATE tb_ai_reader_action_queue SET status='queued',locked_by=NULL"))
        await db.execute(text("INSERT INTO tb_ai_reader_daily_schedule (ai_reader_schedule_id,ai_reader_agent_id,schedule_date,active_start_at,active_end_at,status,locked_by) VALUES (1,1,CURRENT_DATE,CURRENT_TIMESTAMP,timestampadd(hour,1,current_timestamp),'running','mysql-test')"))
    claimed = sessions.ReaderClaimedSession(1, 1, 1, "30s", "M", "{}", "{}", "{}")

    async def claim_session(db, **kwargs):
        return [claimed]

    async def no_setup(db):
        return None

    async def broken_connection(session, db):
        await db.execute(text("SELECT 1"))
        connection = await db.connection()
        await connection.invalidate()
        raise ConnectionError("test-only DB connection lost inside reader decision")

    async def process_session(session, db, *, worker_id):
        return await sessions.process_claimed_reader_session(
            session, db, worker_id=worker_id, decision_func=broken_connection,
        )

    worker.reset_reader_session_credit_cooldown_for_tests()
    async with AsyncSession(mysql) as db:
        result = await worker.run_reader_worker_cycle(
            db, worker_id="mysql-test", session_claimer=claim_session,
            session_processor=process_session, schema_guard=no_setup, expired_agent_pauser=no_setup,
        )
    assert result.failed_session_count == 1
    assert result.claimed_action_count == 4
    assert result.processed_action_count == 4
    assert result.failed_action_count == 0
    async with mysql.connect() as db:
        failed = (await db.execute(text("SELECT status,error_message FROM tb_ai_reader_daily_schedule WHERE ai_reader_schedule_id=1"))).mappings().one()
        assert failed["status"] == "failed"
        assert failed["error_message"] == "test-only DB connection lost inside reader decision"
        assert (await db.execute(text("SELECT COUNT(*) FROM tb_product_comment"))).scalar_one() == 1
        assert (await db.execute(text("SELECT COUNT(*) FROM tb_ai_reader_action_queue WHERE status='applied'"))).scalar_one() == 1
        assert (await db.execute(text("SELECT COUNT(*) FROM tb_ai_reader_action_queue WHERE status='skipped'"))).scalar_one() == 3
