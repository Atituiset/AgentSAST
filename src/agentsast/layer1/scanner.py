from __future__ import annotations

import json
import logging
from pathlib import Path

from .flawfinder import FlawfinderScanner
from .models import Anchor, Location, Severity
from .semgrep import SemgrepScanner

logger = logging.getLogger(__name__)


def parse_sarif_file(sarif_path: Path) -> list[Anchor]:
    with open(sarif_path) as f:
        sarif = json.load(f)

    anchors: list[Anchor] = []
    for run in sarif.get("runs", []):
        tool_name = (
            run.get("tool", {}).get("driver", {}).get("name", "unknown")
        )
        rules_map: dict[str, dict] = {}
        for rule in run.get("tool", {}).get("driver", {}).get("rules", []):
            rules_map[rule["id"]] = rule

        for result in run.get("results", []):
            rule_id = result.get("ruleId", "unknown")
            rule = rules_map.get(rule_id, {})
            cwe = ""
            for tag in rule.get("properties", {}).get("tags", []):
                if isinstance(tag, str) and tag.startswith("CWE-"):
                    cwe = tag
                    break

            locs = result.get("locations", [])
            if not locs:
                continue
            phys = locs[0].get("physicalLocation", {})
            artifact = phys.get("artifactLocation", {})
            region = phys.get("region", {})

            anchor = Anchor(
                rule_id=rule_id,
                tool=tool_name,
                severity=Severity(result.get("level", "warning")),
                message=result.get("message", {}).get("text", ""),
                location=Location(
                    file=Path(artifact.get("uri", "")),
                    line=region.get("startLine", 0),
                    col=region.get("startColumn", 0),
                    end_line=region.get("endLine", 0),
                    end_col=region.get("endColumn", 0),
                ),
                cwe=cwe,
                raw_sarif=result,
            )
            anchors.append(anchor)

    return anchors


def scan(
    target: Path,
    tools: list[str] | None = None,
    config: str = "p/c",
) -> list[Anchor]:
    if tools is None:
        tools = ["semgrep", "flawfinder"]

    target = Path(target).resolve()
    if not target.exists():
        raise FileNotFoundError(
            f"Target path does not exist: {target}"
        )

    all_anchors: list[Anchor] = []
    seen: set[tuple[str, str, int]] = set()

    scanners = []
    if "semgrep" in tools:
        scanners.append(SemgrepScanner(config=config))
    if "flawfinder" in tools:
        scanners.append(FlawfinderScanner())

    for scanner in scanners:
        try:
            anchors = scanner.scan(target)
        except Exception:
            logger.exception("Scanner %s failed", scanner.NAME)
            continue

        for anchor in anchors:
            key = (anchor.tool, str(anchor.file), anchor.line)
            if key not in seen:
                seen.add(key)
                all_anchors.append(anchor)

    logger.info("Layer1 total unique anchors: %d", len(all_anchors))
    return all_anchors
