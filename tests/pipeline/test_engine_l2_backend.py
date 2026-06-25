# tests/pipeline/test_engine_l2_backend.py
"""Pipeline 按 l2_backend 构造正确后端。仅验证构造分支，不跑真实扫描/切片。"""
from __future__ import annotations

import types

from agentsast.pipeline.engine import Pipeline


def test_pipeline_accepts_mcp_lsp_agent_choice():
    # Pipeline 接受 mcp-lsp-agent 字符串（Choice 校验在 CLI 层）
    p = Pipeline(l2_backend="mcp-lsp-agent", skip_llm=True)
    assert p.l2_backend == "mcp-lsp-agent"


def test_engine_builds_agent_backend_for_mcp_lsp_agent(monkeypatch, tmp_path):
    import agentsast.pipeline.engine as eng
    from agentsast.layer2.models import SlicingResult

    # mock Layer1 扫描返回 1 个 fake anchor，驱动 Layer2 backend 构造分支
    fake_anchor = types.SimpleNamespace(file=tmp_path / "a.c", line=1)
    monkeypatch.setattr(eng, "layer1_scan", lambda *a, **k: [fake_anchor])

    constructed: list[str] = []

    class SpyEngine:
        def __init__(self, max_call_depth, backend):
            constructed.append(type(backend).__name__)

        def slice_anchor(self, anchor, project_root=None):
            return SlicingResult(
                struct_defs=[], dataflow_slices=[], caller_slices=[]
            )

    monkeypatch.setattr(eng, "SlicingEngine", SpyEngine)

    p = Pipeline(l2_backend="mcp-lsp-agent", skip_llm=True)
    p.run(tmp_path, project_root=tmp_path)
    assert constructed == ["AgentBackend"]
