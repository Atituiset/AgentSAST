# tests/test_cli.py
from __future__ import annotations

from click.testing import CliRunner

from agentsast.cli import main


def test_cli_accepts_compile_options(tmp_path):
    runner = CliRunner()
    target = tmp_path / "a.c"
    target.write_text("int main(){return 0;}")
    result = runner.invoke(main, [
        str(target), "--skip-llm", "--tools", "flawfinder",
        "--compile-dir", str(tmp_path),
    ])
    assert result.exit_code == 0


def test_cli_accepts_l2_backend(tmp_path):
    runner = CliRunner()
    target = tmp_path / "a.c"
    target.write_text("int main(){return 0;}")
    result = runner.invoke(main, [
        str(target), "--skip-llm", "--tools", "flawfinder",
        "--l2-backend", "treesitter",
    ])
    assert result.exit_code == 0
