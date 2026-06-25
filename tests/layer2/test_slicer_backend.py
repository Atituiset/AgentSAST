# tests/layer2/test_slicer_backend.py
"""验证 SlicingEngine 接受 backend 参数,且默认行为与原来一致。"""
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.models import Anchor, Location, Severity
from agentsast.layer2.slicer import SlicingEngine
from agentsast.layer2.treesitter_backend import TreeSitterBackend

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"
VULN = SAMPLES / "vulnerable_server.c"


def _memcpy_anchor(line=17):
    return Anchor(
        rule_id="t", tool="t", severity=Severity.WARNING, message="m",
        location=Location(file=VULN, line=line), cwe="CWE-120", sink_function="memcpy",
    )


def test_slicing_engine_accepts_backend():
    backend = TreeSitterBackend()
    engine = SlicingEngine(backend=backend)
    assert engine.backend is backend


def test_slicing_engine_defaults_to_treesitter():
    engine = SlicingEngine()
    assert isinstance(engine.backend, TreeSitterBackend)


def test_caller_slice_via_backend():
    engine = SlicingEngine()
    result = engine.slice_anchor(_memcpy_anchor())
    # process_buffer 被 handle_connection 调用 → caller slice 应含 handle_connection
    labels = " ".join(s.label for s in result.caller_slices)
    assert "handle_connection" in labels or "caller_of:process_buffer" in labels
