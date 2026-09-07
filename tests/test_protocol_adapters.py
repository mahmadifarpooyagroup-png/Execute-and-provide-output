from unittest.mock import AsyncMock, Mock

import pytest

from atrin_core.acp_adapter import ACPAdapter
from atrin_core.a2a_adapter import A2AAdapter
from atrin_core.mcp_adapter import MCPAdapter
from atrin_core.protocol_models import ACPConfig, A2AConfig, MCPConfig


class FakeResponse:
    def __init__(self, *, json_data=None, text="", status_code=200):
        self._json_data = json_data if json_data is not None else {}
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


@pytest.mark.asyncio
async def test_mcp_adapter_stateless_rpc_lifecycle_and_tool_calls():
    mock_client = Mock()
    mock_client.post = AsyncMock(side_effect=[
        FakeResponse(json_data={"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "echo"}]}}),
        FakeResponse(json_data={"jsonrpc": "2.0", "id": 2, "result": {"status": "ok"}}),
    ])
    adapter = MCPAdapter(MCPConfig(server_url="https://example.test", capabilities=["tools"], auth_token="token-123"), client=mock_client)
    connected = await adapter.connect()
    assert connected.state == "CONNECTED"
    assert adapter.protocol_state.health == "HEALTHY"
    tools = await adapter.list_tools()
    assert tools["tools"][0]["name"] == "echo"
    result = await adapter.call_tool("echo", {"message": "hello"}, idempotency_key="key-1")
    assert result["status"] == "ok"
    assert await adapter.verify_action("key-1") == "CONFIRMED"
    await adapter.disconnect()
    assert adapter.protocol_state.state == "DISCONNECTED"
    assert adapter.protocol_state.health == "OFFLINE"
    assert mock_client.post.await_count == 2


@pytest.mark.asyncio
async def test_acp_adapter_session_workflow_and_identity_bound_verification():
    mock_client = Mock()
    mock_client.post = AsyncMock(side_effect=[
        FakeResponse(json_data={"session_id": "session-42"}),
        FakeResponse(json_data={"reply": "message processed"}),
    ])
    mock_client.get = AsyncMock(return_value=FakeResponse(json_data={"session_id": "session-42", "status": "resumed"}))
    mock_client.delete = AsyncMock(return_value=FakeResponse(json_data={"ok": True}))
    adapter = ACPAdapter(ACPConfig(agent_path="https://agent.example.test", resume_supported=True), client=mock_client)
    session = await adapter.start_session()
    assert session["session_id"] == "session-42"
    send_result = await adapter.send_message("hello", idempotency_key="key-1")
    assert send_result["reply"] == "message processed"
    assert await adapter.verify_action("key-1") == "CONFIRMED"
    assert await adapter.verify_action("wrong-key") == "AMBIGUOUS"
    resumed = await adapter.resume_session("session-42")
    assert resumed["session_id"] == "session-42"
    await adapter.close_session()
    assert adapter.session_id is None
    assert adapter.config.session_id is None
    assert adapter.protocol_state.state == "CLOSED"


@pytest.mark.asyncio
async def test_a2a_adapter_jsonrpc_task_lifecycle():
    mock_client = Mock()
    mock_client.get = AsyncMock(return_value=FakeResponse(json_data={"name": "Agent A", "url": "https://agent.example.test"}))
    mock_client.post = AsyncMock(side_effect=[
        FakeResponse(json_data={"jsonrpc": "2.0", "id": 1, "result": {"id": "task-123", "status": "working"}}),
        FakeResponse(json_data={"jsonrpc": "2.0", "id": 2, "result": {"id": "task-123", "status": "completed"}}),
    ])
    adapter = A2AAdapter(
        A2AConfig(agent_card_url="https://agent.example.test/.well-known/agent-card.json", capabilities=["tasks"], auth_method="token"),
        client=mock_client,
    )
    card = await adapter.discover_agent()
    assert card["name"] == "Agent A"
    task = await adapter.send_task(
        {"message": {"role": "user", "parts": [{"kind": "text", "text": "Use tool"}]}},
        idempotency_key="key-1",
    )
    assert task["id"] == "task-123"
    status = await adapter.poll_task_status("task-123")
    assert status["status"] == "completed"
    assert await adapter.verify_action("key-1") == "CONFIRMED"


@pytest.mark.asyncio
async def test_protocol_state_is_independent_from_workflow_state_and_checkpoints():
    mcp = MCPAdapter(MCPConfig(server_url="https://example.test", capabilities=["tools"]), client=Mock(post=AsyncMock()))
    acp = ACPAdapter(ACPConfig(agent_path="https://agent.example.test"), client=Mock(post=AsyncMock(), get=AsyncMock(), delete=AsyncMock()))
    a2a = A2AAdapter(A2AConfig(agent_card_url="https://agent.example.test/agent-card.json"), client=Mock(get=AsyncMock(), post=AsyncMock()))
    workflow_checkpoint = {"state": "RUNNING", "step_id": "step-1", "last_result": "ok"}
    mcp.workflow_state = acp.workflow_state = a2a.workflow_state = "RUNNING"
    mcp.protocol_state.state = "CONNECTED"
    acp.protocol_state.state = "ACTIVE"
    a2a.protocol_state.state = "DISCOVERED"
    workflow_checkpoint["state"] = "PAUSED"
    assert mcp.workflow_state == acp.workflow_state == a2a.workflow_state == "RUNNING"
    assert workflow_checkpoint["state"] == "PAUSED"
