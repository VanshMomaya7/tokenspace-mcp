"""Benchmark harness: str_replace vs tokenspace vs measure_edit on 10 fixture files."""
from __future__ import annotations

import csv
import pathlib
import sys
import tempfile
from dataclasses import asdict, dataclass

import libcst as cst
import tiktoken
from libcst.metadata import MetadataWrapper, PositionProvider

from tokenspace.core import edit_class_method, edit_function_body, measure_edit, read_structure

TASKS_DIR = pathlib.Path(__file__).parent / "tasks"
RESULTS_DIR = pathlib.Path(__file__).parent / "results"
RESULTS_CSV = RESULTS_DIR / "benchmark.csv"

_enc = tiktoken.get_encoding("cl100k_base")


# ── data types ────────────────────────────────────────────────────────────────


@dataclass
class MultiEditRow:
    file: str
    n_edits: int
    str_replace_tokens: int
    tokenspace_tokens: int
    reduction_pct: float


@dataclass
class Symbol:
    fn_name: str
    class_name: str | None  # None = top-level function
    start_line: int
    body_start_line: int  # first line inside the IndentedBlock (after the signature)
    end_line: int


@dataclass
class Row:
    file: str
    function: str
    approach: str
    success: bool
    input_tokens: int
    output_tokens: int
    total_tokens: int
    blast_radius: float | None
    patch_locality: float | None
    error: str | None


# ── helpers ───────────────────────────────────────────────────────────────────


def _t(text: str) -> int:
    return len(_enc.encode(text))


def _label(sym: Symbol) -> str:
    return f"{sym.class_name}.{sym.fn_name}" if sym.class_name else sym.fn_name


def collect_symbols(path: pathlib.Path) -> list[Symbol]:
    source = path.read_text(encoding="utf-8")
    tree = cst.parse_module(source)
    wrapper = MetadataWrapper(tree)
    positions = wrapper.resolve(PositionProvider)
    syms: list[Symbol] = []
    for stmt in wrapper.module.body:
        if isinstance(stmt, cst.FunctionDef):
            rng = positions[stmt]
            body_rng = positions[stmt.body]
            syms.append(
                Symbol(stmt.name.value, None, rng.start.line, body_rng.start.line, rng.end.line)
            )
        elif isinstance(stmt, cst.ClassDef):
            for item in stmt.body.body:
                if isinstance(item, cst.FunctionDef):
                    rng = positions[item]
                    body_rng = positions[item.body]
                    syms.append(
                        Symbol(
                            item.name.value,
                            stmt.name.value,
                            rng.start.line,
                            body_rng.start.line,
                            rng.end.line,
                        )
                    )
    return syms


def extract_texts(source: str, sym: Symbol) -> tuple[str, str]:
    """Return (full_fn_text, body_only) using exact line numbers from libcst."""
    lines = source.splitlines(keepends=True)
    full_fn_text = "".join(lines[sym.start_line - 1 : sym.end_line])
    body_text = "".join(lines[sym.body_start_line - 1 : sym.end_line])
    return full_fn_text, body_text


def make_new_body(body_text: str) -> str:
    """Prepend a no-op statement so the body is visibly different."""
    indent = "    "
    for line in body_text.splitlines():
        if line.strip():
            indent = " " * (len(line) - len(line.lstrip()))
            break
    return f"{indent}_ = None\n" + body_text


# ── per-approach runners ──────────────────────────────────────────────────────


def run_str_replace(
    source: str, sym: Symbol, full_fn_text: str, body_text: str, new_body: str
) -> Row:
    # Replace only the body portion within the full function text
    new_full = full_fn_text.replace(body_text, new_body, 1)
    new_source = source.replace(full_fn_text, new_full, 1)
    success = (full_fn_text in source) and (new_source != source)

    # Each component tokenised separately — models receive them as distinct inputs
    input_t = _t(source) + _t(body_text) + _t(new_body)
    output_t = _t(new_source)
    return Row(
        file="",
        function=_label(sym),
        approach="str_replace",
        success=success,
        input_tokens=input_t,
        output_tokens=output_t,
        total_tokens=input_t + output_t,
        blast_radius=None,
        patch_locality=None,
        error=None if success else "replacement string not found",
    )


def run_tokenspace(source: str, sym: Symbol, new_body: str) -> Row:
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(source)
        tmp_path = tmp.name

    try:
        if sym.class_name:
            result = edit_class_method(tmp_path, sym.class_name, sym.fn_name, new_body)
        else:
            result = edit_function_body(tmp_path, sym.fn_name, new_body)
    finally:
        pathlib.Path(tmp_path).unlink(missing_ok=True)

    if not result.success:
        return Row(
            file="",
            function=_label(sym),
            approach="tokenspace",
            success=False,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            blast_radius=None,
            patch_locality=None,
            error=result.error,
        )

    diff_t = _t(result.diff)
    # token_cost = _t(source + fn_name + new_body) + _t(diff)
    total_t = result.token_cost or 0
    input_t = total_t - diff_t
    return Row(
        file="",
        function=_label(sym),
        approach="tokenspace",
        success=True,
        input_tokens=max(0, input_t),
        output_tokens=diff_t,
        total_tokens=total_t,
        blast_radius=result.blast_radius,
        patch_locality=result.patch_locality,
        error=None,
    )


def run_measure(path: pathlib.Path, source: str, sym: Symbol, new_body: str) -> Row:
    # measure_edit only supports top-level functions
    if sym.class_name is not None:
        return Row(
            file="",
            function=_label(sym),
            approach="measure_edit",
            success=False,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            blast_radius=None,
            patch_locality=None,
            error="measure_edit: class methods not supported",
        )

    result = measure_edit(str(path), sym.fn_name, new_body)
    if not result.success:
        return Row(
            file="",
            function=_label(sym),
            approach="measure_edit",
            success=False,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            blast_radius=None,
            patch_locality=None,
            error=result.error,
        )

    diff_t = _t(result.diff)
    total_t = result.token_cost or 0
    input_t = total_t - diff_t
    return Row(
        file="",
        function=_label(sym),
        approach="measure_edit",
        success=True,
        input_tokens=max(0, input_t),
        output_tokens=diff_t,
        total_tokens=total_t,
        blast_radius=result.blast_radius,
        patch_locality=result.patch_locality,
        error=None,
    )


# ── multi-edit scenario ───────────────────────────────────────────────────────


def multi_edit_stats(
    path: pathlib.Path, source: str, symbols: list[Symbol], n: int = 5
) -> MultiEditRow:
    """Cost of n sequential edits: str_replace pays full file each time; tokenspace pays structure once."""
    selected = symbols[:n]
    struct_tokens = _t(read_structure(str(path)))

    str_replace_total = 0
    tokenspace_edit_total = 0
    for sym in selected:
        _, body_text = extract_texts(source, sym)
        new_body = make_new_body(body_text)
        fn_id = f"{sym.class_name}.{sym.fn_name}" if sym.class_name else sym.fn_name

        str_replace_total += _t(source) + _t(body_text) + _t(new_body)
        tokenspace_edit_total += _t(fn_id) + _t(new_body)

    tokenspace_total = struct_tokens + tokenspace_edit_total
    reduction = 100.0 * (str_replace_total - tokenspace_total) / str_replace_total if str_replace_total else 0.0
    return MultiEditRow(
        file=path.name,
        n_edits=len(selected),
        str_replace_tokens=str_replace_total,
        tokenspace_tokens=tokenspace_total,
        reduction_pct=reduction,
    )


def print_multi_edit_summary(multi_rows: list[MultiEditRow]) -> None:
    n = multi_rows[0].n_edits if multi_rows else 5
    col_w = 28
    header = (
        f"{'Multi-edit (' + str(n) + ' edits / file)':<{col_w}}| "
        f"{'str_replace total':>18} | {'tokenspace total':>14} | {'Reduction':>10}"
    )
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)
    avg_sr = sum(r.str_replace_tokens for r in multi_rows) / len(multi_rows)
    avg_sc = sum(r.tokenspace_tokens for r in multi_rows) / len(multi_rows)
    avg_red = sum(r.reduction_pct for r in multi_rows) / len(multi_rows)
    print(
        f"{'avg across ' + str(len(multi_rows)) + ' files':<{col_w}}| "
        f"{avg_sr:>18.0f} | {avg_sc:>14.0f} | {avg_red:>9.1f}%"
    )
    print(sep)


# ── summary printer ───────────────────────────────────────────────────────────


def print_summary(rows: list[Row]) -> None:
    approaches = ["str_replace", "tokenspace", "measure_edit"]
    col_w = 18

    header = (
        f"{'Approach':<{col_w}}| {'Avg Input Tokens':>17} | "
        f"{'Avg Total Tokens':>17} | {'Success Rate':>12}"
    )
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    avgs: dict[str, tuple[float, float]] = {}
    for approach in approaches:
        subset = [r for r in rows if r.approach == approach]
        if not subset:
            continue
        success_count = sum(1 for r in subset if r.success)
        successful = [r for r in subset if r.success]
        avg_in = sum(r.input_tokens for r in successful) / len(successful) if successful else 0.0
        avg_total = sum(r.total_tokens for r in successful) / len(successful) if successful else 0.0
        rate = f"{100 * success_count // len(subset)}%"
        print(
            f"{approach:<{col_w}}| {avg_in:>17.0f} | {avg_total:>17.0f} | {rate:>12}"
        )
        avgs[approach] = (avg_in, avg_total)

    print(sep)

    if "str_replace" in avgs and "tokenspace" in avgs:
        sr_total = avgs["str_replace"][1]
        sc_total = avgs["tokenspace"][1]
        if sr_total > 0:
            reduction = 100.0 * (sr_total - sc_total) / sr_total
            print(f"Token reduction (tokenspace vs str_replace):  {reduction:.1f}%")

    print(sep)


# ── main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    task_files = sorted(TASKS_DIR.glob("*.py"))
    if not task_files:
        print("No task files found in", TASKS_DIR, file=sys.stderr)
        sys.exit(1)

    # Fix 2: print read_structure token count (compact format) vs full file
    rep = task_files[0]
    rep_source = rep.read_text(encoding="utf-8")
    struct_out = read_structure(str(rep))
    full_t = _t(rep_source)
    struct_t = _t(struct_out)
    print(f"\nread_structure token comparison ({rep.name}):")
    print(f"  full file content:  {full_t:>5} tokens")
    print(f"  read_structure out: {struct_t:>5} tokens  ({full_t / struct_t:.1f}x reduction)")

    all_rows: list[Row] = []
    multi_rows: list[MultiEditRow] = []

    for task_path in task_files:
        source = task_path.read_text(encoding="utf-8")
        symbols = collect_symbols(task_path)
        file_label = task_path.name

        for sym in symbols:
            full_fn_text, body_text = extract_texts(source, sym)
            new_body = make_new_body(body_text)

            for row in (
                run_str_replace(source, sym, full_fn_text, body_text, new_body),
                run_tokenspace(source, sym, new_body),
                run_measure(task_path, source, sym, new_body),
            ):
                row.file = file_label
                all_rows.append(row)

        multi_rows.append(multi_edit_stats(task_path, source, symbols))

    # Write CSV
    fieldnames = [f.name for f in Row.__dataclass_fields__.values()]  # type: ignore[attr-defined]
    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in all_rows:
            writer.writerow(asdict(row))

    print(f"\nResults written to: {RESULTS_CSV}")
    total_fns = len(all_rows) // 3
    print(f"Benchmarked {len(task_files)} files, {total_fns} functions/methods\n")
    print_summary(all_rows)
    print()
    print_multi_edit_summary(multi_rows)


if __name__ == "__main__":
    main()
