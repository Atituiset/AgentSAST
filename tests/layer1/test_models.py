# tests/layer1/test_models.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.models import Anchor, Location, Severity


def test_anchor_defaults_no_path():
    a = Anchor(
        rule_id="r", tool="t", severity=Severity.WARNING,
        message="m", location=Location(file=Path("a.c"), line=1),
    )
    assert a.source_location is None
    assert a.dataflow_path == []


def test_anchor_with_path_serializes():
    a = Anchor(
        rule_id="r", tool="t", severity=Severity.WARNING,
        message="m", location=Location(file=Path("a.c"), line=10),
        source_location=Location(file=Path("a.c"), line=3),
        dataflow_path=[
            Location(file=Path("a.c"), line=3),
            Location(file=Path("a.c"), line=7),
            Location(file=Path("a.c"), line=10),
        ],
    )
    d = a.to_dict()
    assert d["source_location"]["line"] == 3
    assert [loc["line"] for loc in d["dataflow_path"]] == [3, 7, 10]
