import os

import pytest

from atrin_core.execution_bus import ExecutionBus
from atrin_core.execution_models import ExecutionAction, ExecutionTarget, PermissionLevel


@pytest.mark.asyncio
async def test_safe_execution():
    bus = ExecutionBus()
    if os.name == "nt":
        action = ExecutionAction(
            action_id="safe-powershell",
            permission_required=PermissionLevel.READ_ONLY,
            execution_target=ExecutionTarget.POWERSHELL,
            arguments=["-NoProfile", "-Command", "Write-Output \"hello\""],
            timeout_seconds=10,
            working_dir=None,
        )
    else:
        action = ExecutionAction(
            action_id="safe-python",
            permission_required=PermissionLevel.READ_ONLY,
            execution_target=ExecutionTarget.PYTHON,
            arguments=["-c", "print('hello')"],
            timeout_seconds=10,
            working_dir=None,
        )
    result = await bus.execute(action, lambda: True)
    assert result.status == "completed"
    assert "hello" in result.stdout.lower()


@pytest.mark.asyncio
async def test_timeout_enforcement():
    bus = ExecutionBus()
    action = ExecutionAction(
        action_id="timeout-python",
        permission_required=PermissionLevel.EXECUTE_SAFE,
        execution_target=ExecutionTarget.PYTHON,
        arguments=["-c", "import time; time.sleep(5)"],
        timeout_seconds=1,
        working_dir=None,
    )
    result = await bus.execute(action, lambda: True)
    assert result.status == "timed_out"
    assert result.exit_code == 124
    assert result.error_message == "Action exceeded its 1s timeout."


@pytest.mark.asyncio
async def test_permission_denial():
    bus = ExecutionBus()
    action = ExecutionAction(
        action_id="denied-python",
        permission_required=PermissionLevel.WRITE,
        execution_target=ExecutionTarget.PYTHON,
        arguments=["-c", "print('denied')"],
        timeout_seconds=10,
        working_dir=None,
    )
    result = await bus.execute(action, lambda: False)
    assert result.status == "permission_denied"
    assert "denied" in result.stderr.lower() or "denied" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_output_limit_enforcement():
    bus = ExecutionBus(default_max_output_bytes=1024)
    action = ExecutionAction(
        action_id="output-limit",
        permission_required=PermissionLevel.EXECUTE_SAFE,
        execution_target=ExecutionTarget.PYTHON,
        arguments=["-c", "print('x' * 5000)"],
        timeout_seconds=10,
        max_output_bytes=1024,
    )
    result = await bus.execute(action, lambda: True)
    assert result.status == "output_limit_exceeded"
    assert result.exit_code == 122


def test_working_directory_policy():
    bus = ExecutionBus(allowed_working_dirs=[os.getcwd()])
    action = ExecutionAction(
        action_id="cwd",
        permission_required=PermissionLevel.READ_ONLY,
        execution_target=ExecutionTarget.PYTHON,
        arguments=["-c", "print('ok')"],
        working_dir=os.getcwd(),
    )
    bus._validate_working_dir(action.working_dir)


def test_action_argument_bounds():
    bus = ExecutionBus(default_max_output_bytes=2048, max_argument_length=10)
    action = ExecutionAction(
        action_id="bounds",
        permission_required=PermissionLevel.READ_ONLY,
        execution_target=ExecutionTarget.PYTHON,
        arguments=["-c", "x" * 20],
        max_output_bytes=2048,
    )
    with pytest.raises(ValueError, match="maximum allowed length"):
        bus._validate_action(action)


# ── FIX (بند ۱۴/۲۵ — گزارش‌های قبلی): CPU/memory resource quotas ───────────

@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="RLIMIT quotas are POSIX-only")
async def test_cpu_quota_kills_busy_loop_process():
    """
    A CPU-bound infinite loop must be terminated by RLIMIT_CPU well before
    the (much longer) wall-clock timeout would otherwise fire.
    """
    bus = ExecutionBus(max_cpu_seconds=1)
    action = ExecutionAction(
        action_id="cpu-hog",
        permission_required=PermissionLevel.EXECUTE_SAFE,
        execution_target=ExecutionTarget.PYTHON,
        arguments=["-c", "x = 0\nwhile True:\n    x += 1"],
        timeout_seconds=30,
        working_dir=None,
    )
    result = await bus.execute(action, lambda: True)
    assert result.status != "completed"
    assert result.exit_code != 0


@pytest.mark.asyncio
@pytest.mark.skipif(os.name == "nt", reason="RLIMIT quotas are POSIX-only")
async def test_memory_quota_kills_unbounded_allocation():
    """A process trying to allocate far beyond the memory quota must be killed, not hang."""
    bus = ExecutionBus(max_memory_bytes=64 * 1024 * 1024)
    action = ExecutionAction(
        action_id="memory-hog",
        permission_required=PermissionLevel.EXECUTE_SAFE,
        execution_target=ExecutionTarget.PYTHON,
        arguments=["-c", "data = bytearray(500 * 1024 * 1024)"],
        timeout_seconds=15,
        working_dir=None,
    )
    result = await bus.execute(action, lambda: True)
    assert result.status != "completed"


@pytest.mark.asyncio
async def test_default_quotas_do_not_break_normal_execution():
    """The default (non-None) memory/process quotas must not interfere with an ordinary safe action."""
    bus = ExecutionBus()
    action = ExecutionAction(
        action_id="normal-run",
        permission_required=PermissionLevel.READ_ONLY,
        execution_target=ExecutionTarget.PYTHON,
        arguments=["-c", "print('ok')"],
        timeout_seconds=10,
        working_dir=None,
    )
    result = await bus.execute(action, lambda: True)
    assert result.status == "completed"
    assert "ok" in result.stdout.lower()


def test_execution_bus_accepts_custom_quota_overrides():
    bus = ExecutionBus(max_cpu_seconds=5, max_memory_bytes=128 * 1024 * 1024, max_child_processes=4)
    assert bus.max_cpu_seconds == 5
    assert bus.max_memory_bytes == 128 * 1024 * 1024
    assert bus.max_child_processes == 4


def test_execution_bus_quotas_can_be_disabled():
    """Passing None for all three quotas must disable preexec_fn entirely (no-op on Windows too)."""
    bus = ExecutionBus(max_cpu_seconds=None, max_memory_bytes=None, max_child_processes=None)
    assert bus._resource_limit_preexec() is None
