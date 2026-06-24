from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .base import ScanContext, register_scanner
from .models import Anchor, Location, Severity

logger = logging.getLogger(__name__)


@register_scanner("semgrep")
class SemgrepScanner:
    NAME = "Semgrep"
    requires_compilation = False

    def __init__(self, config: str = "p/c", timeout: int = 300):
        self.config = config
        self.timeout = timeout

    @property
    def name(self) -> str:
        return self.NAME

    def is_available(self) -> bool:
        try:
            result = subprocess.run(
                ["semgrep", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def scan(self, ctx) -> list[Anchor]:
        target = ctx.target if isinstance(ctx, ScanContext) else ctx
        if not self.is_available():
            logger.warning("Semgrep not found in PATH, skipping")
            return []

        sarif_path = Path("/tmp/agentsast_semgrep.sarif")
        cmd = [
            "semgrep",
            "scan",
            "--config", self.config,
            "--sarif",
            "-o", str(sarif_path),
            "--no-git",
            str(target),
        ]
        logger.info("Running Semgrep: %s", " ".join(cmd))
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            logger.error("Semgrep timed out after %ds", self.timeout)
            return []
        except FileNotFoundError:
            logger.error("Semgrep binary not found")
            return []

        if not sarif_path.exists():
            logger.warning("Semgrep did not produce SARIF output")
            return []

        return self._parse_sarif(sarif_path)

    def _parse_sarif(self, sarif_path: Path) -> list[Anchor]:
        with open(sarif_path) as f:
            sarif = json.load(f)

        anchors: list[Anchor] = []
        for run in sarif.get("runs", []):
            tool_name = run.get("tool", {}).get("driver", {}).get("name", self.NAME)
            rules_map = {}
            for rule in run.get("tool", {}).get("driver", {}).get("rules", []):
                rules_map[rule["id"]] = rule

            for result in run.get("results", []):
                rule_id = result.get("ruleId", "unknown")
                rule = rules_map.get(rule_id, {})
                cwe = ""
                for tag in rule.get("properties", {}).get("tags", []):
                    if tag.startswith("CWE-"):
                        cwe = tag
                        break

                locs = result.get("locations", [])
                if not locs:
                    continue
                phys = locs[0].get("physicalLocation", {})
                artifact = phys.get("artifactLocation", {})
                region = phys.get("region", {})
                file_path = Path(artifact.get("uri", ""))
                if file_path.is_absolute():
                    file_path = Path(str(file_path).lstrip("/"))

                anchor = Anchor(
                    rule_id=rule_id,
                    tool=tool_name,
                    severity=Severity(result.get("level", "warning")),
                    message=result.get("message", {}).get("text", ""),
                    location=Location(
                        file=file_path,
                        line=region.get("startLine", 0),
                        col=region.get("startColumn", 0),
                        end_line=region.get("endLine", 0),
                        end_col=region.get("endColumn", 0),
                    ),
                    cwe=cwe,
                    sink_function=self._extract_sink(result),
                    sink_params=self._extract_sink_params(result),
                    raw_sarif=result,
                )
                anchors.append(anchor)

        logger.info("Semgrep found %d anchors", len(anchors))
        return anchors

    @staticmethod
    def _extract_sink(result: dict) -> str:
        msg = result.get("message", {}).get("text", "")
        for fn in ["memcpy", "strcpy", "strcat", "sprintf", "gets", "scanf",
                    "printf", "malloc", "realloc", "free", "system", "popen",
                    "exec", "memmove", "strncpy", "snprintf"]:
            if fn in msg.lower():
                return fn
        return ""

    @staticmethod
    def _extract_sink_params(result: dict) -> list[str]:
        code_flows = result.get("codeFlows", [])
        if not code_flows:
            return []
        params = []
        for flow in code_flows:
            for tf in flow.get("threadFlows", []):
                for loc in tf.get("locations", []):
                    msg = loc.get("location", {}).get("message", {}).get("text", "")
                    if msg:
                        params.append(msg)
        return params
