from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..layer1.models import Anchor
from ..layer1.scanner import scan as layer1_scan
from ..layer2.models import SlicingResult
from ..layer2.slicer import SlicingEngine
from ..layer3.judge import LLMJudge
from ..layer3.models import Verdict

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    target: str
    total_anchors: int = 0
    results: list[dict] = field(default_factory=list)
    vulnerable: int = 0
    safe: int = 0
    uncertain: int = 0

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "total_anchors": self.total_anchors,
            "vulnerable": self.vulnerable,
            "safe": self.safe,
            "uncertain": self.uncertain,
            "results": self.results,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(
            self.to_dict(), indent=indent, ensure_ascii=False
        )


class Pipeline:
    def __init__(
        self,
        tools: list[str] | None = None,
        semgrep_config: str = "p/c",
        max_call_depth: int = 2,
        llm_model: str = "gpt-4o",
        llm_api_key: str | None = None,
        llm_base_url: str | None = None,
        skip_llm: bool = False,
    ):
        self.tools = tools or ["semgrep", "flawfinder"]
        self.semgrep_config = semgrep_config
        self.max_call_depth = max_call_depth
        self.skip_llm = skip_llm
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.llm_base_url = llm_base_url

    def run(
        self,
        target: Path,
        project_root: Path | None = None,
    ) -> PipelineResult:
        target = Path(target).resolve()
        result = PipelineResult(target=str(target))

        logger.info("=== Layer 1: SAST Anchor Scanning ===")
        anchors = layer1_scan(
            target, tools=self.tools, config=self.semgrep_config
        )
        result.total_anchors = len(anchors)

        if not anchors:
            logger.info("No anchors found by Layer 1, pipeline complete")
            return result

        logger.info("=== Layer 2: Context Slicing ===")
        engine = SlicingEngine(max_call_depth=self.max_call_depth)
        sliced_anchors: list[tuple[Anchor, SlicingResult]] = []
        for anchor in anchors:
            try:
                slicing = engine.slice_anchor(
                    anchor, project_root=project_root
                )
                sliced_anchors.append((anchor, slicing))
                logger.info(
                    "Sliced %s:%d -> %d struct_defs, "
                    "%d dataflow, %d callers",
                    anchor.file,
                    anchor.line,
                    len(slicing.struct_defs),
                    len(slicing.dataflow_slices),
                    len(slicing.caller_slices),
                )
            except Exception:
                logger.exception(
                    "Slicing failed for %s:%d",
                    anchor.file,
                    anchor.line,
                )

        if self.skip_llm:
            for anchor, slicing in sliced_anchors:
                entry = {
                    "anchor": anchor.to_dict(),
                    "slicing": slicing.to_dict(),
                    "llm": None,
                }
                result.results.append(entry)
            return result

        logger.info("=== Layer 3: LLM Judgment ===")
        judge = LLMJudge(
            model=self.llm_model,
            api_key=self.llm_api_key,
            base_url=self.llm_base_url,
        )

        for anchor, slicing in sliced_anchors:
            try:
                llm_result = judge.judge(anchor, slicing)
                entry = {
                    "anchor": anchor.to_dict(),
                    "slicing": slicing.to_dict(),
                    "llm": llm_result.to_dict(),
                }
                result.results.append(entry)

                if llm_result.verdict == Verdict.VULNERABLE:
                    result.vulnerable += 1
                elif llm_result.verdict == Verdict.SAFE:
                    result.safe += 1
                else:
                    result.uncertain += 1

                logger.info(
                    "Verdict for %s:%d -> %s (confidence: %.2f)",
                    anchor.file,
                    anchor.line,
                    llm_result.verdict.value,
                    llm_result.confidence,
                )
            except Exception:
                logger.exception(
                    "LLM judgment failed for %s:%d",
                    anchor.file,
                    anchor.line,
                )
                result.uncertain += 1
                entry = {
                    "anchor": anchor.to_dict(),
                    "slicing": slicing.to_dict(),
                    "llm": {
                        "verdict": "uncertain",
                        "confidence": 0.0,
                        "reason": "LLM judgment failed",
                    },
                }
                result.results.append(entry)

        return result
