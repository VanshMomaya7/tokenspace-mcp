from __future__ import annotations

import pytest

from scalpel.measure import blast_radius, patch_locality, token_cost

import difflib


def _unified_diff(before: str, after: str, relpath: str = "mod.py") -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{relpath}",
            tofile=f"b/{relpath}",
        )
    )


def test_blast_radius_only_classes_no_top_level_functions(tmp_path) -> None:
    path = tmp_path / "only_classes.py"
    source = (
        "class Box:\n"
        "    def size(self) -> int:\n"
        "        return 1\n"
    )
    path.write_text(source, encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    after = (
        "class Box:\n"
        "    def size(self) -> int:\n"
        "        return 2\n"
    )
    assert blast_radius(before, after) == 0.0


def test_blast_radius_method_signature_change_same_name_detected(tmp_path) -> None:
    path = tmp_path / "sig.py"
    before = (
        "class C:\n"
        "    def m(self) -> None:\n"
        "        return None\n"
    )
    after = (
        "class C:\n"
        "    def m(self, x: int) -> int:\n"
        "        return x\n"
    )
    path.write_text(before, encoding="utf-8")
    assert blast_radius(before, after) > 0.0


def test_blast_radius_adding_method_increases_vs_body_only_edit(tmp_path) -> None:
    one_method = (
        "class Widget:\n"
        "    def tick(self) -> None:\n"
        "        pass\n"
    )
    body_only = (
        "class Widget:\n"
        "    def tick(self) -> None:\n"
        "        return None\n"
    )
    two_methods = (
        "class Widget:\n"
        "    def tick(self) -> None:\n"
        "        pass\n"
        "    def tock(self) -> None:\n"
        "        pass\n"
    )
    p = tmp_path / "widget.py"
    p.write_text(one_method, encoding="utf-8")
    br_body = blast_radius(one_method, body_only)
    br_new = blast_radius(one_method, two_methods)
    assert br_new > br_body


def test_patch_locality_top_compact_vs_bottom_wide_span_differs(tmp_path) -> None:
    n = 100
    base_lines = [f"L{i}\n" for i in range(1, n + 1)]
    base = "".join(base_lines)
    (tmp_path / "base.py").write_text(base, encoding="utf-8")

    top_lines = base_lines.copy()
    top_lines[1] = "TOP_CHANGED\n"
    diff_top = _unified_diff(base, "".join(top_lines), "big.py")

    bottom_lines = base_lines.copy()
    for i in range(n - 5, n):
        bottom_lines[i] = "BOTTOM\n"
    diff_bottom = _unified_diff(base, "".join(bottom_lines), "big.py")

    loc_top = patch_locality(diff_top, n)
    loc_bottom = patch_locality(diff_bottom, n)
    assert loc_top > loc_bottom


def test_patch_locality_multiline_change_middle_of_large_file(tmp_path) -> None:
    n = 80
    lines = [f"row_{i}\n" for i in range(n)]
    base = "".join(lines)
    (tmp_path / "grid_base.py").write_text(base, encoding="utf-8")

    changed = lines.copy()
    for i in range(35, 42):
        changed[i] = "BLOCK\n"
    diff_mid = _unified_diff(base, "".join(changed), "grid.py")
    loc = patch_locality(diff_mid, n)
    assert 0.0 <= loc < 1.0
    single = lines.copy()
    single[40] = "ONE\n"
    loc_one = patch_locality(_unified_diff(base, "".join(single), "grid.py"), n)
    assert loc < loc_one


def test_token_cost_empty_strings() -> None:
    cost = token_cost("", "")
    assert cost == 0


def test_token_cost_large_input_no_crash(tmp_path) -> None:
    path = tmp_path / "blob.txt"
    big = "z" * 10_000
    path.write_text(big, encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    cost = token_cost(text, "---\n+++")
    assert isinstance(cost, int)
    assert cost > 0


# ── blast_radius: required cases ──────────────────────────────────────────────


def test_blast_radius_no_change() -> None:
    src = "def foo(x: int) -> str:\n    return ''\n"
    assert blast_radius(src, src) == 0.0


def test_blast_radius_rename_function() -> None:
    before = "def foo() -> None:\n    pass\n"
    after = "def bar() -> None:\n    pass\n"
    assert blast_radius(before, after) == 1.0


def test_blast_radius_add_function() -> None:
    before = "def foo() -> None:\n    pass\n"
    after = before + "\n\ndef bar() -> None:\n    pass\n"
    result = blast_radius(before, after)
    assert 0.0 < result <= 1.0


def test_blast_radius_body_only_change() -> None:
    before = "def foo() -> None:\n    x = 1\n"
    after = "def foo() -> None:\n    x = 2\n"
    assert blast_radius(before, after) == 0.0


# ── patch_locality: required cases ────────────────────────────────────────────


def test_patch_locality_empty_diff() -> None:
    assert patch_locality("", 100) == 1.0


def test_patch_locality_single_line_near_one() -> None:
    lines = [f"x = {i}\n" for i in range(50)]
    before = "".join(lines)
    lines[25] = "x = 999\n"
    after = "".join(lines)
    result = patch_locality(_unified_diff(before, after), 50)
    assert result > 0.9


def test_patch_locality_whole_file_near_zero() -> None:
    before = "a = 1\nb = 2\nc = 3\n"
    after = "a = 9\nb = 9\nc = 9\n"
    result = patch_locality(_unified_diff(before, after), 3)
    assert result <= 0.1


# ── token_cost: required cases ────────────────────────────────────────────────


def test_token_cost_returns_int() -> None:
    assert isinstance(token_cost("hello", "diff"), int)


def test_token_cost_positive() -> None:
    assert token_cost("hello", "diff") > 0
