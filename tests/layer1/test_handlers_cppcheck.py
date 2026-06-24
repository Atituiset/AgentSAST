# tests/layer1/test_handlers_cppcheck.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.handlers.cppcheck import cppcheck_xml_to_anchors

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_xml_to_anchors_basic():
    anchors = cppcheck_xml_to_anchors(FIXTURES / "cppcheck_buffer.xml")
    assert len(anchors) == 1
    a = anchors[0]
    assert a.tool == "Cppcheck"
    assert a.location.line == 8
    assert a.location.file.name == "main.c"
    assert a.rule_id == "bufferAccessOutOfBounds"
