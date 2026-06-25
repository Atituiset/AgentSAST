# tests/layer2/test_agent_backend.py
"""AgentBackend 测试：mock LLM client 与 McpLspConnection，不依赖真实 LLM/clangd。"""
from __future__ import annotations

import json
import types
from pathlib import Path
from unittest.mock import MagicMock

from agentsast.layer1.models import Location


def _loc():
    return Location(file=Path("/src/main.c"), line=8, col=1)


def test_unavailable_returns_empty(monkeypatch):
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", False)
    b = AgentBackend(llm_api_key="sk-test")
    assert b.is_available() is False
    assert b.find_callers("process_buffer", _loc()) == []


def test_skip_llm_uses_programmatic_direct(monkeypatch):
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", True)
    b = AgentBackend(skip_llm=True)
    # 无 key/skip_llm 时不应构造 LLM client
    assert b._skip_llm is True
    assert b._client is None
    # 直接走程序化 direct
    monkeypatch.setattr(
        b._direct._conn,
        "call_tool",
        lambda tool, args: "caller_a\n  /src/main.c:18:1",
    )
    refs = b.find_callers("process_buffer", _loc())
    assert [r.name for r in refs] == ["caller_a"]


def test_no_api_key_implies_skip_llm(monkeypatch):
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    b = AgentBackend()  # 无 key、无 env
    assert b._skip_llm is True
    assert b._client is None
