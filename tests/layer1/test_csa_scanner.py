# tests/layer1/test_csa_scanner.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.base import ScanContext
from agentsast.layer1.csa import CsaScanner

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_requires_compilation():
    assert CsaScanner.requires_compilation is True


def test_scan_parses_report(monkeypatch, tmp_path):
    scanner = CsaScanner()
    # 测试机未必装了 analyze-build，桩掉可用性与真实调用，直接用 fixture SARIF
    monkeypatch.setattr(scanner, "is_available", lambda: True)
    monkeypatch.setattr(scanner, "_run_csa", lambda ctx: FIXTURES / "csa_null_deref.sarif")
    ctx = ScanContext(target=tmp_path, compile_db=tmp_path / "cc.json")
    anchors = scanner.scan(ctx)
    assert len(anchors) == 1
    assert anchors[0].source_location is not None  # codeFlows 被还原
    assert anchors[0].source_location.line == 5
