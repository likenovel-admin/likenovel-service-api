import asyncio
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent


def test_ai_reader_worker_timezone_uses_bound_parameter():
    from scripts.run_ai_reader_worker import set_ai_reader_worker_db_timezone

    captured = {}

    class FakeDb:
        async def execute(self, statement, params=None):
            captured["statement"] = str(statement)
            captured["params"] = params

    asyncio.run(set_ai_reader_worker_db_timezone(FakeDb()))

    assert captured == {
        "statement": "set time_zone = :tz",
        "params": {"tz": "+09:00"},
    }


def test_prod_deploy_bundle_includes_ai_reader_worker_script():
    workflow = REPO_ROOT / ".github" / "workflows" / "deploy_be_actions.yml"
    content = workflow.read_text(encoding="utf-8")

    assert "cp ../scripts/run_ai_reader_worker.py ./scripts/run_ai_reader_worker.py" in content
    assert "zip -r $GITHUB_SHA.zip" in content
    assert "scripts/" in content


def test_prod_wheel_pins_sqlalchemy_for_aiomysql_pre_ping():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    sqlalchemy_dependency = pyproject["tool"]["poetry"]["dependencies"]["sqlalchemy"]

    assert sqlalchemy_dependency == {
        "extras": ["asyncio"],
        "version": "2.0.41",
    }


def test_prod_run_script_replaces_and_starts_ai_reader_worker():
    run_script = PROJECT_ROOT / "dist" / "run_be.sh"
    content = run_script.read_text(encoding="utf-8")

    assert "source .env" not in content
    assert "load_env_file .env" in content
    assert "stop_pidfile_process()" in content
    assert "ai_reader_worker.pid" in content
    assert "ai_reader_worker_manual_*.pid" in content
    assert "kill -KILL" in content
    assert "AI_READER_WORKER_ENABLED=Y nohup ./.venv/bin/python -u scripts/run_ai_reader_worker.py" in content
    assert "--worker-id \"ai-reader-prod-$(hostname)\"" in content
    assert "[ERROR] AI reader worker failed to start" in content


def test_deploy_run_scripts_do_not_source_env_files():
    for script_name in ("run_be.sh", "run_be.dev.sh"):
        content = (PROJECT_ROOT / "dist" / script_name).read_text(encoding="utf-8")

        assert "source .env" not in content
        assert "load_env_file .env" in content
        assert "while IFS= read -r line" in content
