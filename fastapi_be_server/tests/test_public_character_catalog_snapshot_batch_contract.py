import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.utils.auto_migrate import _parse_statements


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_snapshot_schema_is_parseable_and_keeps_one_active_generation_per_scope():
    migration = _read("dist/init/110-create-public-character-catalog-snapshot.sql")
    statements = _parse_statements(migration)

    assert len(statements) == 2
    assert "UNIQUE KEY uk_public_character_catalog_active_scope (active_scope)" in migration
    assert "PRIMARY KEY (generation_id, adult_yn, display_order)" in migration
    assert "ON DELETE CASCADE" in migration


def test_refresh_has_single_flight_consistent_build_and_no_request_fallback():
    refresh = _read("scripts/refresh_public_character_catalog_snapshot.py")
    reader = _read("app/services/product/main_character_slot_service.py")

    assert "SELECT GET_LOCK(:lock_name, 0)" in refresh
    assert 'isolation_level="REPEATABLE READ"' in refresh
    assert "for adult_yn in PUBLIC_CHARACTER_CATALOG_SCOPES" in refresh
    assert "SELECT RELEASE_LOCK(:lock_name)" in refresh
    assert "_load_public_character_catalog_base" not in reader.split(
        "async def get_public_main_character_slots", 1
    )[1].split("async def _load_public_character_catalog_base", 1)[0]


def test_batch_wiring_is_bounded_and_dev_schedule_remains_disabled():
    wrapper = _read("dist/batch/public_character_catalog_snapshot_batch.sh")
    story_context = _read("dist/batch/build_story_agent_context_batch.sh")
    cron_env = _read("dist/batch/cron_env.sh")
    prod_cron = _read("dist/run_be.sh")
    dev_cron = _read("dist/batch/cron_job.dev.sh")

    assert "timeout --signal=TERM --kill-after=10s 120s" in wrapper
    assert "public_character_catalog_snapshot_batch.sh" in story_context
    assert 'PUBLIC_CHARACTER_CATALOG_SNAPSHOT_AUTO_REFRESH_ENABLE:-0' in story_context
    assert cron_env.count("PUBLIC_CHARACTER_CATALOG_SNAPSHOT_AUTO_REFRESH_ENABLE") == 2
    assert '[ "${PUBLIC_CHARACTER_CATALOG_SNAPSHOT_AUTO_REFRESH_ENABLE}" = "1" ]' in story_context
    assert 'PUBLIC_CHARACTER_CATALOG_SNAPSHOT_AUTO_REFRESH_ENABLE:-0' in prod_cron
    assert '[ "$PUBLIC_CHARACTER_CATALOG_SNAPSHOT_AUTO_REFRESH_ENABLE" = "1" ]' in prod_cron
    assert 'grep -Fv "/home/ln-admin/likenovel/batch/public_character_catalog_snapshot_batch.sh"' in prod_cron
    assert "7,22,37,52 * * * *" in prod_cron
    assert "# 7,22,37,52 * * * *" in dev_cron


def test_backend_deploy_workflows_package_snapshot_refresh_script():
    copy_line = (
        "cp ../scripts/refresh_public_character_catalog_snapshot.py "
        "./scripts/refresh_public_character_catalog_snapshot.py"
    )

    for workflow_path in (
        ".github/workflows/deploy_be_actions_dev.yml",
        ".github/workflows/deploy_be_actions.yml",
    ):
        workflow = (ROOT.parent / workflow_path).read_text(encoding="utf-8")
        assert copy_line in workflow


def _run_wrapper(tmp_path: Path, *, python_exit: int, timeout_exit: int | None = None):
    api_root = tmp_path / "api"
    batch_dir = api_root / "dist" / "batch"
    scripts_dir = api_root / "scripts"
    fake_bin = tmp_path / "bin"
    batch_dir.mkdir(parents=True)
    scripts_dir.mkdir(parents=True)
    fake_bin.mkdir()

    wrapper = batch_dir / "public_character_catalog_snapshot_batch.sh"
    shutil.copy2(ROOT / "dist/batch/public_character_catalog_snapshot_batch.sh", wrapper)
    (scripts_dir / "refresh_public_character_catalog_snapshot.py").write_text(
        "# wrapper execution fixture\n", encoding="utf-8"
    )
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        '#!/bin/sh\nexit "${FAKE_PYTHON_EXIT_CODE:-0}"\n', encoding="utf-8"
    )
    fake_python.chmod(0o755)

    if timeout_exit is not None:
        fake_timeout = fake_bin / "timeout"
        fake_timeout.write_text(
            f"#!/bin/sh\nexit {timeout_exit}\n", encoding="utf-8"
        )
        fake_timeout.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "FAKE_PYTHON_EXIT_CODE": str(python_exit),
    }
    return subprocess.run(
        ["bash", str(wrapper)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.parametrize("python_exit", [0, 9])
def test_wrapper_preserves_refresh_exit_code(tmp_path, python_exit):
    result = _run_wrapper(tmp_path, python_exit=python_exit)

    assert result.returncode == python_exit
    if python_exit == 0:
        assert "refresh completed" in result.stdout
    else:
        assert "refresh failed exit=9" in result.stderr


def test_wrapper_preserves_timeout_exit_code(tmp_path):
    result = _run_wrapper(tmp_path, python_exit=0, timeout_exit=124)

    assert result.returncode == 124
    assert "refresh failed exit=124" in result.stderr
