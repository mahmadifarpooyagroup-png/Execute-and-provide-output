import asyncio
import os
import shutil
import sys
import time
from typing import Any, Callable, Optional

import psutil

from .execution_models import ExecutionAction, ExecutionResult, ExecutionTarget, PermissionLevel


class ExecutionBus:
    """Vendor-neutral secure process execution bus."""

    def __init__(self, *, allowed_env_keys: Optional[list[str]] = None):
        self.allowed_env_keys = allowed_env_keys or [
            "PATH",
            "HOME",
            "USERPROFILE",
            "TEMP",
            "TMP",
            "SYSTEMROOT",
            "COMSPEC",
            "PATHEXT",
            "PYTHONPATH",
            "TERM",
        ]

    async def execute(
        self,
        action: ExecutionAction,
        permission_check_callback: Callable[..., bool],
    ) -> ExecutionResult:
        start = time.perf_counter()

        if not self._permission_allowed(action, permission_check_callback):
            duration_ms = (time.perf_counter() - start) * 1000.0
            return ExecutionResult(
                action_id=action.action_id,
                status="permission_denied",
                stdout="",
                stderr="",
                exit_code=1,
                duration_ms=duration_ms,
                evidence=f"Permission denied for action {action.action_id} requiring {action.permission_required.name}",
                error_message="Permission denied by policy.",
            )

        command = self._build_command(action)
        env = self._build_environment()

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=action.working_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            return ExecutionResult(
                action_id=action.action_id,
                status="failed",
                stdout="",
                stderr=str(exc),
                exit_code=127,
                duration_ms=duration_ms,
                evidence=f"Executable not found for {action.execution_target.value}",
                error_message=str(exc),
            )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=action.timeout_seconds,
            )
        except asyncio.TimeoutError:
            await self._terminate_tree(proc)
            duration_ms = (time.perf_counter() - start) * 1000.0
            message = f"Action exceeded its {action.timeout_seconds}s timeout."
            return ExecutionResult(
                action_id=action.action_id,
                status="timed_out",
                exit_code=124,
                duration_ms=duration_ms,
                evidence=self._build_evidence(action, "", message, 124),
                error_message=message,
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
        duration_ms = (time.perf_counter() - start) * 1000.0
        evidence = self._build_evidence(action, stdout, stderr, proc.returncode)

        return ExecutionResult(
            action_id=action.action_id,
            status="completed" if proc.returncode == 0 else "failed",
            stdout=stdout,
            stderr=stderr,
            exit_code=proc.returncode or 0,
            duration_ms=duration_ms,
            evidence=evidence,
            error_message=None if proc.returncode == 0 else (stderr or "Process exited with a non-zero code."),
        )

    def _permission_allowed(
        self,
        action: ExecutionAction,
        permission_check_callback: Callable[..., bool],
    ) -> bool:
        try:
            allowed = permission_check_callback(action)
        except TypeError:
            allowed = permission_check_callback()
        return bool(allowed)

    def _build_command(self, action: ExecutionAction) -> list[str]:
        target = action.execution_target
        args = list(action.arguments)

        if target == ExecutionTarget.PYTHON:
            return [sys.executable, *args]
        if target == ExecutionTarget.BASH:
            return [shutil.which("bash") or "/bin/bash", *args]
        if target == ExecutionTarget.WSL:
            return [shutil.which("wsl") or "wsl", *args]
        if target == ExecutionTarget.POWERSHELL:
            if os.name == "nt":
                return [shutil.which("powershell.exe") or "powershell.exe", *args]
            return [shutil.which("pwsh") or "pwsh", *args]
        if target == ExecutionTarget.CMD:
            if os.name == "nt":
                return [shutil.which("cmd.exe") or "cmd.exe", *args]
            return [shutil.which("bash") or "/bin/bash", *args]
        if target == ExecutionTarget.GIT:
            return [shutil.which("git") or "git", *args]
        if target == ExecutionTarget.FILESYSTEM:
            return [sys.executable, *args]
        if target == ExecutionTarget.PROCESS:
            return [sys.executable, *args]

        return [sys.executable, *args]

    def _build_environment(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in self.allowed_env_keys:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value

        if os.name == "nt":
            env.setdefault("PATH", os.environ.get("PATH", ""))
        else:
            env.setdefault("PATH", os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"))

        return env

    def _build_evidence(self, action: ExecutionAction, stdout: str, stderr: str, exit_code: Optional[int]) -> str:
        if action.execution_target == ExecutionTarget.FILESYSTEM:
            if action.arguments:
                target_path = action.arguments[0]
                exists = os.path.exists(target_path)
                return f"filesystem target={target_path}; exists={exists}; exit_code={exit_code}; stdout={stdout[:200]}; stderr={stderr[:200]}"
            return f"filesystem action; exit_code={exit_code}; stdout={stdout[:200]}; stderr={stderr[:200]}"
        if action.execution_target == ExecutionTarget.PROCESS:
            return f"process target; exit_code={exit_code}; stdout={stdout[:200]}; stderr={stderr[:200]}"
        return f"target={action.execution_target.value}; exit_code={exit_code}; stdout={stdout[:200]}; stderr={stderr[:200]}"

    async def _terminate_tree(self, proc: Any) -> None:
        if proc is None:
            return
        pid = getattr(proc, "pid", None)
        if pid is None:
            return
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            try:
                parent.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            _, alive = psutil.wait_procs([parent, *children], timeout=3)
            for p in alive:
                try:
                    p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        try:
            proc.kill()
        except Exception:
            pass
