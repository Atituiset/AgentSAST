# tests/layer1/test_sarif_parser.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.sarif_parser import parse_sarif_to_anchors

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_parses_result_to_anchor():
    anchors = parse_sarif_to_anchors(FIXTURES / "csa_null_deref.sarif")
    assert len(anchors) == 1
    a = anchors[0]
    assert a.location.line == 12            # sink 行
    assert a.location.file.name == "main.c"
    # codeFlows 被还原成 dataflow_path
    assert len(a.dataflow_path) >= 2
    assert a.source_location is not None
    assert a.source_location.line == 5      # source 行
