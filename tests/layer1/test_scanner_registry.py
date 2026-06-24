# tests/layer1/test_scanner_registry.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.base import SCANNER_REGISTRY, ScanContext, register_scanner


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


def test_semgrep_is_registered_and_protocol_compatible():
    from agentsast.layer1.base import SCANNER_REGISTRY
    assert "semgrep" in SCANNER_REGISTRY
    scanner = SCANNER_REGISTRY["semgrep"](config="p/c")
    assert scanner.name == "Semgrep"
    assert scanner.requires_compilation is False
    assert callable(scanner.is_available)
    assert callable(scanner.scan)


def test_flawfinder_is_registered_and_protocol_compatible():
    from agentsast.layer1.base import SCANNER_REGISTRY
    assert "flawfinder" in SCANNER_REGISTRY
    scanner = SCANNER_REGISTRY["flawfinder"]()
    assert scanner.name == "Flawfinder"
    assert scanner.requires_compilation is False


def test_scan_skips_compilation_scanner_without_compile_db(monkeypatch, tmp_path):
    from agentsast.layer1 import scanner as scanner_mod
    from agentsast.layer1.base import SCANNER_REGISTRY, register_scanner

    called = {"n": 0}

    @register_scanner("fake-compiler")
    class _FakeCompiler:
        name = "Fake"
        requires_compilation = True
        def is_available(self):
            return True
        def scan(self, ctx):
            called["n"] += 1
            return []

    anchors = scanner_mod.scan(tmp_path, tools=["fake-compiler"])
    assert anchors == []
    assert called["n"] == 0  # 无 compile_db，编译期扫描器被跳过
    SCANNER_REGISTRY.pop("fake-compiler", None)
