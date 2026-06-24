from __future__ import annotations

import logging
from pathlib import Path

from .base import ScanContext, SCANNER_REGISTRY
from .flawfinder import FlawfinderScanner   # import 副作用：触发注册
from .models import Anchor
from .sarif_parser import parse_sarif_to_anchors
from .semgrep import SemgrepScanner          # import 副作用：触发注册

logger = logging.getLogger(__name__)


def parse_sarif_file(sarif_path: Path) -> list[Anchor]:
    """向后兼容：委托给通用 SARIF 解析器。"""
    return parse_sarif_to_anchors(sarif_path)


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
