"""Offline Docker execution helper (--network=none, stripped .git for blind solves)."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExecResult:
    returncode: int
    stdout: str
    stderr: str


def run_in_offline_docker(
    image: str,
    workspace_dir: Path,
    cmd: list[str],
    timeout_sec: int = 300,
    strip_git: bool = False,
) -> ExecResult:
    """Runs a command inside an isolated offline Docker container against a clean copy."""
    with tempfile.TemporaryDirectory(prefix="factory_sandbox_") as tmp:
        mounted = Path(tmp) / "repo"
        shutil.copytree(
            workspace_dir,
            mounted,
            ignore=shutil.ignore_patterns(".git") if strip_git else None,
        )
        docker_cmd = [
            "docker", "run", "--rm",
            "--network=none",
            "--cpus=2",
            "--memory=2g",
            "-v", f"{mounted.resolve()}:/workspace",
            "-w", "/workspace",
            image,
            *cmd,
        ]
        proc = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return ExecResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
