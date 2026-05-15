"""Benchmark harness: real OSS Python files from popular open-source repos.

Step 1: Download → benchmarks/tasks/real/
Step 2: libcst round-trip verification (skip failures)
Step 3: Benchmark (str_replace vs tokenspace vs measure_edit)
        - Skip functions whose body has < 3 non-empty, non-comment lines
        - Skip functions where libcst/tokenspace raises a parse error
Step 4: Summary table + CSV at benchmarks/results/benchmark_real.csv
"""
from __future__ import annotations

import csv
import pathlib
import sys
import urllib.error
import urllib.request
from dataclasses import asdict

import libcst as cst

# Add benchmarks/ to path so we can import shared utilities from harness.py.
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from harness import (  # noqa: E402
    MultiEditRow,
    Row,
    Symbol,
    _label,
    collect_symbols,
    extract_texts,
    make_new_body,
    multi_edit_stats,
    print_multi_edit_summary,
    print_summary,
    run_measure,
    run_tokenspace,
    run_str_replace,
)

REAL_DIR = pathlib.Path(__file__).parent / "tasks" / "real"
RESULTS_DIR = pathlib.Path(__file__).parent / "results"
RESULTS_CSV = RESULTS_DIR / "benchmark_real.csv"

# (local filename, primary URL, fallback URL or None)
TARGETS: list[tuple[str, str, str | None]] = [
    (
        "requests_auth.py",
        "https://raw.githubusercontent.com/psf/requests/main/src/requests/auth.py",
        None,
    ),
    (
        "requests_utils.py",
        "https://raw.githubusercontent.com/psf/requests/main/src/requests/utils.py",
        None,
    ),
    (
        "flask_helpers.py",
        "https://raw.githubusercontent.com/pallets/flask/main/src/flask/helpers.py",
        None,
    ),
    (
        "fastapi_routing.py",
        "https://raw.githubusercontent.com/tiangolo/fastapi/master/fastapi/routing.py",
        None,
    ),
    (
        "django_text.py",
        "https://raw.githubusercontent.com/django/django/main/django/utils/text.py",
        None,
    ),
    (
        "httpx_auth.py",
        "https://raw.githubusercontent.com/encode/httpx/master/httpx/_auth.py",
        None,
    ),
    (
        "pydantic_main.py",
        "https://raw.githubusercontent.com/pydantic/pydantic/main/pydantic/main.py",
        "https://raw.githubusercontent.com/pydantic/pydantic/main/pydantic/functional_validators.py",
    ),
    (
        "rich_progress.py",
        "https://raw.githubusercontent.com/Textualize/rich/master/rich/progress.py",
        None,
    ),
    (
        "black_linegen.py",
        "https://raw.githubusercontent.com/psf/black/main/src/black/linegen.py",
        None,
    ),
    (
        "click_core.py",
        "https://raw.githubusercontent.com/pallets/click/main/src/click/core.py",
        None,
    ),
]

_PARSE_ERROR_KEYWORDS = ("parse", "libcst", "syntax", "invalid", "unexpected")


def download_files() -> list[pathlib.Path]:
    REAL_DIR.mkdir(parents=True, exist_ok=True)
    downloaded: list[pathlib.Path] = []
    for local_name, primary_url, fallback_url in TARGETS:
        dest = REAL_DIR / local_name
        urls: list[str] = [primary_url] + ([fallback_url] if fallback_url else [])
        ok = False
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=20) as resp:
                    dest.write_bytes(resp.read())
                print(f"  OK  {local_name}  ({url})")
                ok = True
                break
            except urllib.error.HTTPError as exc:
                print(f"  --  {url}  (HTTP {exc.code})")
            except Exception as exc:
                print(f"  --  {url}  ({exc})")
        if not ok:
            print(f"  FAIL {local_name}: all URLs failed, skipping")
        else:
            downloaded.append(dest)
    return downloaded


def verify_roundtrip(paths: list[pathlib.Path]) -> list[pathlib.Path]:
    good: list[pathlib.Path] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        try:
            if cst.parse_module(source).code == source:
                print(f"  OK  {path.name}  ({source.count(chr(10))} lines)")
                good.append(path)
            else:
                print(f"  FAIL  {path.name}  (round-trip mismatch)")
        except Exception as exc:
            print(f"  FAIL  {path.name}  ({exc})")
    return good


def _body_nontrivial(body_text: str) -> bool:
    """True if body has at least 3 non-empty, non-comment lines."""
    count = sum(
        1
        for ln in body_text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    )
    return count >= 3


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("\n-- Step 1: Downloading files ------------------------------------------")
    downloaded = download_files()
    if not downloaded:
        print("No files downloaded.", file=sys.stderr)
        sys.exit(1)

    print(f"\n-- Step 2: Round-trip check ({len(downloaded)} files) -----------------")
    good_files = verify_roundtrip(downloaded)
    if not good_files:
        print("No files passed round-trip.", file=sys.stderr)
        sys.exit(1)

    print(f"\n-- Step 3: Benchmarking ({len(good_files)} files) ---------------------")
    all_rows: list[Row] = []
    multi_rows: list[MultiEditRow] = []
    per_file: list[tuple[str, int, int, int, int]] = []  # name, total, n_short, n_err, n_bench

    for task_path in good_files:
        source = task_path.read_text(encoding="utf-8")
        symbols = collect_symbols(task_path)
        label = task_path.name
        n_short = n_err = n_bench = 0

        eligible: list[Symbol] = []
        for sym in symbols:
            _, body_text = extract_texts(source, sym)
            if not _body_nontrivial(body_text):
                n_short += 1
                continue
            eligible.append(sym)

        for sym in eligible:
            full_fn_text, body_text = extract_texts(source, sym)
            new_body = make_new_body(body_text)

            tokenspace_row = run_tokenspace(source, sym, new_body)
            if not tokenspace_row.success:
                err_msg = (tokenspace_row.error or "").lower()
                if any(kw in err_msg for kw in _PARSE_ERROR_KEYWORDS):
                    print(f"  skip {label}:{_label(sym)} - {tokenspace_row.error}")
                    n_err += 1
                    continue

            for row in (
                run_str_replace(source, sym, full_fn_text, body_text, new_body),
                tokenspace_row,
                run_measure(task_path, source, sym, new_body),
            ):
                row.file = label
                all_rows.append(row)
            n_bench += 1

        per_file.append((label, len(symbols), n_short, n_err, n_bench))
        if eligible:
            multi_rows.append(multi_edit_stats(task_path, source, eligible))

    col = 30
    print(f"\n  {'File':<{col}} | Total | Short | Err | Bench")
    print("  " + "-" * (col + 34))
    for fname, tot, ns, ne, nb in per_file:
        print(f"  {fname:<{col}} | {tot:>5} | {ns:>5} | {ne:>3} | {nb:>5}")

    with RESULTS_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(Row.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in all_rows:
            writer.writerow(asdict(row))

    benchmarked_fns = sum(r[4] for r in per_file)
    print(f"\nResults written to: {RESULTS_CSV}")
    print(f"Benchmarked {len(good_files)} files, {benchmarked_fns} functions/methods\n")

    print("\n-- Step 4: Summary ----------------------------------------------------")
    print_summary(all_rows)
    print()
    if multi_rows:
        print_multi_edit_summary(multi_rows)


if __name__ == "__main__":
    main()
