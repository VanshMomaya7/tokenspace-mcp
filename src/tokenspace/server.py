"""MCP tool definitions. Thin wrapper only — no business logic here."""
from __future__ import annotations

import importlib.resources
import json
import pathlib
import sys

from mcp.server.fastmcp import FastMCP

from tokenspace import core
from tokenspace.types import format_result

__all__: list[str] = []

mcp = FastMCP("tokenspace")


@mcp.tool()
def read_structure(file_path: str) -> str:
    """Return top-level functions and classes with signatures and line ranges.
    No bodies, no docstrings. Use before editing to locate symbols.
    Args: file_path — path to Python file.
    Returns: plain text, one symbol per line with signature and line range.
    Errors returned as text."""
    try:
        return core.read_structure(file_path)
    except Exception as exc:
        return str(exc)


@mcp.tool()
def edit_function_body(file_path: str, function_name: str, new_body: str) -> str:
    """Replace a top-level function body. Writes to disk on success.
    Args: file_path — path to file; function_name — exact name;
    new_body — replacement body as Python source (indented or not).
    Returns: success status, diff, blast_radius, patch_locality, token_cost.
    Use edit_class_method for class methods. Errors returned as text; file unchanged on failure."""
    try:
        return format_result(core.edit_function_body(file_path, function_name, new_body))
    except Exception as exc:
        return str(exc)


@mcp.tool()
def edit_class_method(
    file_path: str, class_name: str, method_name: str, new_body: str
) -> str:
    """Replace a class method body. Writes to disk on success.
    Args: file_path — path to file; class_name — containing class;
    method_name — method to replace; new_body — replacement body.
    Returns: success status, diff, blast_radius, patch_locality, token_cost.
    Errors returned as text; file unchanged on failure."""
    try:
        return format_result(
            core.edit_class_method(file_path, class_name, method_name, new_body)
        )
    except Exception as exc:
        return str(exc)


@mcp.tool()
def measure_edit(file_path: str, function_name: str, new_body: str) -> str:
    """Dry-run cost estimate for replacing a top-level function body. Never writes to disk.
    Args: file_path — path to file; function_name — function to evaluate;
    new_body — proposed body.
    Returns: blast_radius, patch_locality, token_cost. Use before edit_function_body to check cost."""
    try:
        result = core.measure_edit(file_path, function_name, new_body)
    except Exception as exc:
        return str(exc)
    if not result.success:
        return result.error or "unknown error"
    lines = [f"Dry-run metrics for '{function_name}':"]
    if result.blast_radius is not None:
        lines.append(f"  blast_radius:   {result.blast_radius:.2f}")
    if result.patch_locality is not None:
        lines.append(f"  patch_locality: {result.patch_locality:.2f}")
    if result.token_cost is not None:
        lines.append(f"  token_cost:     {result.token_cost}")
    return "\n".join(lines)


def install_skill() -> None:
    skill_text = (
        importlib.resources.files("tokenspace")
        .joinpath("SKILL.md")
        .read_text(encoding="utf-8")
    )
    dest = pathlib.Path(".claude") / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    already_exists = dest.exists()
    dest.write_text(skill_text, encoding="utf-8")
    if already_exists:
        print("Skill already installed — updated .claude/SKILL.md")
    else:
        print("Skill installed: .claude/SKILL.md")

    settings_path = pathlib.Path(".claude") / "settings.json"
    config: dict[str, object] = (
        json.loads(settings_path.read_text(encoding="utf-8"))
        if settings_path.exists()
        else {}
    )
    mcp_servers = config.setdefault("mcpServers", {})
    assert isinstance(mcp_servers, dict)
    if "tokenspace" not in mcp_servers:
        mcp_servers["tokenspace"] = {"command": "tokenspace", "args": []}
        settings_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        print("MCP server registered: .claude/settings.json")
    else:
        print("MCP server already registered — skipping")
    print("Restart Claude Code to activate Tokenspace.")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("--help", "-h"):
        print(
            "tokenspace-mcp — Surgical AST-based Python editing for AI agents\n"
            "\n"
            "Commands:\n"
            "  tokenspace               Start the MCP server (connect via Claude Code)\n"
            "  tokenspace install-skill Install the Claude Code skill and MCP config\n"
            "\n"
            "Tools exposed via MCP:\n"
            "  read_structure(file_path)\n"
            "  edit_function_body(file_path, function_name, new_body)\n"
            "  edit_class_method(file_path, class_name, method_name, new_body)\n"
            "  measure_edit(file_path, function_name, new_body)\n"
            "\n"
            "Docs: https://github.com/VanshMomaya7/tokenspace\n"
        )
        return
    if len(sys.argv) > 1 and sys.argv[1] == "install-skill":
        install_skill()
    else:
        mcp.run()


if __name__ == "__main__":
    main()
