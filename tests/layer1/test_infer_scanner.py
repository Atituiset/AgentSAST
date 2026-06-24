# tests/layer1/test_infer_scanner.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.base import ScanContext
from agentsast.layer1.infer import InferScanner

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_requires_compilation():
    assert InferScanner.requires_compilation is True


def test_scan_no_compile_db_returns_empty(tmp_path):
    scanner = InferScanner()
    ctx = ScanContext(target=tmp_path, compile_db=None)
    assert scanner.scan(ctx) == []


def test_scan_parses_report(monkeypatch, tmp_path):
    scanner = InferScanner()
    # 测试机未必装了 infer，桩掉可用性与真实调用，直接用 fixture SARIF
    monkeypatch.setattr(scanner, "is_available", lambda: True)
    monkeypatch.setattr(scanner, "_run_infer", lambda ctx: FIXTURES / "infer_null_deref.sarif")
    ctx = ScanContext(target=tmp_path, compile_db=tmp_path / "cc.json")
    anchors = scanner.scan(ctx)
    assert len(anchors) == 1
    assert anchors[0].source_location is not None
    assert anchors[0].source_location.line == 5  # Infer handler 从 message 还原 source 行
