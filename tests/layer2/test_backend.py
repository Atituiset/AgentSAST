# tests/layer2/test_backend.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer2.backend import FunctionRef, ProgramUnderstandingBackend
from agentsast.layer1.models import Location


def test_function_ref_holds_name_and_location():
    ref = FunctionRef(name="handle_connection", location=Location(file=Path("a.c"), line=18, end_line=25))
    assert ref.name == "handle_connection"
    assert ref.location.line == 18
    assert ref.location.end_line == 25


def test_protocol_methods_exist_as_attrs():
    for meth in ("find_callers", "find_callees"):
        assert hasattr(ProgramUnderstandingBackend, meth)
