# src/agentsast/layer1/handlers/cppcheck.py
"""Cppcheck XML → Anchor。参考 gen-auto/parse_cppcheck.py（全新实现，去除全局变量竞态）。

CWE 映射表（参考 gen-auto INTERESTED_ERRORS）。
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import Anchor, Location, Severity

logger = logging.getLogger(__name__)

CWE_MAP = {
    "bufferAccessOutOfBounds": "CWE-120",
    "nullPointer": "CWE-476",
    "memleak": "CWE-401",
    "deallocDealloc": "CWE-415",
    "integerOverflow": "CWE-190",
}
SEVERITY_MAP = {
    "error": Severity.ERROR,
    "warning": Severity.WARNING,
    "style": Severity.NOTE,
}


def cppcheck_xml_to_anchors(xml_path: Path) -> list[Anchor]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    anchors: list[Anchor] = []
    for err in root.iter("error"):
        error_id = err.get("id", "unknown")
        msg = err.get("msg", "")
        loc = err.find("location")
        if loc is None:
            continue
        anchors.append(Anchor(
            rule_id=error_id,
            tool="Cppcheck",
            severity=SEVERITY_MAP.get(err.get("severity", "warning"), Severity.WARNING),
            message=msg,
            location=Location(
                file=Path(loc.get("file", "")),
                line=int(loc.get("line", "0")),
                col=int(loc.get("column", "0")),
            ),
            cwe=CWE_MAP.get(error_id, ""),
        ))
    logger.info("Cppcheck XML parsed: %d anchors", len(anchors))
    return anchors
