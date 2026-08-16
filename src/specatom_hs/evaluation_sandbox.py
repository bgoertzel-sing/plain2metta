"""Small subprocess boundary for deterministic evaluation output."""

from __future__ import annotations

import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

METTA_RUNTIME = os.environ.get("PLAIN2METTA_METTA_BIN", "metta")
METTA_RUNTIME_VERSION = "0.2.10"


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024, 128 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))


def run_python_reference(source: str, timeout_seconds: int = 2) -> dict:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="plain2metta-eval-") as temporary:
        path = Path(temporary) / "evaluation.py"
        path.write_text(source, encoding="utf-8")
        completed = subprocess.run(
            (sys.executable, "-I", str(path)), cwd=temporary,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=timeout_seconds, check=False, env={"PATH": os.environ.get("PATH", "")},
            preexec_fn=_limits,
        )
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout[:16_384],
        "stderr": completed.stderr[:16_384],
        "duration_ms": max(1, int((time.monotonic() - started) * 1000)),
        "limits": {"cpu_seconds": 2, "memory_mib": 128, "file_mib": 1, "processes": 1, "timeout_seconds": timeout_seconds},
    }


def run_metta_reference(source: str, timeout_seconds: int = 2) -> dict:
    """Execute generated MeTTa with the pinned Hyperon CLI under the same limits."""
    runtime_name = shutil.which(METTA_RUNTIME)
    if runtime_name is None:
        raise RuntimeError(f"pinned MeTTa runtime is unavailable: {METTA_RUNTIME}")
    runtime = Path(runtime_name).resolve()
    version = subprocess.run(
        (str(runtime), "--version"), stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=timeout_seconds, check=False,
        env={"PATH": os.environ.get("PATH", "")},
    )
    if version.returncode != 0 or version.stdout.strip() != METTA_RUNTIME_VERSION:
        raise RuntimeError("pinned MeTTa runtime version mismatch")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="plain2metta-metta-") as temporary:
        path = Path(temporary) / "evaluation.metta"
        path.write_text(source, encoding="utf-8")
        completed = subprocess.run(
            (str(runtime), str(path)), cwd=temporary,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=timeout_seconds, check=False, env={"PATH": os.environ.get("PATH", "")},
            preexec_fn=_limits,
        )
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout[:16_384], "stderr": completed.stderr[:16_384],
        "duration_ms": max(1, int((time.monotonic() - started) * 1000)),
        "runtime": "hyperon-cli", "runtime_version": METTA_RUNTIME_VERSION,
        "runtime_path": METTA_RUNTIME,
        "limits": {"cpu_seconds": 2, "memory_mib": 128, "file_mib": 1, "processes": 1, "timeout_seconds": timeout_seconds},
    }
