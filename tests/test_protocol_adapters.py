from unittest.mock import AsyncMock, Mock

import pytest

from atrin_core.acp_adapter import ACPAdapter
from atrin_core.a2a_adapter import A2AAdapter
from atrin_core.mcp_adapter import MCPAdapter
from atrin_core.protocol_models import ACPConfig, A2AConfig, MCPConfig


class FakeResponse:
    def __init__(self, *, json_data=None, text="", status_code=200):
        self._json_data = json_data or {}
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


@pytest.mark.asyncio
async def test_mcp_adapter_lifecycle_and_tool_calls():
    mock_client = Mock()
    mock_client.post = AsyncMock(
        side_effect=[
            FakeResponse(json_data={"ok": True}),
            FakeResponse(json_data={"result": {"status": "ok"}}),
            FakeResponse(json_data={"ok": True}),
        ]
    )
    mock_client.get = AsyncMock(return_value=FakeResponse(json_data={"tools": [{"name": "echo"}]}))

    adapter = MCPAdapter(
        MCPConfig(
            server_url="https://example.test",
            capabilities=["tools"],
            auth_token="token-123",
        ),
        client=mock_client,
    )

    connected = await adapter.connect()
    assert connected.state == "CONNECTED"
    assert adapter.protocol_state.health == "HEALTHY"

    tools = await adapter.list_tools()
    assert tools["tools"][0]["name"] == "echo"

    result = await adapter.call_tool("echo", {"message": "hello"})
    assert result["result"]["status"] == "ok"

    await adapter.disconnect()
    assert adapter.protocol_state.state == "DISCONNECTED"
    assert adapter.protocol_state.health == "OFFLINE"

    assert mock_client.post.await_count == 3
    assert mock_client.get.await_count == 1


@pytest.mark.asyncio
async def test_acp_adapter_session_workflow():
    mock_client = Mock()
    mock_client.post = AsyncMock(
        side_effect=[
            FakeResponse(json_data={"session_id": "session-42"}),
            FakeResponse(json_data={"reply": "message processed"}),
            FakeResponse(json_data={"ok": True}),
        ]
    )
    mock_client.get = AsyncMock(return_value=FakeResponse(json_data={"session_id": "session-42", "status": "resumed"}))
    mock_client.delete = AsyncMock(return_value=FakeResponse(json_data={"ok": True}))

    adapter = ACPAdapter(
        ACPConfig(agent_path="https://agent.example.test", resume_supported=True),
        client=mock_client,
    )

    session = await adapter.start_session()
    assert session["session_id"] == "session-42"
    assert adapter.session_id == "session-42"
    assert adapter.protocol_state.state == "ACTIVE"

    send_result = await adapter.send_message("hello")
    assert send_result["reply"] == "message processed"
    assert adapter.protocol_state.state == "RESPONDING"

    resumed = await adapter.resume_session("session-42")
    assert resumed["session_id"] == "session-42"
    assert adapter.protocol_state.state == "RESUMED"

    await adapter.close_session()
    assert adapter.session_id is None
    assert adapter.config.session_id is None
    assert adapter.protocol_state.state == "CLOSED"
    assert adapter.protocol_state.health == "OFFLINE"


@pytest.mark.asyncio
async def test_a2a_adapter_agent_discovery_and_task_lifecycle():
    mock_client = Mock()
    mock_client.get = AsyncMock(
        side_effect=[
            FakeResponse(json_data={"name": "Agent A", "url": "https://agent.example.test"}),
            FakeResponse(json_data={"status": "running", "task_id": "task-123"}),
        ]
    )
    mock_client.post = AsyncMock(return_value=FakeResponse(json_data={"task_id": "task-123", "status": "accepted"}))

    adapter = A2AAdapter(
        A2AConfig(
            agent_card_url="https://agent.example.test/.well-known/agent-card.json",
            capabilities=["tasks"],
            auth_method="token",
        ),
        client=mock_client,
    )

    card = await adapter.discover_agent()
    assert card["name"] == "Agent A"
    assert adapter.protocol_state.state == "DISCOVERED"

    task = await adapter.send_task({"message": "Use tool"})
    assert task["task_id"] == "task-123"
    assert adapter.protocol_state.state == "TASK_SENT"

    status = await adapter.poll_task_status("task-123")
    assert status["status"] == "running"
    assert adapter.protocol_state.state == "TASK_PENDING"


@pytest.mark.asyncio
async def test_protocol_state_is_independent_from_workflow_state_and_checkpoints():
    mcp = MCPAdapter(
        MCPConfig(server_url="https://example.test", capabilities=["tools"]),
        client=Mock(post=AsyncMock(), get=AsyncMock()),
    )
    acp = ACPAdapter(ACPConfig(agent_path="https://agent.example.test"), client=Mock(post=AsyncMock(), get=AsyncMock(), delete=AsyncMock()))
    a2a = A2AAdapter(A2AConfig(agent_card_url="https://agent.example.test/agent-card.json"), client=Mock(get=AsyncMock(), post=AsyncMock()))

    workflow_checkpoint = {"state": "RUNNING", "step_id": "step-1", "last_result": "ok"}

    mcp.workflow_state = "RUNNING"
    mcp.protocol_state.state = "CONNECTED"
    acp.workflow_state = "RUNNING"
    acp.protocol_state.state = "ACTIVE"
    a2a.workflow_state = "RUNNING"
    a2a.protocol_state.state = "DISCOVERED"

    assert mcp.workflow_state == "RUNNING"
    assert acp.workflow_state == "RUNNING"
    assert a2a.workflow_state == "RUNNING"

    assert mcp.protocol_state.state == "CONNECTED"
    assert acp.protocol_state.state == "ACTIVE"
    assert a2a.protocol_state.state == "DISCOVERED"

    workflow_checkpoint["state"] = "PAUSED"
    assert mcp.workflow_state == "RUNNING"
    assert acp.workflow_state == "RUNNING"
    assert a2a.workflow_state == "RUNNING"
    assert workflow_checkpoint["state"] == "PAUSED"
    assert workflow_checkpoint["step_id"] == "step-1"

    assert mcp.protocol_state.state != mcp.workflow_state
    assert acp.protocol_state.state != acp.workflow_state
    assert a2a.protocol_state.state != a2a.workflow_state
