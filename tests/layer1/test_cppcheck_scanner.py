# tests/layer1/test_cppcheck_scanner.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.base import ScanContext
from agentsast.layer1.cppcheck import CppcheckScanner

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_requires_compilation():
    assert CppcheckScanner.requires_compilation is True


def test_scan_parses_xml(monkeypatch, tmp_path):
    scanner = CppcheckScanner()
    # 测试机未必装了 cppcheck，桩掉可用性与真实调用，直接用 fixture XML
    monkeypatch.setattr(scanner, "is_available", lambda: True)
    monkeypatch.setattr(scanner, "_run_cppcheck", lambda ctx: FIXTURES / "cppcheck_buffer.xml")
    ctx = ScanContext(target=tmp_path, compile_db=tmp_path / "cc.json")
    anchors = scanner.scan(ctx)
    assert len(anchors) == 1
    assert anchors[0].tool == "Cppcheck"
    assert anchors[0].cwe == "CWE-120"
