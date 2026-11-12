#!/usr/bin/env python3
"""Execute DEV hooks with a denied DB time budget, before any mutation."""
import os
from pathlib import Path
import subprocess
import tempfile

BASE = Path(__file__).resolve().parents[1] / "dist"
with tempfile.TemporaryDirectory() as directory:
    temp = Path(directory)
    trace = temp / "calls"
    for name, code in (("grep", 0), ("python3", 23), ("mkdir", 99), ("date", 99), ("find", 99), ("systemctl", 99)):
        command = temp / name
        command.write_text('#!/bin/sh\nprintf "%s\n" "' + name + '" >> "$DEV_GUARD_TRACE"\nexit ' + str(code) + '\n')
        command.chmod(0o700)
    for script in ("before_install.dev.sh", "run_be.dev.sh"):
        trace.write_text("")
        result = subprocess.run(["/bin/bash", str(BASE / script)], text=True,
            capture_output=True, timeout=5,
            env={"PATH": str(temp), "DEV_GUARD_TRACE": str(trace)})
        assert result.returncode == 23, (script, result.returncode, result.stderr)
        assert trace.read_text().splitlines() == ["grep", "python3"], (script, trace.read_text())
    (temp / "grep").write_text('#!/bin/sh\nexit 42\n')
    for script in ("before_install.dev.sh", "run_be.dev.sh"):
        trace.write_text("")
        result = subprocess.run(["/bin/bash", str(BASE / script)], text=True,
            capture_output=True, timeout=5,
            env={"PATH": str(temp), "DEV_GUARD_TRACE": str(trace)})
        assert result.returncode == 42, (script, result.returncode)
        assert trace.read_text() == "", "old server must never execute the old Python stopper"
print("DEV deployment budget/version guards reject before mutation: PASS")
