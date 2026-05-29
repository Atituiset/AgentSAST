from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    VULNERABLE = "vulnerable"
    SAFE = "safe"
    UNCERTAIN = "uncertain"


@dataclass
class LLMResult:
    anchor_file: str
    anchor_line: int
    verdict: Verdict
    confidence: float
    reason: str
    cwe: str = ""
    raw_response: str = ""

    def to_dict(self) -> dict:
        return {
            "anchor_file": self.anchor_file,
            "anchor_line": self.anchor_line,
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "cwe": self.cwe,
        }

    @property
    def is_vulnerable(self) -> bool:
        return self.verdict == Verdict.VULNERABLE
