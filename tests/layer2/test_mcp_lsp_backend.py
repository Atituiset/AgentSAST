# tests/layer2/test_mcp_lsp_backend.py
"""McpLspBackend 测试：mock _call_tool_async，不依赖真实 mcp/clangd。"""
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.models import Location


def test_is_available_reflects_mcp_import(monkeypatch):
    from agentsast.layer2 import mcp_lsp_backend as mod
    from agentsast.layer2.mcp_lsp_backend import McpLspBackend
    monkeypatch.setattr(mod, "IS_AVAILABLE", False)
    b = McpLspBackend()
    assert b.is_available() is False


def test_find_callers_parses_mocked_tool_result(monkeypatch):
    from agentsast.layer2.mcp_lsp_backend import McpLspBackend
    b = McpLspBackend()
    # mock async 调用：返回 callers tool 的文本（每行一个引用 "file:line"）
    async def fake_call(tool, args):
        return "handle_connection\n  /src/main.c:18:1\n  /src/other.c:5:1"
    monkeypatch.setattr(b, "_call_tool_async", fake_call)
    refs = b.find_callers("process_buffer", Location(file=Path("/src/main.c"), line=8))
    names = [r.name for r in refs]
    assert "handle_connection" in names
    assert all(r.location.line > 0 for r in refs)


def test_find_callers_empty_when_no_result(monkeypatch):
    from agentsast.layer2.mcp_lsp_backend import McpLspBackend
    b = McpLspBackend()
    async def fake_call(tool, args):
        return ""
    monkeypatch.setattr(b, "_call_tool_async", fake_call)
    assert b.find_callers("x", Location(file=Path("a.c"), line=1)) == []
