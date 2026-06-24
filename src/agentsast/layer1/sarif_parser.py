# src/agentsast/layer1/sarif_parser.py
from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import Anchor, Location, Severity

logger = logging.getLogger(__name__)


def _region_to_location(phys: dict, default_msg: str = "") -> Location:
    """从 physicalLocation 构建 Location；缺失 message 时回退到 default_msg。"""
    art = phys.get("artifactLocation", {})
    region = phys.get("region", {})
    uri = art.get("uri", "")
    fp = Path(uri.lstrip("/"))
    return Location(
        file=fp,
        line=region.get("startLine", 0),
        col=region.get("startColumn", 0),
        end_line=region.get("endLine", 0),
        end_col=region.get("endColumn", 0),
        message=phys.get("message", {}).get("text", default_msg),
    )


def _extract_cwe(rule: dict) -> str:
    for tag in rule.get("properties", {}).get("tags", []):
        if isinstance(tag, str) and tag.startswith("CWE-"):
            return tag
    return ""


def _flow_to_path(result: dict) -> list[Location]:
    """把 result.codeFlows 展平成有序 Location 列表（source 在前）。"""
    path: list[Location] = []
    for flow in result.get("codeFlows", []):
        for tf in flow.get("threadFlows", []):
            for step in tf.get("locations", []):
                phys = step.get("location", {}).get("physicalLocation", {})
                msg = step.get("location", {}).get("message", {}).get("text", "")
                if phys:
                    path.append(_region_to_location(phys, msg))
    return path


def parse_sarif_to_anchors(sarif_path: Path) -> list[Anchor]:
    with open(sarif_path, encoding="utf-8") as f:
        sarif = json.load(f)

    anchors: list[Anchor] = []
    for run in sarif.get("runs", []):
        driver = run.get("tool", {}).get("driver", {})
        tool_name = driver.get("name", "unknown")
        rules_map = {r["id"]: r for r in driver.get("rules", []) if "id" in r}

        for result in run.get("results", []):
            try:
                rule_id = result.get("ruleId", "unknown")
                locs = result.get("locations", [])
                if not locs:
                    continue
                sink = _region_to_location(
                    locs[0].get("physicalLocation", {}),
                    result.get("message", {}).get("text", ""),
                )
                dataflow = _flow_to_path(result)
                source = dataflow[0] if dataflow else None

                try:
                    severity = Severity(result.get("level", "warning"))
                except ValueError:
                    severity = Severity.WARNING
                    logger.warning("Unknown SARIF level %r for %s, defaulting to warning", result.get("level"), rule_id)

                anchors.append(Anchor(
                    rule_id=rule_id,
                    tool=tool_name,
                    severity=severity,
                    message=result.get("message", {}).get("text", ""),
                    location=sink,
                    cwe=_extract_cwe(rules_map.get(rule_id, {})),
                    raw_sarif=result,
                    source_location=source,
                    dataflow_path=dataflow,
                ))
            except Exception:
                logger.exception("Failed to parse a SARIF result (ruleId=%s)", result.get("ruleId"))
                continue

    logger.info("SARIF parsed: %d anchors from %s", len(anchors), sarif_path)
    return anchors
