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
    assert "verify_backend_prod_deploy.sh" in content
    assert "chmod +x verify_backend_prod_deploy.sh" in content
    assert "scripts/" in content


def test_prod_workflow_runs_pre_deploy_quality_gates_and_waits_for_codedeploy():
    workflow = REPO_ROOT / ".github" / "workflows" / "deploy_be_actions.yml"
    content = workflow.read_text(encoding="utf-8")

    assert "poetry run python tests/test_ai_reader_worker_deploy.py" in content
    assert "shellcheck --severity=warning dist/run_be.sh dist/verify_backend_prod_deploy.sh" in content
    assert "bash -n dist/run_be.sh" in content
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


if __name__ == "__main__":
    for name, test_func in sorted(globals().items()):
        if name.startswith("test_") and callable(test_func):
            test_func()
