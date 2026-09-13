import asyncio
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

import psutil

from .execution_models import ExecutionAction, ExecutionResult, ExecutionTarget


class OutputLimitExceeded(RuntimeError):
    """Raised when a child process produces more output than policy permits."""


class ExecutionBus:
    """Vendor-neutral process execution bus with explicit policy boundaries."""

    def __init__(
        self,
        *,
        allowed_env_keys: Optional[list[str]] = None,
        allowed_working_dirs: Optional[list[str]] = None,
        default_max_output_bytes: int = 1_048_576,
        max_argument_length: int = 16_384,
        # FIX (بند ۱۴/۲۵ — گزارش‌های قبلی): ExecutionBus had timeout + output
        # limits but no CPU/memory/process-count quota, unlike the plugin
        # worker sandbox hardened earlier. A single misbehaving action could
        # still consume unbounded CPU or memory for its full timeout window,
        # or spawn many descendant processes. These rlimits are applied
        # inside the child right before exec via preexec_fn.
        max_cpu_seconds: Optional[int] = None,
        max_memory_bytes: Optional[int] = 512 * 1024 * 1024,
        max_child_processes: Optional[int] = 16,
    ):
        self.allowed_env_keys = allowed_env_keys or [
            "PATH", "HOME", "USERPROFILE", "TEMP", "TMP", "SYSTEMROOT",
            "COMSPEC", "PATHEXT", "TERM",
        ]
        self.allowed_working_dirs = [Path(value).expanduser().resolve() for value in (allowed_working_dirs or [])]
        self.default_max_output_bytes = default_max_output_bytes
        self.max_argument_length = max_argument_length
        self.max_cpu_seconds = max_cpu_seconds
        self.max_memory_bytes = max_memory_bytes
        self.max_child_processes = max_child_processes

    def _resource_limit_preexec(self) -> Optional[Callable[[], None]]:
        """
        Build a preexec_fn that applies RLIMIT_CPU / RLIMIT_AS / RLIMIT_NPROC
        to the child process before its program image is loaded. Returns
        None on non-POSIX platforms (Windows) or when no quotas are set,
        since asyncio.create_subprocess_exec's preexec_fn is POSIX-only.
        """
        if sys.platform == "win32":
            return None
        if self.max_cpu_seconds is None and self.max_memory_bytes is None and self.max_child_processes is None:
            return None
        cpu_seconds = self.max_cpu_seconds
        memory_bytes = self.max_memory_bytes
        max_processes = self.max_child_processes

        def _apply() -> None:
            try:
                import resource

                if cpu_seconds is not None:
                    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
                if memory_bytes is not None:
                    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
                if max_processes is not None:
                    resource.setrlimit(resource.RLIMIT_NPROC, (max_processes, max_processes))
                # Start a new session so the whole subtree shares one
                # process group, matching _terminate_tree's kill scope.
                os.setsid()
            except (ImportError, ValueError, OSError):
                pass

        return _apply

    async def execute(
        self,
        action: ExecutionAction,
        permission_check_callback: Callable[..., bool],
    ) -> ExecutionResult:
        start = time.perf_counter()

        if not self._permission_allowed(action, permission_check_callback):
            return self._result(action, "permission_denied", 1, start,
                                stderr="Permission denied by policy.",
                                evidence=f"Permission denied for action {action.action_id} requiring {action.permission_required.name}")

        try:
            self._validate_action(action)
            self._validate_working_dir(action.working_dir)
            command = self._build_command(action)
            env = self._build_environment()
        except (OSError, ValueError, PermissionError) as exc:
            return self._result(action, "permission_denied", 126, start,
                                stderr=str(exc), evidence="Execution admission rejected by policy.",
                                error_message=str(exc))

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=action.working_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=self._resource_limit_preexec(),
            )
        except (FileNotFoundError, OSError) as exc:
            return self._result(action, "failed", 127, start, stderr=str(exc),
                                evidence=f"Executable not found for {action.execution_target.value}", error_message=str(exc))

        stdout_task = asyncio.create_task(self._read_stream(proc.stdout, action.max_output_bytes))
        stderr_task = asyncio.create_task(self._read_stream(proc.stderr, action.max_output_bytes))
        try:
            await asyncio.wait_for(proc.wait(), timeout=action.timeout_seconds)
            try:
                stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
            except OutputLimitExceeded as exc:
                await self._terminate_tree(proc)
                return self._result(action, "output_limit_exceeded", 122, start,
                                    evidence=str(exc), error_message=str(exc))
        except asyncio.TimeoutError:
            await self._terminate_tree(proc)
            for task in (stdout_task, stderr_task):
                task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            message = f"Action exceeded its {action.timeout_seconds}s timeout."
            return self._result(action, "timed_out", 124, start, evidence=message, error_message=message)
        except Exception:
            await self._terminate_tree(proc)
            for task in (stdout_task, stderr_task):
                task.cancel()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise

        exit_code = int(proc.returncode or 0)
        evidence = self._build_evidence(action, stdout, stderr, exit_code)
        return self._result(
            action,
            "completed" if exit_code == 0 else "failed",
            exit_code,
            start,
            stdout=stdout,
            stderr=stderr,
            evidence=evidence,
            error_message=None if exit_code == 0 else (stderr or "Process exited with a non-zero code."),
        )

    @staticmethod
    async def _read_stream(stream: Any, limit: int) -> str:
        if stream is None:
            return ""
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await stream.read(min(65_536, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise OutputLimitExceeded(f"Process output exceeded the {limit}-byte safety limit")
        return b"".join(chunks).decode("utf-8", errors="replace")

    @staticmethod
    def _result(action: ExecutionAction, status: str, exit_code: int, start: float,
                *, stdout: str = "", stderr: str = "", evidence: str = "",
                error_message: Optional[str] = None) -> ExecutionResult:
        return ExecutionResult(
            action_id=action.action_id,
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=(time.perf_counter() - start) * 1000.0,
            evidence=evidence,
            error_message=error_message,
        )

    @staticmethod
    def _permission_allowed(action: ExecutionAction, permission_check_callback: Callable[..., bool]) -> bool:
        try:
            allowed = permission_check_callback(action)
        except TypeError:
            allowed = permission_check_callback()
        return bool(allowed)

    def _validate_action(self, action: ExecutionAction) -> None:
        if action.max_output_bytes > self.default_max_output_bytes:
            raise ValueError(f"max_output_bytes exceeds runtime policy ({self.default_max_output_bytes})")
        if any(len(argument) > self.max_argument_length for argument in action.arguments):
            raise ValueError("Execution argument exceeds the maximum allowed length")
        if action.execution_target in {ExecutionTarget.FILESYSTEM, ExecutionTarget.PROCESS} and not action.arguments:
            raise ValueError(f"{action.execution_target.value} target requires explicit arguments")

    def _validate_working_dir(self, working_dir: Optional[str]) -> None:
        if not working_dir:
            return
        path = Path(working_dir).expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"Working directory does not exist: {working_dir}")
        if self.allowed_working_dirs and not any(path == root or root in path.parents for root in self.allowed_working_dirs):
            raise PermissionError("Working directory is outside the execution policy roots")

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
            return [shutil.which("powershell.exe") or "powershell.exe", *args] if os.name == "nt" else [shutil.which("pwsh") or "pwsh", *args]
        if target == ExecutionTarget.CMD:
            return [shutil.which("cmd.exe") or "cmd.exe", *args] if os.name == "nt" else [shutil.which("bash") or "/bin/bash", *args]
        if target == ExecutionTarget.GIT:
            return [shutil.which("git") or "git", *args]
        if target == ExecutionTarget.FILESYSTEM:
            return [sys.executable, *args]
        if target == ExecutionTarget.PROCESS:
            return [sys.executable, *args]
        raise ValueError(f"Unsupported execution target: {target}")

    def _build_environment(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key in self.allowed_env_keys:
            value = os.environ.get(key)
            if value is not None:
                env[key] = value
        env["PATH"] = os.environ.get("PATH", "")
        return env

    @staticmethod
    def _build_evidence(action: ExecutionAction, stdout: str, stderr: str, exit_code: Optional[int]) -> str:
        if action.execution_target == ExecutionTarget.FILESYSTEM:
            target_path = action.arguments[0]
            exists = os.path.exists(target_path)
            return f"filesystem target={target_path}; exists={exists}; exit_code={exit_code}; stdout={stdout[:200]}; stderr={stderr[:200]}"
        if action.execution_target == ExecutionTarget.PROCESS:
            return f"process target; exit_code={exit_code}; stdout={stdout[:200]}; stderr={stderr[:200]}"
        return f"target={action.execution_target.value}; exit_code={exit_code}; stdout={stdout[:200]}; stderr={stderr[:200]}"

    async def _terminate_tree(self, proc: Any) -> None:
        pid = getattr(proc, "pid", None) if proc is not None else None
        if pid is not None:
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
                for process in alive:
                    try:
                        process.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass
