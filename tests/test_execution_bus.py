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
