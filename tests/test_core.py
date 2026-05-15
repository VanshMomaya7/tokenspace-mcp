from __future__ import annotations

import libcst as cst
import pytest

from tokenspace.core import edit_class_method, edit_function_body, find_symbol, read_structure
from tokenspace.types import EditResult


# ── find_symbol ───────────────────────────────────────────────────────────────


def test_find_symbol_sync() -> None:
    tree = cst.parse_module("def foo():\n    pass\n")
    result = find_symbol(tree, "foo")
    assert isinstance(result, cst.FunctionDef)
    assert result.name.value == "foo"


def test_find_symbol_not_found() -> None:
    tree = cst.parse_module("def foo():\n    pass\n")
    assert find_symbol(tree, "bar") is None


def test_find_symbol_async() -> None:
    tree = cst.parse_module("async def foo():\n    pass\n")
    result = find_symbol(tree, "foo")
    assert isinstance(result, cst.FunctionDef)
    assert result.asynchronous is not None


def test_find_symbol_decorated() -> None:
    tree = cst.parse_module("@decorator\ndef foo():\n    pass\n")
    result = find_symbol(tree, "foo")
    assert isinstance(result, cst.FunctionDef)
    assert result.name.value == "foo"


def test_find_symbol_ignores_class_method() -> None:
    tree = cst.parse_module("class Bar:\n    def foo(self):\n        pass\n")
    assert find_symbol(tree, "foo") is None


# ── edit_function_body ────────────────────────────────────────────────────────


def test_edit_function_body_success(tmp_path: pytest.TempPathFactory) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")  # type: ignore[union-attr]
    result = edit_function_body(str(f), "foo", "    return 42\n")
    assert result.success is True
    assert result.syntax_valid is True
    assert result.error is None
    assert result.diff != ""
    assert "return 42" in f.read_text(encoding="utf-8")  # type: ignore[union-attr]


def test_edit_function_body_not_found(tmp_path: pytest.TempPathFactory) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")  # type: ignore[union-attr]
    result = edit_function_body(str(f), "missing", "    pass\n")
    assert result.success is False
    assert result.error is not None
    assert "missing" in result.error
    assert f.read_text(encoding="utf-8") == "def foo():\n    return 1\n"  # type: ignore[union-attr]


def test_edit_function_body_async(tmp_path: pytest.TempPathFactory) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text("async def fetch():\n    return 1\n", encoding="utf-8")  # type: ignore[union-attr]
    result = edit_function_body(str(f), "fetch", "    return 2\n")
    assert result.success is True
    text = f.read_text(encoding="utf-8")  # type: ignore[union-attr]
    assert "async def fetch()" in text
    assert "return 2" in text


def test_edit_function_body_single_decorator(tmp_path: pytest.TempPathFactory) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text("@property\ndef answer():\n    return 42\n", encoding="utf-8")  # type: ignore[union-attr]
    result = edit_function_body(str(f), "answer", "    return 43\n")
    assert result.success is True
    text = f.read_text(encoding="utf-8")  # type: ignore[union-attr]
    assert "@property" in text
    assert "return 43" in text


def test_edit_function_body_multiple_decorators(tmp_path: pytest.TempPathFactory) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text(
        "def _noop(fn):\n    return fn\n\n\n@_noop\n@_noop\ndef doubled():\n    return 1\n",
        encoding="utf-8",
    )  # type: ignore[union-attr]
    result = edit_function_body(str(f), "doubled", "    return 2\n")
    assert result.success is True
    text = f.read_text(encoding="utf-8")  # type: ignore[union-attr]
    assert "@_noop\n@_noop" in text
    assert "return 2" in text


def test_edit_function_body_class_method_returns_error(
    tmp_path: pytest.TempPathFactory,
) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text("class Bar:\n    def foo(self):\n        return 1\n", encoding="utf-8")  # type: ignore[union-attr]
    result = edit_function_body(str(f), "foo", "    return 2\n")
    assert result.success is False
    assert result.error is not None


def test_edit_function_body_syntax_error_no_write(
    tmp_path: pytest.TempPathFactory,
) -> None:
    original = "def foo():\n    return 1\n"
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text(original, encoding="utf-8")  # type: ignore[union-attr]
    result = edit_function_body(str(f), "foo", "    return 1 +\n")
    assert result.success is False
    assert result.syntax_valid is False
    assert f.read_text(encoding="utf-8") == original  # type: ignore[union-attr]


def test_edit_function_body_preserves_signature(tmp_path: pytest.TempPathFactory) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text("def variadic(*args: int, **kwargs: str) -> str:\n    return 'a'\n", encoding="utf-8")  # type: ignore[union-attr]
    result = edit_function_body(str(f), "variadic", "    return 'b'\n")
    assert result.success is True
    after = f.read_text(encoding="utf-8")  # type: ignore[union-attr]
    assert "def variadic(*args: int, **kwargs: str) -> str:" in after
    assert "return 'b'" in after


def test_edit_function_body_metrics_populated_on_success(
    tmp_path: pytest.TempPathFactory,
) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text("def foo():\n    return 1\n", encoding="utf-8")  # type: ignore[union-attr]
    result = edit_function_body(str(f), "foo", "    return 2\n")
    assert result.success is True
    assert result.blast_radius == 0.0  # body change only, signature unchanged
    assert result.patch_locality is not None
    assert 0.0 <= result.patch_locality <= 1.0
    assert result.token_cost is not None
    assert result.token_cost > 0


# ── edit_class_method ─────────────────────────────────────────────────────────


def test_edit_class_method_success(tmp_path: pytest.TempPathFactory) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text("class Foo:\n    def bar(self):\n        return 1\n", encoding="utf-8")  # type: ignore[union-attr]
    result = edit_class_method(str(f), "Foo", "bar", "    return 42\n")
    assert result.success is True
    assert result.syntax_valid is True
    assert result.error is None
    assert "return 42" in f.read_text(encoding="utf-8")  # type: ignore[union-attr]


def test_edit_class_method_class_not_found(tmp_path: pytest.TempPathFactory) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text("class Foo:\n    def bar(self):\n        return 1\n", encoding="utf-8")  # type: ignore[union-attr]
    result = edit_class_method(str(f), "Baz", "bar", "    return 42\n")
    assert result.success is False
    assert result.error is not None
    assert "Baz" in result.error


def test_edit_class_method_method_not_found(tmp_path: pytest.TempPathFactory) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text("class Foo:\n    def bar(self):\n        return 1\n", encoding="utf-8")  # type: ignore[union-attr]
    result = edit_class_method(str(f), "Foo", "baz", "    return 42\n")
    assert result.success is False
    assert result.error is not None
    assert "baz" in result.error


def test_edit_class_method_disambiguation(tmp_path: pytest.TempPathFactory) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    src = (
        "class A:\n    def method(self):\n        return 1\n\n\n"
        "class B:\n    def method(self):\n        return 2\n"
    )
    f.write_text(src, encoding="utf-8")  # type: ignore[union-attr]
    result = edit_class_method(str(f), "B", "method", "    return 99\n")
    assert result.success is True
    text = f.read_text(encoding="utf-8")  # type: ignore[union-attr]
    assert "return 1" in text
    assert "return 99" in text
    assert "return 2" not in text


def test_edit_class_method_async_method(tmp_path: pytest.TempPathFactory) -> None:
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text("class Foo:\n    async def bar(self):\n        return 1\n", encoding="utf-8")  # type: ignore[union-attr]
    result = edit_class_method(str(f), "Foo", "bar", "    return 99\n")
    assert result.success is True
    text = f.read_text(encoding="utf-8")  # type: ignore[union-attr]
    assert "return 99" in text
    assert "async def bar" in text


def test_edit_class_method_syntax_error_no_write(
    tmp_path: pytest.TempPathFactory,
) -> None:
    original = "class Foo:\n    def bar(self):\n        return 1\n"
    f = tmp_path / "mod.py"  # type: ignore[operator]
    f.write_text(original, encoding="utf-8")  # type: ignore[union-attr]
    result = edit_class_method(str(f), "Foo", "bar", "    !!invalid!!\n")
    assert result.success is False
    assert result.syntax_valid is False
    assert f.read_text(encoding="utf-8") == original  # type: ignore[union-attr]
