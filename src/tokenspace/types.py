from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EditResult:
    success: bool
    syntax_valid: bool
    diff: str                    # unified diff, empty string if no change
    error: str | None            # None on success
    blast_radius: float | None   # fraction of file's symbols whose sig changed
    patch_locality: float | None  # 1 - (changed_line_range / total_lines)
    token_cost: int | None       # tiktoken count: input_tokens + output_tokens


def format_result(result: EditResult) -> str:
    if not result.success:
        error = result.error or "unknown error"
        return f"Edit failed: {error}"

    lines = ["Edit successful"]

    if result.blast_radius is not None:
        percent = round(result.blast_radius * 100)
        lines.append(
            f"  Blast radius:   {result.blast_radius:.2f}  "
            f"({percent}% of symbols affected)"
        )

    if result.patch_locality is not None:
        if result.patch_locality >= 0.90:
            note = "edit is well-contained"
        elif result.patch_locality >= 0.50:
            note = "edit is moderately contained"
        else:
            note = "edit is broad"
        lines.append(f"  Patch locality: {result.patch_locality:.2f}  ({note})")

    if result.token_cost is not None:
        token_word = "token" if result.token_cost == 1 else "tokens"
        lines.append(f"  Token cost:     {result.token_cost} {token_word}")

    diff_lines = len(result.diff.splitlines())
    line_word = "line" if diff_lines == 1 else "lines"
    lines.append(f"  Diff: {diff_lines} {line_word} changed")

    return "\n".join(lines)
