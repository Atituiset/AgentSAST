# tests/layer1/test_handlers_csa.py
from __future__ import annotations

from pathlib import Path

from agentsast.layer1.models import Anchor, Location, Severity
from agentsast.layer1.handlers.csa import enhance_anchor, is_csa_result


def test_is_csa_result_detects_clang():
    a = Anchor(rule_id="core.NullDereference", tool="clang",
               severity=Severity.WARNING, message="m",
               location=Location(file=Path("a.c"), line=10))
    assert is_csa_result(a) is True


def test_enhance_uses_codeflows_when_present():
    a = Anchor(rule_id="core.NullDereference", tool="clang",
               severity=Severity.WARNING, message="m",
               location=Location(file=Path("a.c"), line=12),
               dataflow_path=[Location(file=Path("a.c"), line=5)])
    enhance_anchor(a)
    assert a.source_location is not None
    assert a.source_location.line == 5


def test_enhance_noop_without_info():
    a = Anchor(rule_id="core.NullDereference", tool="clang",
               severity=Severity.WARNING, message="no lines here",
               location=Location(file=Path("a.c"), line=12))
    enhance_anchor(a)
    assert a.source_location is None  # 无 codeFlows 且 message 无行号 → 保持空（保守）
