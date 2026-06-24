# src/agentsast/layer1/csa.py
from __future__ import annotations

import glob
import logging
import shutil
import subprocess
from pathlib import Path

from .base import ScanContext, register_scanner
from .sarif_parser import parse_sarif_to_anchors
from .handlers import csa as csa_handler

logger = logging.getLogger(__name__)


@register_scanner("csa")
class CsaScanner:
    name = "CSA"
    requires_compilation = True

    def __init__(self, timeout: int = 1800):
        self.timeout = timeout

    def is_available(self) -> bool:
        return shutil.which("analyze-build") is not None

    def _run_csa(self, ctx: ScanContext) -> Path:
        """执行 analyze-build（scan-build-py），返回产出的 *.sarif 路径。"""
        out_dir = ctx.target / "result-csa"
        cmd = [
            "analyze-build", "--status-bugs", "--sarif",
            "-o", str(out_dir),
        ]
        subprocess.run(cmd, capture_output=True, text=True,
                       cwd=str(ctx.target), timeout=self.timeout)
        sarifs = glob.glob(str(out_dir / "*.sarif"))
        return Path(sarifs[0]) if sarifs else out_dir / "results-merged.sarif"

    def scan(self, ctx: ScanContext) -> list:
        if ctx.compile_db is None or not self.is_available():
            logger.warning("CSA skipped (compile_db=%s, available=%s)",
                           ctx.compile_db, self.is_available())
            return []
        try:
            report = self._run_csa(ctx)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.exception("CSA execution failed")
            return []
        if not report.exists():
            logger.warning("CSA produced no report at %s", report)
            return []
        anchors = parse_sarif_to_anchors(report)
        for a in anchors:
            if csa_handler.is_csa_result(a):
                csa_handler.enhance_anchor(a)
        return anchors
