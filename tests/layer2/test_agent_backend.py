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


def _tc(name, args, tcid="t1"):
    """构造一个 openai tool_call 形态的对象（兼容 SimpleNamespace fake）。"""
    return types.SimpleNamespace(
        id=tcid,
        function=types.SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _resp(content=None, tool_calls=None):
    """构造一个 openai chat completion response 形态的对象。"""
    msg = types.SimpleNamespace(content=content, tool_calls=tool_calls)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


def _backend_with_fake_llm(monkeypatch, responses, key="sk-test"):
    """构造 AgentBackend，其 LLM create() 依次返回 responses（list）。"""
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", True)  # 默认 mcp 可用，走到 loop
    b = AgentBackend(llm_api_key=key)
    it = iter(responses)
    b._client.chat.completions.create = MagicMock(side_effect=lambda **kw: next(it))
    return b


def test_loop_success_calls_tool_then_parses_json(monkeypatch):
    # 第 1 轮：LLM 调 callers 工具；第 2 轮：LLM 给最终 JSON
    responses = [
        _resp(tool_calls=[_tc("callers", {"symbolName": "process_buffer",
                                          "filePath": "/src/main.c", "line": 8, "column": 1})]),
        _resp(content='[{"name": "caller_a", "file": "/src/main.c", "line": 18}]'),
    ]
    b = _backend_with_fake_llm(monkeypatch, responses)
    monkeypatch.setattr(
        b._conn, "call_tool", lambda tool, args: "caller_a\n  /src/main.c:18:1"
    )
    refs = b.find_callers("process_buffer", _loc())
    assert [r.name for r in refs] == ["caller_a"]
    assert refs[0].location.line == 18


def test_read_source_tool_reads_file_range(tmp_path, monkeypatch):
    f = tmp_path / "main.c"
    f.write_text("line1\nline2\nline3\nline4\n")
    responses = [
        _resp(tool_calls=[_tc("read_source", {"filePath": str(f), "startLine": 2, "endLine": 3})]),
        _resp(content="[]"),
    ]
    b = _backend_with_fake_llm(monkeypatch, responses)
    captured: list[str] = []
    real_dispatch = b._dispatch
    monkeypatch.setattr(b, "_dispatch", lambda name, args, *a, **k: (
        captured.append(real_dispatch(name, args, *a, **k)) or captured[-1]))
    b.find_callers("process_buffer", _loc())
    assert any("2: line2" in c and "3: line3" in c for c in captured)


def test_tool_exception_self_corrects(monkeypatch):
    # 第 1 轮 callers 工具抛异常 → 回填错误；第 2 轮 LLM 给最终 JSON
    responses = [
        _resp(tool_calls=[_tc("callers", {"symbolName": "x", "filePath": "/a.c",
                                          "line": 1, "column": 1})]),
        _resp(content="[]"),
    ]
    b = _backend_with_fake_llm(monkeypatch, responses)

    def boom(tool, args):
        raise RuntimeError("mcp timeout")

    monkeypatch.setattr(b._conn, "call_tool", boom)
    # 不应抛出，agent 收到错误后正常返回 []
    assert b.find_callers("x", _loc()) == []


def test_fallback_on_llm_error(monkeypatch):
    # LLM create 抛异常 → fallback 到程序化 direct
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", True)
    b = AgentBackend(llm_api_key="sk-test")
    b._client.chat.completions.create = MagicMock(side_effect=RuntimeError("503"))
    monkeypatch.setattr(
        b._direct._conn,
        "call_tool",
        lambda tool, args: "caller_a\n  /src/main.c:18:1",
    )
    refs = b.find_callers("process_buffer", _loc())
    assert [r.name for r in refs] == ["caller_a"]  # 来自 fallback direct


def test_fallback_on_max_iters(monkeypatch):
    # LLM 每轮都只调工具、永不收敛 → 触顶 max_iters → fallback
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", True)
    b = AgentBackend(llm_api_key="sk-test", max_iters=2)
    loop_resp = _resp(
        tool_calls=[
            _tc("callers", {"symbolName": "x", "filePath": "/a.c",
                             "line": 1, "column": 1})
        ]
    )
    b._client.chat.completions.create = MagicMock(return_value=loop_resp)
    monkeypatch.setattr(
        b._direct._conn,
        "call_tool",
        lambda tool, args: "caller_b\n  /a.c:5:1",
    )
    refs = b.find_callers("x", _loc())
    assert [r.name for r in refs] == ["caller_b"]


def test_fallback_on_parse_failure(monkeypatch):
    # LLM 最终返回非 JSON → fallback
    from agentsast.layer2 import _mcp_client as mcpmod
    from agentsast.layer2.agent_backend import AgentBackend

    monkeypatch.setattr(mcpmod, "IS_AVAILABLE", True)
    b = AgentBackend(llm_api_key="sk-test")
    b._client.chat.completions.create = MagicMock(return_value=_resp(content="不是 JSON"))
    monkeypatch.setattr(
        b._direct._conn,
        "call_tool",
        lambda tool, args: "caller_c\n  /a.c:9:1",
    )
    refs = b.find_callers("x", _loc())
    assert [r.name for r in refs] == ["caller_c"]
