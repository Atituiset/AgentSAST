# tests/layer1/test_scanner_registry.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.base import ScanContext, Scanner, register_scanner, SCANNER_REGISTRY


def test_scan_context_carries_compile_db():
    ctx = ScanContext(target=Path("a.c"), compile_db=Path("cc.json"))
    assert ctx.compile_db == Path("cc.json")


def test_register_scanner_adds_to_registry():
    @register_scanner("dummy-tool")
    class DummyScanner:
        name = "Dummy"
        requires_compilation = False
        def is_available(self) -> bool:
            return True
        def scan(self, ctx: ScanContext):
            return []

    assert "dummy-tool" in SCANNER_REGISTRY
    assert SCANNER_REGISTRY["dummy-tool"] is DummyScanner
