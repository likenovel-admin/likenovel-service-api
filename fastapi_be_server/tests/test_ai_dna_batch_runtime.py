import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
BATCH_SCRIPT = ROOT / "dist" / "batch" / "ai_dna_extract_daily_batch.sh"
TIMESTAMP_HELPER = ROOT / "dist" / "batch" / "batch_timestamp_logging.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class AiDnaBatchRuntimeTest(TestCase):
    def _run_batch(self, *, container_layout: bool) -> list[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            batch_dir = root / ("dist/batch" if container_layout else "batch")
            batch_dir.mkdir(parents=True)
            batch_script = batch_dir / BATCH_SCRIPT.name
            batch_script.write_text(
                BATCH_SCRIPT.read_text(encoding="utf-8").replace(
                    'LOCK_DIR="/tmp/ai-dna-extract-daily-batch.lock"',
                    f'LOCK_DIR="{root / "ai-dna.lock"}"',
                ),
                encoding="utf-8",
            )
            batch_script.chmod(batch_script.stat().st_mode | stat.S_IXUSR)
            shutil.copy2(TIMESTAMP_HELPER, batch_dir / TIMESTAMP_HELPER.name)
            (batch_dir / "extract_product_dna.py").write_text("", encoding="utf-8")

            call_log = root / "python-calls.log"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            _write_executable(
                fake_bin / "mysql",
                "#!/bin/sh\ncat >/dev/null\nexit 0\n",
            )
            _write_executable(
                fake_bin / "python3",
                '#!/bin/sh\nprintf "system:%s\\n" "$*" >> "$CALL_LOG"\nexit 0\n',
            )

            if not container_layout:
                venv_python = root / "api/.venv/bin/python"
                venv_python.parent.mkdir(parents=True)
                _write_executable(
                    venv_python,
                    '#!/bin/sh\nprintf "venv:%s\\n" "$*" >> "$CALL_LOG"\nexit 0\n',
                )

            env = {
                **os.environ,
                "AI_DNA_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "test-key",
                "DB_USER": "test-user",
                "DB_PW": "test-password",
                "MYSQL_SSL_OPT": "--skip-ssl",
                "CALL_LOG": str(call_log),
                "PATH": f"{fake_bin}:/usr/bin:/bin",
            }
            completed = subprocess.run(
                ["/bin/bash", str(batch_script)],
                cwd=batch_dir,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            return call_log.read_text(encoding="utf-8").splitlines()

    def test_prod_layout_prefers_deployed_api_virtualenv(self) -> None:
        calls = self._run_batch(container_layout=False)

        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("venv:"), calls)
        self.assertTrue(calls[0].endswith("extract_product_dna.py --all"), calls)

    def test_container_layout_falls_back_to_system_python(self) -> None:
        calls = self._run_batch(container_layout=True)

        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("system:"), calls)
        self.assertTrue(calls[0].endswith("extract_product_dna.py --all"), calls)
