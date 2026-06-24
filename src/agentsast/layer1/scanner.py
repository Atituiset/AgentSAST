from __future__ import annotations

import json
import logging
from pathlib import Path

from .base import ScanContext, SCANNER_REGISTRY
from .flawfinder import FlawfinderScanner   # import 副作用：触发注册
from .models import Anchor, Location, Severity
from .semgrep import SemgrepScanner          # import 副作用：触发注册

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
    compile_db: Path | None = None,
) -> list[Anchor]:
    if tools is None:
        tools = ["semgrep", "flawfinder"]

    target = Path(target).resolve()
    if not target.exists():
        raise FileNotFoundError(
            f"Target path does not exist: {target}"
        )

    ctx = ScanContext(target=target, compile_db=compile_db)
    all_anchors: list[Anchor] = []
    seen: set[tuple[str, str, int]] = set()

    for key in tools:
        if key not in SCANNER_REGISTRY:
            logger.warning("Unknown scanner: %s, skipping", key)
            continue
        kwargs: dict = {"config": config} if key == "semgrep" else {}
        scanner = SCANNER_REGISTRY[key](**kwargs)
        if scanner.requires_compilation and ctx.compile_db is None:
            logger.warning(
                "Scanner %s requires compilation but no compile_db provided, skipping",
                scanner.name,
            )
            continue
        try:
            if not scanner.is_available():
                logger.warning("Scanner %s not available, skipping", scanner.name)
                continue
            anchors = scanner.scan(ctx)
        except Exception:
            logger.exception("Scanner %s failed", getattr(scanner, "name", key))
            continue

        for anchor in anchors:
            akey = (anchor.tool, str(anchor.file), anchor.line)
            if akey not in seen:
                seen.add(akey)
                all_anchors.append(anchor)

    logger.info("Layer1 total unique anchors: %d", len(all_anchors))
    return all_anchors
