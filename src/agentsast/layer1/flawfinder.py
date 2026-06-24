from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from .base import ScanContext, register_scanner
from .models import Anchor, Location, Severity

logger = logging.getLogger(__name__)


@register_scanner("flawfinder")
class FlawfinderScanner:
    NAME = "Flawfinder"
    requires_compilation = False

    DANGER_FUNCTIONS = {
        "memcpy": "CWE-120",
        "strcpy": "CWE-120",
        "strcat": "CWE-120",
        "gets": "CWE-120",
        "sprintf": "CWE-120",
        "scanf": "CWE-120",
        "vsprintf": "CWE-120",
        "strncat": "CWE-120",
        "strncpy": "CWE-120",
        "snprintf": "CWE-120",
        "malloc": "CWE-787",
        "realloc": "CWE-787",
        "free": "CWE-415",
        "system": "CWE-78",
        "popen": "CWE-78",
        "execl": "CWE-78",
        "execle": "CWE-78",
        "execlp": "CWE-78",
        "execv": "CWE-78",
        "execve": "CWE-78",
        "execvp": "CWE-78",
        "printf": "CWE-134",
        "fprintf": "CWE-134",
        "syslog": "CWE-134",
    }

    def __init__(self, min_level: int = 3, timeout: int = 300):
        self.min_level = min_level
        self.timeout = timeout

    @property
    def name(self) -> str:
        return self.NAME

    def is_available(self) -> bool:
        try:
            result = subprocess.run(
                ["flawfinder", "--version"],
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
            logger.info(
                "Flawfinder not found, using built-in pattern scanner"
            )
            return self._pattern_scan(target)

        cmd = [
            "flawfinder",
            "--minlevel",
            str(self.min_level),
            "--sarif",
            str(target),
        ]
        logger.info("Running Flawfinder: %s", " ".join(cmd))
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return self._parse_sarif_output(proc.stdout)
        except subprocess.TimeoutExpired:
            logger.error("Flawfinder timed out")
            return []
        except FileNotFoundError:
            return self._pattern_scan(target)

    def _parse_sarif_output(self, sarif_text: str) -> list[Anchor]:
        import json

        try:
            sarif = json.loads(sarif_text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Flawfinder SARIF output")
            return []

        anchors: list[Anchor] = []
        for run in sarif.get("runs", []):
            for result in run.get("results", []):
                locs = result.get("locations", [])
                if not locs:
                    continue
                phys = locs[0].get("physicalLocation", {})
                region = phys.get("region", {})
                uri = phys.get("artifactLocation", {}).get("uri", "")

                anchor = Anchor(
                    rule_id=result.get("ruleId", "flawfinder"),
                    tool=self.NAME,
                    severity=Severity(result.get("level", "warning")),
                    message=result.get("message", {}).get("text", ""),
                    location=Location(
                        file=Path(uri),
                        line=region.get("startLine", 0),
                        col=region.get("startColumn", 0),
                    ),
                    cwe=self._extract_cwe(result),
                    sink_function=self._extract_sink_from_message(
                        result.get("message", {}).get("text", "")
                    ),
                    raw_sarif=result,
                )
                anchors.append(anchor)

        logger.info("Flawfinder found %d anchors", len(anchors))
        return anchors

    def _pattern_scan(self, target: Path) -> list[Anchor]:
        logger.info("Running built-in pattern scanner on %s", target)
        anchors: list[Anchor] = []

        func_pattern = re.compile(
            r"\b("
            + "|".join(
                re.escape(f) for f in self.DANGER_FUNCTIONS
            )
            + r")\s*\("
        )

        for source_file in self._collect_source_files(target):
            try:
                content = source_file.read_text(errors="replace")
            except OSError:
                continue

            for match in func_pattern.finditer(content):
                func_name = match.group(1)
                line_no = content[: match.start()].count("\n") + 1
                cwe = self.DANGER_FUNCTIONS[func_name]
                anchor = Anchor(
                    rule_id=f"agentsast-builtin-{func_name}",
                    tool="AgentSAST-Pattern",
                    severity=Severity.WARNING,
                    message=(
                        f"Dangerous function '{func_name}' called"
                        f" — potential {cwe} vulnerability"
                    ),
                    location=Location(
                        file=source_file, line=line_no
                    ),
                    cwe=cwe,
                    sink_function=func_name,
                )
                anchors.append(anchor)

        logger.info("Pattern scanner found %d anchors", len(anchors))
        return anchors

    @staticmethod
    def _collect_source_files(target: Path) -> list[Path]:
        extensions = {
            ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx"
        }
        if target.is_file():
            return [target] if target.suffix in extensions else []
        return [
            p for p in target.rglob("*") if p.suffix in extensions
        ]

    @staticmethod
    def _extract_cwe(result: dict) -> str:
        for tag in result.get("properties", {}).get("tags", []):
            if isinstance(tag, str) and tag.startswith("CWE-"):
                return tag
        msg = result.get("message", {}).get("text", "")
        m = re.search(r"CWE-\d+", msg)
        return m.group(0) if m else ""

    @staticmethod
    def _extract_sink_from_message(message: str) -> str:
        for fn in [
            "memcpy", "strcpy", "strcat", "gets", "sprintf", "scanf",
            "malloc", "realloc", "free", "system", "popen", "printf",
        ]:
            if fn in message.lower():
                return fn
        return ""
