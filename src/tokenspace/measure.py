"""Metrics: blast_radius, patch_locality, token_cost."""
from __future__ import annotations

import re
import libcst as cst
import tiktoken

__all__ = ["blast_radius", "patch_locality", "token_cost"]


def _stub_class(cls: cst.ClassDef) -> cst.ClassDef:
    return cls.with_changes(
        body=cst.IndentedBlock([cst.SimpleStatementLine([cst.Pass()])])
    )


def _function_sig_blob(fn: cst.FunctionDef) -> str:
    stub = fn.with_changes(
        body=cst.IndentedBlock([cst.SimpleStatementLine([cst.Pass()])])
    )
    return cst.Module(body=[stub]).code.rstrip()


def _class_sig_blob(cls: cst.ClassDef) -> str:
    stub = _stub_class(cls)
    return cst.Module(body=[stub]).code.rstrip()


def _collect_signatures(tree: cst.Module) -> set[str]:
    sigs: set[str] = set()

    def walk_class(cls: cst.ClassDef, prefix: str) -> None:
        sigs.add(f"class:{prefix}{cls.name.value}|{_class_sig_blob(cls)}")
        for item in cls.body.body:
            if isinstance(item, cst.FunctionDef):
                q = f"{prefix}{cls.name.value}.{item.name.value}"
                sigs.add(f"fn:{q}|{_function_sig_blob(item)}")
            elif isinstance(item, cst.ClassDef):
                walk_class(item, f"{prefix}{cls.name.value}.")

    for stmt in tree.body:
        if isinstance(stmt, cst.FunctionDef):
            q = stmt.name.value
            sigs.add(f"fn:{q}|{_function_sig_blob(stmt)}")
        elif isinstance(stmt, cst.ClassDef):
            walk_class(stmt, "")

    return sigs


def blast_radius(source_before: str, source_after: str) -> float:
    before_s = _collect_signatures(cst.parse_module(source_before))
    after_s = _collect_signatures(cst.parse_module(source_after))
    sym = before_s ^ after_s
    union = before_s | after_s
    if not union:
        return 0.0
    return len(sym) / len(union)


def patch_locality(diff: str, total_lines_after: int) -> float:
    if total_lines_after <= 0:
        return 1.0
    if not diff.strip():
        return 1.0

    changed: list[int] = []
    new_line = 0
    i = 0
    lines = diff.splitlines()

    while i < len(lines):
        line = lines[i]
        if line.startswith("+++ ") or line.startswith("--- "):
            i += 1
            continue
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            new_line = int(m.group(3))
            i += 1
            while i < len(lines) and not lines[i].startswith("@@"):
                dl = lines[i]
                if dl.startswith("\\"):
                    i += 1
                    continue
                if not dl:
                    i += 1
                    continue
                prefix = dl[0]
                if prefix == " ":
                    new_line += 1
                elif prefix == "-":
                    pass
                elif prefix == "+":
                    changed.append(new_line)
                    new_line += 1
                i += 1
            continue
        i += 1

    if not changed:
        return 1.0
    span = max(changed) - min(changed) + 1
    return 1.0 - (span / total_lines_after)


def token_cost(input_text: str, diff_output: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(input_text)) + len(enc.encode(diff_output))
