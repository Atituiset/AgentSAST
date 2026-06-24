from __future__ import annotations

from pathlib import Path

from agentsast.layer1.flawfinder import FlawfinderScanner
from agentsast.layer1.models import Anchor, Location, Severity
from agentsast.layer2.models import SlicingResult
from agentsast.layer2.slicer import SlicingEngine
from agentsast.layer3.models import LLMResult, Verdict
from agentsast.layer3.prompt import build_payload, build_user_prompt

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
VULN_FILE = SAMPLES_DIR / "vulnerable_server.c"
SAFE_FILE = SAMPLES_DIR / "safe_server.c"


class TestFlawfinderPatternScan:
    def test_finds_memcpy(self):
        scanner = FlawfinderScanner()
        anchors = scanner._pattern_scan(VULN_FILE)
        func_names = [a.sink_function for a in anchors]
        assert "memcpy" in func_names
        assert "strcpy" in func_names
        assert "sprintf" in func_names

    def test_anchor_has_cwe(self):
        scanner = FlawfinderScanner()
        anchors = scanner._pattern_scan(VULN_FILE)
        memcpy_anchors = [a for a in anchors if a.sink_function == "memcpy"]
        assert len(memcpy_anchors) > 0
        assert memcpy_anchors[0].cwe == "CWE-120"

    def test_safe_file_fewer_anchors(self):
        scanner = FlawfinderScanner()
        vuln_anchors = scanner._pattern_scan(VULN_FILE)
        safe_anchors = scanner._pattern_scan(SAFE_FILE)
        assert len(vuln_anchors) > len(safe_anchors)

    def test_anchor_location(self):
        scanner = FlawfinderScanner()
        anchors = scanner._pattern_scan(VULN_FILE)
        assert all(a.line > 0 for a in anchors)
        assert all(a.file == VULN_FILE for a in anchors)


class TestSlicingEngine:
    def test_slice_memcpy_anchor(self):
        anchor = Anchor(
            rule_id="test-memcpy",
            tool="test",
            severity=Severity.WARNING,
            message="memcpy without bounds check",
            location=Location(file=VULN_FILE, line=17),
            cwe="CWE-120",
            sink_function="memcpy",
        )
        engine = SlicingEngine()
        result = engine.slice_anchor(anchor)
        assert result.raw_function is not None
        assert len(result.struct_defs) > 0
        content = result.raw_function.content
        assert "RequestContext" in content or "user_buf" in content

    def test_slice_safe_code(self):
        anchor = Anchor(
            rule_id="test-memcpy",
            tool="test",
            severity=Severity.WARNING,
            message="memcpy call",
            location=Location(file=SAFE_FILE, line=14),
            cwe="CWE-120",
            sink_function="memcpy",
        )
        engine = SlicingEngine()
        result = engine.slice_anchor(anchor)
        assert result.raw_function is not None

    def test_slice_has_struct_def(self):
        anchor = Anchor(
            rule_id="test-memcpy",
            tool="test",
            severity=Severity.WARNING,
            message="memcpy",
            location=Location(file=VULN_FILE, line=17),
            cwe="CWE-120",
            sink_function="memcpy",
        )
        engine = SlicingEngine()
        result = engine.slice_anchor(anchor)
        struct_names = [s.label for s in result.struct_defs]
        assert any("RequestContext" in name for name in struct_names)


class TestPromptBuilder:
    def test_build_payload_structure(self):
        anchor = Anchor(
            rule_id="test",
            tool="Semgrep",
            severity=Severity.WARNING,
            message="test alert",
            location=Location(file=Path("test.c"), line=7),
            cwe="CWE-120",
            sink_function="memcpy",
        )
        slicing = SlicingResult(
            anchor_file=Path("test.c"),
            anchor_line=7,
            raw_function=None,
        )
        payload = build_payload(anchor, slicing)
        assert "alert" in payload
        assert "context_slices" in payload
        assert payload["alert"]["tool"] == "Semgrep"
        assert payload["alert"]["cwe"] == "CWE-120"

    def test_build_user_prompt_includes_alert(self):
        anchor = Anchor(
            rule_id="CWE-120",
            tool="Semgrep",
            severity=Severity.WARNING,
            message="Buffer overflow",
            location=Location(file=Path("test.c"), line=7),
            cwe="CWE-120",
            sink_function="memcpy",
        )
        slicing = SlicingResult(anchor_file=Path("test.c"), anchor_line=7, raw_function=None)
        payload = build_payload(anchor, slicing)
        prompt = build_user_prompt(payload)
        assert "CWE-120" in prompt
        assert "memcpy" in prompt
        assert "Semgrep" in prompt


class TestLLMResult:
    def test_verdict_vulnerable(self):
        result = LLMResult(
            anchor_file="test.c",
            anchor_line=7,
            verdict=Verdict.VULNERABLE,
            confidence=0.95,
            reason="Buffer overflow",
            cwe="CWE-120",
        )
        assert result.is_vulnerable
        d = result.to_dict()
        assert d["verdict"] == "vulnerable"

    def test_verdict_safe(self):
        result = LLMResult(
            anchor_file="test.c",
            anchor_line=7,
            verdict=Verdict.SAFE,
            confidence=0.9,
            reason="Has bounds check",
            cwe="CWE-120",
        )
        assert not result.is_vulnerable

    def test_low_confidence_uncertain(self):
        result = LLMResult(
            anchor_file="test.c",
            anchor_line=7,
            verdict=Verdict.UNCERTAIN,
            confidence=0.2,
            reason="Cannot determine",
        )
        assert not result.is_vulnerable


class TestPipelineCompileDb:
    def test_pipeline_accepts_compile_db(self, tmp_path):
        from agentsast.pipeline.engine import Pipeline
        p = Pipeline(tools=["semgrep"], compile_db=tmp_path / "cc.json")
        assert p.compile_db == tmp_path / "cc.json"
