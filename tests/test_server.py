from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from confer import server


async def test_mcp_server_registers_notify_tool():
    tools = await server.mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "notify" in tool_names


async def test_mcp_server_advertises_instructions_block():
    """Per Notify Self-Description Policy (4kxp7qnj): a fresh client should
    see when-to-use / when-not-to-use guidance in the server's
    instructions block."""
    instructions = server.mcp.instructions
    assert instructions is not None
    assert "USE the `notify` tool when" in instructions
    assert "DO NOT use `notify`" in instructions
    assert "out-of-band" in instructions.lower()


async def test_notify_tool_description_leads_with_purpose_not_mechanics():
    """The docstring on the tool should lead with WHY, then HOW."""
    tools = await server.mcp.list_tools()
    notify_tool = next(t for t in tools if t.name == "notify")
    desc = notify_tool.description or ""
    # First sentence should be about pinging the user, not about return type
    first_line = desc.strip().splitlines()[0]
    assert "out-of-band" in first_line.lower() or "ping" in first_line.lower()
    # Return-format info should still be present but later
    assert "sent at" in desc
    assert "NOTIFY_FAILED" in desc


async def test_notify_message_parameter_carries_guidance():
    """Per Notify Self-Description Policy: the message parameter must have
    a description telling the agent what shape the payload should take."""
    tools = await server.mcp.list_tools()
    notify_tool = next(t for t in tools if t.name == "notify")
    schema = notify_tool.inputSchema
    message_prop = schema["properties"]["message"]
    assert "description" in message_prop
    desc = message_prop["description"]
    # The phone-friendly URL-preferred-over-file-path note is the key
    # mobile-UX guidance; tests assert it stays.
    assert "URL" in desc
    assert "mobile" in desc.lower()


async def test_notify_tool_delegates_to_daemon_client():
    fake_client = MagicMock()
    fake_client.notify = AsyncMock(return_value="sent at 2026-01-01T00:00:00+00:00")

    with patch.object(server, "_client", fake_client):
        result = await server.notify("hi")

    assert result == "sent at 2026-01-01T00:00:00+00:00"
    fake_client.notify.assert_awaited_once_with("hi")


async def test_notify_tool_raises_when_client_uninitialized():
    with patch.object(server, "_client", None):
        with pytest.raises(RuntimeError, match="not initialized"):
            await server.notify("hi")


async def test_lifespan_initializes_and_closes_daemon_client():
    fake_client = MagicMock()
    fake_client.connect = AsyncMock()
    fake_client.close = AsyncMock()

    with patch.object(server, "DaemonClient", return_value=fake_client):
        async with server.lifespan(server.mcp):
            assert server._client is fake_client
            fake_client.connect.assert_awaited_once()

    fake_client.close.assert_awaited_once()
    assert server._client is None


def test_main_runs_server():
    with patch.object(server.mcp, "run") as mock_run:
        server.main()
    mock_run.assert_called_once()


# ───── ask tool ────────────────────────────────────────────────────────────


async def test_mcp_server_registers_ask_tool():
    tools = await server.mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "ask" in tool_names


async def test_ask_tool_docstring_leads_with_spokesperson_framing():
    tools = await server.mcp.list_tools()
    ask_tool = next(t for t in tools if t.name == "ask")
    desc = ask_tool.description or ""
    first_line = desc.strip().splitlines()[0].lower()
    # Should reference confer (the spokesperson) rather than the user/Discord
    assert "confer" in first_line
    assert "discord" not in first_line


async def test_ask_tool_question_parameter_has_description():
    tools = await server.mcp.list_tools()
    ask_tool = next(t for t in tools if t.name == "ask")
    schema = ask_tool.inputSchema
    assert "description" in schema["properties"]["question"]


async def test_ask_tool_give_up_after_seconds_is_bounded():
    """Per Minimal Agent Surface Operator Config (mk7npq4x): the
    give_up_after_seconds parameter is enforced by Pydantic with ge=1, le=86400."""
    tools = await server.mcp.list_tools()
    ask_tool = next(t for t in tools if t.name == "ask")
    schema = ask_tool.inputSchema
    prop = schema["properties"]["give_up_after_seconds"]
    assert prop.get("minimum") == 1
    assert prop.get("maximum") == 86400


async def test_ask_tool_on_timeout_is_two_modes_only():
    """The wait_forever / wait_max mode is gone; only use_best_judgment and abort."""
    tools = await server.mcp.list_tools()
    ask_tool = next(t for t in tools if t.name == "ask")
    schema = ask_tool.inputSchema
    prop = schema["properties"]["on_timeout"]
    enum = prop.get("enum")
    assert set(enum) == {"use_best_judgment", "abort"}


async def test_ask_tool_delegates_to_daemon_client():
    fake_client = MagicMock()
    fake_client.ask = AsyncMock(return_value="yes please")

    with patch.object(server, "_client", fake_client):
        result = await server.ask("rebase?", 60, "use_best_judgment")

    assert result == "yes please"
    fake_client.ask.assert_awaited_once_with("rebase?", 60, "use_best_judgment")


async def test_ask_tool_raises_when_client_uninitialized():
    with patch.object(server, "_client", None):
        with pytest.raises(RuntimeError, match="not initialized"):
            await server.ask("rebase?", 60, "use_best_judgment")


async def test_server_instructions_describe_both_tools_and_spokesperson():
    instructions = server.mcp.instructions
    assert "USE the `notify` tool when" in instructions
    assert "USE the `ask` tool when" in instructions
    assert "spokesperson" in instructions
    assert "on_timeout" in instructions


# ───── check_messages tool ─────────────────────────────────────────────────


async def test_mcp_server_registers_check_messages_tool():
    tools = await server.mcp.list_tools()
    assert any(t.name == "check_messages" for t in tools)


async def test_check_messages_tool_takes_no_parameters():
    tools = await server.mcp.list_tools()
    tool = next(t for t in tools if t.name == "check_messages")
    props = tool.inputSchema.get("properties", {})
    assert props == {}


async def test_check_messages_tool_docstring_describes_inbox_semantics():
    tools = await server.mcp.list_tools()
    tool = next(t for t in tools if t.name == "check_messages")
    desc = tool.description or ""
    assert "confer" in desc.lower()
    assert "exactly once" in desc.lower() or "clears" in desc.lower()


async def test_check_messages_tool_delegates_to_daemon_client():
    fake_client = MagicMock()
    fake_client.check_messages = AsyncMock(return_value="No new messages from the user.")

    with patch.object(server, "_client", fake_client):
        result = await server.check_messages()

    assert result == "No new messages from the user."
    fake_client.check_messages.assert_awaited_once_with()


async def test_check_messages_tool_raises_when_client_uninitialized():
    with patch.object(server, "_client", None):
        with pytest.raises(RuntimeError, match="not initialized"):
            await server.check_messages()


async def test_server_instructions_describe_check_messages_tool():
    instructions = server.mcp.instructions
    assert "check_messages" in instructions
    assert "[broadcast]" in instructions
    assert "[re <tag>]" in instructions
    assert "[late-reply]" in instructions


async def test_server_instructions_document_terse_reply_vocabulary():
    instructions = server.mcp.instructions
    assert "TERSE" in instructions
    assert '"stop"' in instructions
    assert '"bj"' in instructions or '"go"' in instructions


async def test_notify_guidance_clarifies_one_way_vs_ask():
    """G2 refinement: notify is one-way; a reply-needed blocker is an ask.
    The stale 'blocker that needs the user's input' notify bullet is gone."""
    instructions = server.mcp.instructions
    assert "one-way" in instructions
    assert "blocker that needs the user's input" not in instructions


async def test_on_timeout_abort_covers_no_safe_default():
    """G2 refinement: abort applies when there's no safe default, not only
    for destructive/irreversible actions."""
    instructions = server.mcp.instructions
    assert "no safe default" in instructions
