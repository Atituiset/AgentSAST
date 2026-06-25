# tests/layer2/test_treesitter_backend.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer2.treesitter_backend import TreeSitterBackend
from agentsast.layer1.models import Location

SAMPLES = Path(__file__).resolve().parent.parent.parent / "samples"
VULN = SAMPLES / "vulnerable_server.c"


def test_find_callers_of_process_buffer():
    backend = TreeSitterBackend()
    callers = backend.find_callers("process_buffer", Location(file=VULN, line=8))
    names = [c.name for c in callers]
    assert "handle_connection" in names


def test_find_callees_of_handle_connection():
    backend = TreeSitterBackend()
    # line 21 is the start of handle_connection() in vulnerable_server.c
    callees = backend.find_callees("handle_connection", Location(file=VULN, line=21))
    names = [c.name for c in callees]
    assert "process_buffer" in names


def test_function_ref_has_end_line():
    backend = TreeSitterBackend()
    callers = backend.find_callers("process_buffer", Location(file=VULN, line=8))
    hc = [c for c in callers if c.name == "handle_connection"][0]
    assert hc.location.line > 0
    assert hc.location.end_line >= hc.location.line
