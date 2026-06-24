# tests/layer1/test_e2e_sarif.py
"""端到端：用三件套 fixture 验证 Scanner 解析接线（桩掉真实工具调用 + 可用性）。"""
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.base import ScanContext
from agentsast.layer1.cppcheck import CppcheckScanner
from agentsast.layer1.csa import CsaScanner
from agentsast.layer1.infer import InferScanner

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_e2e_all_three_parse_fixtures(monkeypatch, tmp_path):
    cc = tmp_path / "cc.json"
    ctx = ScanContext(target=tmp_path, compile_db=cc)

    infer = InferScanner()
    monkeypatch.setattr(infer, "is_available", lambda: True)
    monkeypatch.setattr(infer, "_run_infer", lambda c: FIXTURES / "infer_null_deref.sarif")
    a_infer = infer.scan(ctx)
    assert a_infer and a_infer[0].source_location is not None

    csa = CsaScanner()
    monkeypatch.setattr(csa, "is_available", lambda: True)
    monkeypatch.setattr(csa, "_run_csa", lambda c: FIXTURES / "csa_null_deref.sarif")
    a_csa = csa.scan(ctx)
    assert a_csa and a_csa[0].source_location is not None

    cpp = CppcheckScanner()
    monkeypatch.setattr(cpp, "is_available", lambda: True)
    monkeypatch.setattr(cpp, "_run_cppcheck", lambda c: FIXTURES / "cppcheck_buffer.xml")
    a_cpp = cpp.scan(ctx)
    assert a_cpp and a_cpp[0].cwe == "CWE-120"
