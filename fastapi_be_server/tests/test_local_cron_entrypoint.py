import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "dist" / "batch" / "start-cron.sh"


def _write_fake_service(path: Path) -> None:
    command = path / "service"
    command.write_text(
        "#!/bin/sh\n"
        'printf "service:%s\\n" "$*" >> "$CALL_LOG"\n'
        'case "${1:-}:${2:-}" in\n'
        '  cron:start) touch "$FAKE_CRON_SERVICE_STATE"; exit 0 ;;\n'
        '  cron:stop) rm -f "$FAKE_CRON_SERVICE_STATE"; exit 0 ;;\n'
        '  cron:status) [ -r "$FAKE_CRON_SERVICE_STATE" ] ;;\n'
        '  *) exit 1 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    command.chmod(0o755)


def _write_fake_crontab(path: Path) -> None:
    command = path / "crontab"
    command.write_text(
        "#!/bin/sh\n"
        'printf "crontab:%s\\n" "$*" >> "$CALL_LOG"\n'
        'case "${1:-}" in\n'
        '  -r) rm -f "$FAKE_CRONTAB_STATE"; exit 0 ;;\n'
        '  -l)\n'
        '    if [ "${FAKE_CRONTAB_STICKY:-0}" = "1" ]; then echo "* * * * * stale"; exit 0; fi\n'
        '    [ -r "$FAKE_CRONTAB_STATE" ] || exit 1\n'
        '    cat "$FAKE_CRONTAB_STATE"\n'
        '    exit 0\n'
        '    ;;\n'
        '  *) printf "* * * * * installed from %s\\n" "$1" > "$FAKE_CRONTAB_STATE"; exit 0 ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    command.chmod(0o755)


def _run_entrypoint(tmp_path: Path, **overrides: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_crontab(fake_bin)
    _write_fake_service(fake_bin)

    call_log = tmp_path / "calls.log"
    env = os.environ.copy()
    env.update(overrides)
    env["CALL_LOG"] = str(call_log)
    env["FAKE_CRONTAB_STATE"] = str(tmp_path / "crontab.state")
    env["FAKE_CRON_SERVICE_STATE"] = str(tmp_path / "cron-service.state")
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        [str(ENTRYPOINT), "sh", "-c", "printf APP_STARTED"],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
    return result, calls


def test_local_cron_is_disabled_by_default_and_application_starts(tmp_path: Path) -> None:
    result, calls = _run_entrypoint(tmp_path)

    assert result.returncode == 0
    assert result.stdout.endswith("APP_STARTED")
    assert "crontab:-r" in calls
    assert "service:cron stop" in calls
    assert "service:cron start" not in calls


def test_local_cron_can_be_enabled_explicitly(tmp_path: Path) -> None:
    result, calls = _run_entrypoint(tmp_path, LOCAL_BATCH_CRON_ENABLE="1")

    assert result.returncode == 0
    assert result.stdout.endswith("APP_STARTED")
    assert "crontab:/app/dist/batch/cron_job.sh" in calls
    assert "service:cron start" in calls
    assert "service:cron status" in calls
    assert "crontab:-r" not in calls


def test_api_entrypoint_refuses_to_start_when_crontab_remains_disabled(tmp_path: Path) -> None:
    result, _ = _run_entrypoint(tmp_path, FAKE_CRONTAB_STICKY="1")

    assert result.returncode != 0
    assert "local crontab remains after API startup" in result.stderr
    assert "APP_STARTED" not in result.stdout


def test_api_entrypoint_refuses_unknown_cron_switch_value(tmp_path: Path) -> None:
    result, calls = _run_entrypoint(tmp_path, LOCAL_BATCH_CRON_ENABLE="yes")

    assert result.returncode != 0
    assert "LOCAL_BATCH_CRON_ENABLE must be 0 or 1" in result.stderr
    assert "APP_STARTED" not in result.stdout
    assert calls == []
