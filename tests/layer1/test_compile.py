# tests/layer1/test_compile.py
from __future__ import annotations

from agentsast.layer1.compile import resolve_compile_commands


def test_explicit_compile_db_wins(tmp_path):
    db = tmp_path / "cc.json"
    db.write_text("[]")
    assert resolve_compile_commands(compile_db=db) == db


def test_compile_dir_resolves_json(tmp_path):
    (tmp_path / "compile_commands.json").write_text("[]")
    assert resolve_compile_commands(compile_dir=tmp_path) == tmp_path / "compile_commands.json"


def test_build_cmd_runs_bear(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agentsast.layer1.compile._run_subprocess",
        lambda cmd, cwd: (0, ""),
    )
    def fake_gen(cmd, cwd, dest):
        dest.write_text("[]")
        return dest
    monkeypatch.setattr("agentsast.layer1.compile._generate_with_bear", fake_gen)
    result = resolve_compile_commands(build_cmd="make", build_dir=tmp_path)
    assert result is not None
    assert result.name == "compile_commands.json"


def test_none_when_nothing_provided():
    assert resolve_compile_commands() is None
