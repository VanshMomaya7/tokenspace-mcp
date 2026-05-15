# tokenspace-mcp

Surgical AST-based Python editing for AI agents — edit by symbol name, not text position. Built-in blast radius and token cost on every edit.

```bash
pip install tokenspace-mcp
```

## Why

AI coding agents (Claude Code, Cursor, Aider) edit Python via string replacement or line numbers. This forces the agent to echo the old code to locate the edit, then echo the entire new file as output. On large files that wastes thousands of tokens per edit.

Tokenspace exposes four MCP tools that operate on symbol names:

```
edit_function_body("auth.py", "validate_token", new_body)
```

No echoing. No stale line numbers. Every edit returns a diff, a blast radius score, and a token cost — automatically.

## Benchmark

Measured on **406 real functions** across 10 popular OSS projects (requests, flask, fastapi, django, httpx, pydantic, black, click, rich). All files verified with libcst round-trip.

| Scenario | str\_replace | Tokenspace | Reduction |
|---|---|---|---|
| Single edit — 406 functions total | 36,907 tokens | 18,674 tokens | **49.4%** |
| 5 edits / same file — 10 files total | 70,948 tokens | 2,039 tokens | **95.4%** |

The multi-edit gap is large because `str_replace` pays the full file on every call. Tokenspace pays for `read_structure` once and only the function name + new body per subsequent edit.

## MCP Tools

| Tool | What it does |
|---|---|
| `read_structure` | File skeleton — signatures and line ranges, no bodies. ~3.4× cheaper than reading the file. |
| `edit_function_body` | Replace a top-level function body by name. Writes to disk. Returns diff + metrics. |
| `edit_class_method` | Replace a class method body by name. Writes to disk. Returns diff + metrics. |
| `measure_edit` | Dry-run: compute blast radius and token cost without writing. |

### Metrics returned on every edit

- **blast_radius** — fraction of the file's symbols whose signature changed (0.0 = nothing changed structurally)
- **patch_locality** — how contained the edit is (1.0 = perfectly local)
- **token_cost** — tiktoken count of input + diff output

## Install

```bash
pip install tokenspace-mcp
tokenspace install-skill
```

Then restart Claude Code. Tokenspace tools will be available automatically.

The second command:
- Copies the Claude Code skill to `.claude/SKILL.md`
- Registers the MCP server in `.claude/settings.json`
- After restart, Claude Code knows when and how to use all 4 tools

## Optimal workflow

```
1. read_structure(file_path)          → locate symbols, costs ~200 tokens
2. measure_edit(file_path, fn, body)  → dry run, check blast_radius
3. edit_function_body / edit_class_method  → write if metrics look good
4. Check result: success, diff, blast_radius, patch_locality, token_cost
```

For multiple edits on the same file, call `read_structure` once and skip `measure_edit` — the multi-edit token reduction reaches 95.4%.

## Requirements

- Python ≥ 3.12
- Works with any MCP-compatible host (Claude Code, Continue, custom agents)

## License

MIT
