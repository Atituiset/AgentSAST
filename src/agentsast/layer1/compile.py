# src/agentsast/layer1/compile.py
"""compile_commands.json 供应：用户直供(--compile-db/--compile-dir) > 本地生成(--build-cmd via Bear) > None。"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

COMPILE_DB_NAME = "compile_commands.json"


def _run_subprocess(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd))
    return proc.returncode, proc.stdout + proc.stderr


def _generate_with_bear(build_cmd: str, build_dir: Path, dest: Path) -> Path:
    """用 Bear（make/autotools）拦截生成 compile_commands.json。"""
    bear = shutil.which("bear") or "bear"
    cmd = [bear, "--", *build_cmd.split()]
    rc, out = _run_subprocess(cmd, build_dir)
    if rc != 0:
        logger.warning("Bear build reported rc=%d: %s", rc, out[:200])
    # Bear 默认在 build_dir 产出 compile_commands.json
    produced = build_dir / COMPILE_DB_NAME
    if produced.exists():
        return produced
    return dest


def resolve_compile_commands(
    compile_db: Path | None = None,
    compile_dir: Path | None = None,
    build_cmd: str | None = None,
    build_dir: Path | None = None,
) -> Path | None:
    """按优先级解析 compile_commands.json 路径，无解则返回 None。"""
    # 1. 用户直供文件
    if compile_db is not None:
        if compile_db.exists():
            return compile_db
        logger.warning("--compile-db not found: %s", compile_db)
    # 2. 目录（远端同步产物）
    if compile_dir is not None:
        candidate = Path(compile_dir) / COMPILE_DB_NAME
        if candidate.exists():
            return candidate
        logger.warning("No %s under --compile-dir %s", COMPILE_DB_NAME, compile_dir)
    # 3. 本地生成
    if build_cmd is not None:
        bd = Path(build_dir) if build_dir else Path.cwd()
        dest = bd / COMPILE_DB_NAME
        try:
            return _generate_with_bear(build_cmd, bd, dest)
        except Exception:
            logger.exception("Failed to generate compile_commands via build-cmd")
    # 4. 都没有 → None（编译线扫描器将降级跳过）
    return None
