# src/agentsast/layer1/infer.py
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .base import ScanContext, register_scanner
from .handlers import infer as infer_handler
from .sarif_parser import parse_sarif_to_anchors

logger = logging.getLogger(__name__)


@register_scanner("infer")
class InferScanner:
    name = "Infer"
    requires_compilation = True

    def __init__(self, timeout: int = 1800):
        self.timeout = timeout

    def is_available(self) -> bool:
        return shutil.which("infer") is not None

    def _run_infer(self, ctx: ScanContext) -> Path:
        """执行 infer，返回 report.sarif 路径。"""
        cmd = [
            "infer", "--sarif", "--biabduction", "--pulse",
            "--compilation-database", str(ctx.compile_db),
        ]
        out_dir = ctx.target / "infer-out"
        subprocess.run(cmd, capture_output=True, text=True,
                       cwd=str(ctx.target), timeout=self.timeout)
        return out_dir / "report.sarif"

    def scan(self, ctx: ScanContext) -> list:
        if ctx.compile_db is None or not self.is_available():
            logger.warning("Infer skipped (compile_db=%s, available=%s)",
                           ctx.compile_db, self.is_available())
            return []
        try:
            report = self._run_infer(ctx)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.exception("Infer execution failed")
            return []
        if not report.exists():
            logger.warning("Infer produced no report at %s", report)
            return []
        anchors = parse_sarif_to_anchors(report)
        for a in anchors:
            if a.tool.lower() == "infer":
                infer_handler.enhance_anchor(a)
        return anchors
