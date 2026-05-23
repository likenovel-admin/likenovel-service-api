import asyncio
import inspect
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
    assert "verify_backend_prod_deploy.sh" in content
    assert "scripts/" in content


def test_prod_workflow_runs_pre_deploy_quality_gates_and_waits_for_codedeploy():
    workflow = REPO_ROOT / ".github" / "workflows" / "deploy_be_actions.yml"
    content = workflow.read_text(encoding="utf-8")

    assert "poetry run python tests/test_ai_reader_worker_deploy.py" in content
    assert "shellcheck --severity=warning dist/run_be.sh dist/boot-start-api.sh dist/verify_backend_prod_deploy.sh" in content
    assert "bash -n dist/run_be.sh" in content
    assert "bash -n dist/boot-start-api.sh" in content
    assert "bash -n dist/verify_backend_prod_deploy.sh" in content
    assert "DEPLOY_ID=$(aws deploy create-deployment" in content
    assert 'aws deploy wait deployment-successful --deployment-id "$DEPLOY_ID"' in content
    assert 'aws deploy get-deployment --deployment-id "$DEPLOY_ID"' in content


def test_prod_workflow_runs_hard_readback_over_bastion():
    workflow = REPO_ROOT / ".github" / "workflows" / "deploy_be_actions.yml"
    content = workflow.read_text(encoding="utf-8")

    assert "SSH_PRIVATE_KEY: ${{ secrets.SSH_PRIVATE_KEY }}" in content
    assert "ssh -i ~/.ssh/likenovel_prod_deploy_key" in content
    assert "ln-admin@ec2-3-34-11-39.ap-northeast-2.compute.amazonaws.com" in content
    assert "ln-admin@10.0.100.110" in content
    assert "bash -s' < ./verify_backend_prod_deploy.sh" in content


def test_prod_verify_script_checks_runtime_process_worker_and_versions():
    content = (PROJECT_ROOT / "dist" / "verify_backend_prod_deploy.sh").read_text(
        encoding="utf-8"
    )

    assert "SERVICE_NAME=likenovel-api.service" in content
    assert "PID_FILE=/home/ln-admin/likenovel/api/gunicorn.pid" in content
    assert "AI_READER_WORKER_LOG=/home/ln-admin/likenovel/api/logs/data/ai_reader_worker.log" in content
    assert "systemctl show" in content
    assert "MainPID" in content
    assert "ss -ltnp" in content
    assert "10.0.100.110:3010/health" in content
    assert "ai_reader_worker.pid" in content
    assert "ai reader worker cycle completed" in content
    assert "from importlib.metadata import version" in content
    assert "sqlalchemy==2.0.41" in content
    assert "pymysql==1.1.1" in content
    assert "aiomysql==0.2.0" in content
    assert "exit 1" in content


def test_prod_wheel_pins_mysql_driver_stack_for_aiomysql_pre_ping():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["tool"]["poetry"]["dependencies"]

    assert dependencies["sqlalchemy"] == {
        "extras": ["asyncio"],
        "version": "2.0.41",
    }
    assert dependencies["pymysql"] == "1.1.1"
    assert dependencies["aiomysql"] == "0.2.0"


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


def test_prod_run_script_uses_strict_mode_and_explicit_venv_pip():
    content = (PROJECT_ROOT / "dist" / "run_be.sh").read_text(encoding="utf-8")
    first_lines = content.splitlines()[:3]

    assert first_lines == ["#!/bin/bash", "set -euo pipefail", ""]
    assert "source .venv/bin/activate" not in content
    assert "deactivate" not in content
    assert '"$NEXT_VENV/bin/python" -m pip install --upgrade pip' in content
    assert '"$NEXT_VENV/bin/pip" install "$(ls -v app-*.whl | tail -n 1)"' in content
    assert "from importlib.metadata import version" in content
    assert "[run_be] installed {package}==" in content
    assert 'chmod +x "$BATCH_DST"/*.sh' not in content
    assert 'for batch_script in "$BATCH_DST"/*.sh; do' in content


def test_prod_run_script_prebuilds_next_venv_before_stopping_service():
    content = (PROJECT_ROOT / "dist" / "run_be.sh").read_text(encoding="utf-8")
    main_flow = content[content.index("\nrequire_systemd_access\n") :]

    assert "NEXT_VENV=.venv-next" in content
    assert "PREV_VENV=.venv-prev" in content
    assert "prepare_next_venv" in content
    assert "activate_next_venv" in content
    assert "restore_previous_venv_and_restart" in content
    assert "rm -rf ./.venv" not in content
    assert 'mv .venv "$PREV_VENV"' in content
    assert 'mv "$NEXT_VENV" .venv' in content
    assert 'rm -rf "$PREV_VENV"' in content

    assert main_flow.index("prepare_next_venv") < main_flow.index("stop_service_and_orphans")
    assert main_flow.index("stop_service_and_orphans") < main_flow.index("activate_next_venv")
    assert main_flow.index("activate_next_venv") < main_flow.index("start_service_and_verify")


def test_prod_run_script_validates_env_before_stopping_service_or_copying_env():
    content = (PROJECT_ROOT / "dist" / "run_be.sh").read_text(encoding="utf-8")
    main_flow = content[content.index("\nrequire_systemd_access\n") :]

    assert "validate_env_file()" in content
    assert "verify_env_database_connection()" in content
    assert "activate_next_env()" in content
    assert "ENV_BACKUP=.env.prev" in content
    assert "validate_env_file .env.production" in main_flow
    assert "verify_env_database_connection .env.production" in main_flow
    assert "activate_next_env" in main_flow
    assert "cp .env.production .env" in content
    assert 'load_env_file "$env_file"' in content

    assert main_flow.index("validate_env_file .env.production") < main_flow.index("prepare_next_venv")
    assert main_flow.index("prepare_next_venv") < main_flow.index("verify_env_database_connection .env.production")
    assert main_flow.index("verify_env_database_connection .env.production") < main_flow.index("stop_service_and_orphans")
    assert main_flow.index("stop_service_and_orphans") < main_flow.index("activate_next_env")
    assert main_flow.index("activate_next_env") < main_flow.index("load_env_file .env")
    assert main_flow.index("load_env_file .env") < main_flow.index("start_service_and_verify")


def test_prod_run_script_env_validator_has_minimal_hard_guards():
    content = (PROJECT_ROOT / "dist" / "run_be.sh").read_text(encoding="utf-8")

    assert "REQUIRED_ENV_KEYS=(DB_USER_ID DB_USER_PW DB_IP DB_PORT)" in content
    assert 'PATH_ENV_KEYS=(ROOT_PATH FCM_SERVICE_ACCOUNT_JSON_PATH)' in content
    assert 'invalid env key at line ${line_no}: $key' in content
    assert 'malformed env line ${line_no}' in content
    assert 'duplicate env key: $key' in content
    assert 'missing required env key: $required_key' in content
    assert 'DB_PORT must be numeric' in content
    assert 'path env must be absolute: $path_key' in content


def test_prod_run_script_db_smoke_uses_new_venv_and_env_production_before_stop():
    content = (PROJECT_ROOT / "dist" / "run_be.sh").read_text(encoding="utf-8")

    assert '"$NEXT_VENV/bin/python" - <<\'PY\'' in content
    assert "from sqlalchemy import text" in content
    assert "from sqlalchemy.ext.asyncio import create_async_engine" in content
    assert "from app.const import settings" in content
    assert 'await conn.execute(text("SELECT 1"))' in content
    assert "[run_be] DB smoke check passed" in content


def test_prod_run_script_rolls_back_venv_if_systemd_start_fails():
    content = (PROJECT_ROOT / "dist" / "run_be.sh").read_text(encoding="utf-8")
    failure_block = content[
        content.index('if ! start_service_and_verify; then') :
        content.index("# 배치 파일 동기화")
    ]

    assert 'if ! start_service_and_verify; then' in content
    assert "restore_previous_venv_and_restart" in content
    assert "restore_previous_env" in content
    assert 'mv .venv "$NEXT_VENV.failed"' in content
    assert 'mv "$PREV_VENV" .venv' in content
    assert 'mv "$ENV_BACKUP" .env' in content
    assert 'sudo -n systemctl start "$SERVICE_NAME"' in content
    assert "start_ai_reader_worker" in failure_block
    assert failure_block.index("restore_previous_venv_and_restart") < failure_block.index("start_ai_reader_worker")
    assert failure_block.index("start_ai_reader_worker") < failure_block.index("exit 1")
    assert "exit 1" in failure_block


def test_prod_run_script_uses_systemd_as_gunicorn_owner():
    content = (PROJECT_ROOT / "dist" / "run_be.sh").read_text(encoding="utf-8")

    assert "SERVICE_NAME=likenovel-api.service" in content
    assert "require_systemd_access" in content
    assert "stop_service_and_orphans" in content
    assert "start_service_and_verify" in content
    assert 'sudo -n systemctl stop "$SERVICE_NAME"' in content
    assert 'sudo -n systemctl start "$SERVICE_NAME"' in content
    assert "gunicorn -c ./gconf.py" not in content


def test_prod_run_script_cleans_current_python_module_gunicorn_orphans():
    content = (PROJECT_ROOT / "dist" / "run_be.sh").read_text(encoding="utf-8")

    assert '"/home/ln-admin/likenovel/api/.venv/bin/gunicorn -c"' in content
    assert (
        '"/home/ln-admin/likenovel/api/.venv/bin/python -m gunicorn.app.wsgiapp -c"'
        in content
    )
    assert 'for orphan_pattern in "${orphan_patterns[@]}"; do' in content
    assert 'pkill -TERM -f "$orphan_pattern"' in content
    assert 'pkill -KILL -f "$orphan_pattern"' in content


def test_prod_workflow_bundles_boot_start_script():
    workflow = REPO_ROOT / ".github" / "workflows" / "deploy_be_actions.yml"
    content = workflow.read_text(encoding="utf-8")

    assert "chmod +x run_be.sh boot-start-api.sh verify_backend_prod_deploy.sh" in content
    assert "boot-start-api.sh" in content
    assert (PROJECT_ROOT / "dist" / "boot-start-api.sh").is_file()


def test_prod_boot_start_uses_python_module_not_moved_console_script():
    content = (PROJECT_ROOT / "dist" / "boot-start-api.sh").read_text(encoding="utf-8")

    assert (
        'exec "$APP_DIR/.venv/bin/python" -m gunicorn.app.wsgiapp -c "$APP_DIR/gconf.py"'
        in content
    )
    assert 'exec "$APP_DIR/.venv/bin/gunicorn" -c "$APP_DIR/gconf.py"' not in content


def test_deploy_run_scripts_do_not_source_env_files():
    for script_name in ("run_be.sh", "run_be.dev.sh"):
        content = (PROJECT_ROOT / "dist" / script_name).read_text(encoding="utf-8")

        assert "source .env" not in content
        assert "load_env_file .env" in content
        assert "while IFS= read -r line" in content


def test_dev_run_script_uses_systemd_as_gunicorn_owner():
    content = (PROJECT_ROOT / "dist" / "run_be.dev.sh").read_text(encoding="utf-8")

    assert "SERVICE_NAME=likenovel-api-dev.service" in content
    assert 'sudo -n systemctl stop "$SERVICE_NAME"' in content
    assert 'sudo -n systemctl start "$SERVICE_NAME"' in content
    assert "gunicorn -c ./gconf.py" not in content


def test_dev_codedeploy_uses_staging_destination_for_symlink_release():
    appspec = PROJECT_ROOT / "dist" / "appspec.dev.yml"
    content = appspec.read_text(encoding="utf-8")

    assert "destination: /home/ln-admin/likenovel/api-dev-deploy" in content
    assert "destination: /home/ln-admin/likenovel/api-dev\n" not in content
    assert "BeforeInstall:" in content
    assert "location: before_install.sh" in content


def test_dev_workflow_bundles_versioned_boot_start_script():
    workflow = REPO_ROOT / ".github" / "workflows" / "deploy_be_actions_dev.yml"
    content = workflow.read_text(encoding="utf-8")

    assert "cp before_install.dev.sh before_install.sh" in content
    assert "chmod +x before_install.sh run_be.sh boot-start-api-dev.sh" in content
    assert "zip -r $GITHUB_SHA.zip" in content
    assert "before_install.sh" in content
    assert "boot-start-api-dev.sh" in content
    assert (PROJECT_ROOT / "dist" / "before_install.dev.sh").is_file()
    assert (PROJECT_ROOT / "dist" / "boot-start-api-dev.sh").is_file()


def test_dev_run_script_prepares_release_before_service_stop_and_retains_five():
    content = (PROJECT_ROOT / "dist" / "run_be.dev.sh").read_text(encoding="utf-8")
    main_flow = content[content.index("require_systemd_access"):]

    assert "DEPLOY_DIR=/home/ln-admin/likenovel/api-dev-deploy" in content
    assert "CURRENT_LINK=/home/ln-admin/likenovel/api-dev" in content
    assert "RELEASE_BASE=/home/ln-admin/likenovel/releases/api-dev" in content
    assert "RELEASE_KEEP=5" in content
    assert '${DEPLOYMENT_ID:-${CODEDEPLOY_DEPLOYMENT_ID:-manual-$$}}' in content
    assert "ls -t app-*.whl | head -n 1" in content
    assert "prepare_release" in content
    assert "switch_current_link" in content
    assert "rollback_to_previous_release" in content
    assert 'cleanup_old_releases "$RELEASE_KEEP"' in content
    assert "replace_current_symlink" in content
    assert 'mv -Tf "$tmp_link" "$CURRENT_LINK"' in content
    assert 'rm -f "$CURRENT_LINK"' not in content

    assert main_flow.index("prepare_release") < main_flow.index("stop_service_and_orphans")
    assert main_flow.index("stop_service_and_orphans") < main_flow.index("switch_current_link")
    assert main_flow.index("start_service_and_verify") < main_flow.index('cleanup_old_releases "$RELEASE_KEEP"')


def test_dev_before_install_prunes_only_guarded_staging_dir():
    content = (PROJECT_ROOT / "dist" / "before_install.dev.sh").read_text(encoding="utf-8")

    assert "DEPLOY_DIR=/home/ln-admin/likenovel/api-dev-deploy" in content
    assert 'case "$DEPLOY_DIR" in' in content
    assert '"/home/ln-admin/likenovel/api-dev-deploy")' in content
    assert 'find "$DEPLOY_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +' in content
    assert "api-dev" in content
    assert "api-dev-deploy" in content


def _run_direct_tests(namespace):
    for name, test_func in sorted(namespace.items()):
        if not name.startswith("test_") or not callable(test_func):
            continue
        required_params = [
            param
            for param in inspect.signature(test_func).parameters.values()
            if param.default is inspect.Parameter.empty
            and param.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if required_params:
            continue
        test_func()


def test_direct_runner_skips_pytest_fixture_style_tests():
    called = []

    def test_plain_contract():
        called.append("plain")

    def test_needs_tmp_path(tmp_path):
        called.append(f"fixture:{tmp_path}")

    _run_direct_tests(
        {
            "test_plain_contract": test_plain_contract,
            "test_needs_tmp_path": test_needs_tmp_path,
            "helper": lambda: called.append("helper"),
        }
    )

    assert called == ["plain"]


if __name__ == "__main__":
    _run_direct_tests(globals())
