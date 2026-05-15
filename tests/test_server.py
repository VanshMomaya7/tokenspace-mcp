from __future__ import annotations

import sys

import pytest

from tokenspace.server import install_skill, main


# ── Bug 1: --help / -h print usage and exit cleanly ──────────────────────────


def test_main_help_flag_prints_usage(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["tokenspace", "--help"])
    main()
    out = capsys.readouterr().out
    assert "tokenspace-mcp" in out
    assert "install-skill" in out
    assert "read_structure" in out


def test_main_short_help_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["tokenspace", "-h"])
    main()
    out = capsys.readouterr().out
    assert "tokenspace-mcp" in out


# ── Warning 1: install-skill prints correct messages on fresh vs update ───────


def test_install_skill_fresh_install(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[arg-type]
    install_skill()
    out = capsys.readouterr().out
    assert "Skill installed: .claude/SKILL.md" in out
    assert "MCP server registered: .claude/settings.json" in out


def test_install_skill_already_installed(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[arg-type]
    install_skill()
    capsys.readouterr()  # discard first-run output
    install_skill()
    out = capsys.readouterr().out
    assert "already installed" in out
    assert "already registered" in out
