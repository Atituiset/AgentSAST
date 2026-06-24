# src/agentsast/layer1/cppcheck.py
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .base import ScanContext, register_scanner
from .handlers.cppcheck import cppcheck_xml_to_anchors

logger = logging.getLogger(__name__)


@register_scanner("cppcheck")
class CppcheckScanner:
    name = "Cppcheck"
    requires_compilation = True

    def __init__(self, timeout: int = 1800):
        self.timeout = timeout

    def is_available(self) -> bool:
        return shutil.which("cppcheck") is not None

    def _run_cppcheck(self, ctx: ScanContext) -> Path:
        """执行 cppcheck，返回 XML 报告路径。"""
        out = ctx.target / "cppcheck.xml"
        cmd = [
            "cppcheck", "--project=" + str(ctx.compile_db),
            "--xml", "--enable=all", "-j", "4",
        ]
        with open(out, "w") as f:
            subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE,
                           cwd=str(ctx.target), timeout=self.timeout)
        return out

    def scan(self, ctx: ScanContext) -> list:
        if ctx.compile_db is None or not self.is_available():
            logger.warning("Cppcheck skipped (compile_db=%s, available=%s)",
                           ctx.compile_db, self.is_available())
            return []
        try:
            xml = self._run_cppcheck(ctx)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.exception("Cppcheck execution failed")
            return []
        if not xml.exists():
            logger.warning("Cppcheck produced no report at %s", xml)
            return []
        return cppcheck_xml_to_anchors(xml)
