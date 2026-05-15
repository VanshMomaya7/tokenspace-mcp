"""libcst operations: parse, find_symbol, replace, diff. All libcst imports live here."""
from __future__ import annotations

import difflib
import pathlib
import textwrap
from typing import Optional, Union

import libcst as cst
from libcst import FlattenSentinel, RemovalSentinel
from libcst.metadata import MetadataWrapper, PositionProvider

from tokenspace.measure import blast_radius, patch_locality, token_cost
from tokenspace.types import EditResult

__all__ = [
    "find_symbol",
    "edit_function_body",
    "edit_class_method",
    "read_structure",
    "measure_edit",
]


def find_symbol(tree: cst.Module, name: str) -> Optional[cst.FunctionDef]:
    """Return the first top-level function matching name, or None."""
    for stmt in tree.body:
        if isinstance(stmt, cst.FunctionDef) and stmt.name.value == name:
            return stmt
    return None


def _parse_new_body(new_body: str) -> Optional[cst.BaseSuite]:
    """Wrap new_body in a dummy function and extract its parsed body, or None on syntax error."""
    normalized = textwrap.indent(textwrap.dedent(new_body).strip("\n"), "    ") + "\n"
    try:
        wrapper = cst.parse_statement(f"def _():\n{normalized}")
    except cst.ParserSyntaxError:
        return None
    if not isinstance(wrapper, cst.FunctionDef):
        return None
    return wrapper.body


def _make_diff(before: str, after: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


class _TopLevelFunctionReplacer(cst.CSTTransformer):
    def __init__(self, target: str, new_body: cst.BaseSuite) -> None:
        self._target = target
        self._new_body = new_body
        self._class_depth = 0
        self.replaced = False

    def visit_ClassDef(self, node: cst.ClassDef) -> Optional[bool]:
        self._class_depth += 1
        return True

    def leave_ClassDef(
        self,
        original_node: cst.ClassDef,
        updated_node: cst.ClassDef,
    ) -> Union[cst.BaseStatement, FlattenSentinel[cst.BaseStatement], RemovalSentinel]:
        self._class_depth -= 1
        return updated_node

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> Union[cst.BaseStatement, FlattenSentinel[cst.BaseStatement], RemovalSentinel]:
        if self._class_depth == 0 and updated_node.name.value == self._target:
            self.replaced = True
            return updated_node.with_changes(body=self._new_body)
        return updated_node


class _ClassMethodReplacer(cst.CSTTransformer):
    def __init__(
        self, class_name: str, method_name: str, new_body: cst.BaseSuite
    ) -> None:
        self._class_name = class_name
        self._method_name = method_name
        self._new_body = new_body
        self._class_stack: list[str] = []
        self.replaced = False

    def visit_ClassDef(self, node: cst.ClassDef) -> Optional[bool]:
        self._class_stack.append(node.name.value)
        return True

    def leave_ClassDef(
        self,
        original_node: cst.ClassDef,
        updated_node: cst.ClassDef,
    ) -> Union[cst.BaseStatement, FlattenSentinel[cst.BaseStatement], RemovalSentinel]:
        self._class_stack.pop()
        return updated_node

    def leave_FunctionDef(
        self,
        original_node: cst.FunctionDef,
        updated_node: cst.FunctionDef,
    ) -> Union[cst.BaseStatement, FlattenSentinel[cst.BaseStatement], RemovalSentinel]:
        if (
            len(self._class_stack) == 1
            and self._class_stack[0] == self._class_name
            and updated_node.name.value == self._method_name
        ):
            self.replaced = True
            return updated_node.with_changes(body=self._new_body)
        return updated_node


def _find_method(
    tree: cst.Module, class_name: str, method_name: str
) -> Optional[cst.FunctionDef]:
    for stmt in tree.body:
        if isinstance(stmt, cst.ClassDef) and stmt.name.value == class_name:
            for item in stmt.body.body:
                if isinstance(item, cst.FunctionDef) and item.name.value == method_name:
                    return item
    return None


def _file_not_found_result(file_path: str) -> EditResult:
    return EditResult(
        success=False,
        syntax_valid=False,
        diff="",
        error=f"File not found: {file_path}",
        blast_radius=None,
        patch_locality=None,
        token_cost=None,
    )


def edit_function_body(
    file_path: str, function_name: str, new_body: str
) -> EditResult:
    try:
        source = pathlib.Path(file_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return _file_not_found_result(file_path)
    tree = cst.parse_module(source)

    if find_symbol(tree, function_name) is None:
        return EditResult(
            success=False,
            syntax_valid=True,
            diff="",
            error=f"function '{function_name}' not found at top level; for class methods use edit_class_method",
            blast_radius=None,
            patch_locality=None,
            token_cost=None,
        )

    parsed_body = _parse_new_body(new_body)
    if parsed_body is None:
        return EditResult(
            success=False,
            syntax_valid=False,
            diff="",
            error="new_body has a syntax error",
            blast_radius=None,
            patch_locality=None,
            token_cost=None,
        )

    replacer = _TopLevelFunctionReplacer(function_name, parsed_body)
    new_tree = tree.visit(replacer)
    new_source = new_tree.code
    diff = _make_diff(source, new_source, file_path)
    br = blast_radius(source, new_source)
    pl = patch_locality(diff, len(new_source.splitlines()))
    tc = token_cost(source + function_name + new_body, diff)
    pathlib.Path(file_path).write_text(new_source, encoding="utf-8")

    return EditResult(
        success=True,
        syntax_valid=True,
        diff=diff,
        error=None,
        blast_radius=br,
        patch_locality=pl,
        token_cost=tc,
    )


def edit_class_method(
    file_path: str, class_name: str, method_name: str, new_body: str
) -> EditResult:
    try:
        source = pathlib.Path(file_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return _file_not_found_result(file_path)
    tree = cst.parse_module(source)

    class_exists = any(
        isinstance(stmt, cst.ClassDef) and stmt.name.value == class_name
        for stmt in tree.body
    )
    if not class_exists:
        return EditResult(
            success=False,
            syntax_valid=True,
            diff="",
            error=f"class '{class_name}' not found",
            blast_radius=None,
            patch_locality=None,
            token_cost=None,
        )

    if _find_method(tree, class_name, method_name) is None:
        return EditResult(
            success=False,
            syntax_valid=True,
            diff="",
            error=f"method '{method_name}' not found in class '{class_name}'",
            blast_radius=None,
            patch_locality=None,
            token_cost=None,
        )

    parsed_body = _parse_new_body(new_body)
    if parsed_body is None:
        return EditResult(
            success=False,
            syntax_valid=False,
            diff="",
            error="new_body has a syntax error",
            blast_radius=None,
            patch_locality=None,
            token_cost=None,
        )

    replacer = _ClassMethodReplacer(class_name, method_name, parsed_body)
    new_tree = tree.visit(replacer)
    new_source = new_tree.code
    diff = _make_diff(source, new_source, file_path)
    br = blast_radius(source, new_source)
    pl = patch_locality(diff, len(new_source.splitlines()))
    tc = token_cost(source + class_name + method_name + new_body, diff)
    pathlib.Path(file_path).write_text(new_source, encoding="utf-8")

    return EditResult(
        success=True,
        syntax_valid=True,
        diff=diff,
        error=None,
        blast_radius=br,
        patch_locality=pl,
        token_cost=tc,
    )


def _sig_first_line(node: cst.FunctionDef | cst.ClassDef) -> str:
    """Return the def/class signature line with no body and no decorators."""
    stub = node.with_changes(
        decorators=(),
        leading_lines=(),
        body=cst.IndentedBlock([cst.SimpleStatementLine([cst.Pass()])]),
    )
    lines = cst.Module(body=[stub]).code.splitlines()
    return lines[0] if lines else node.name.value


def _sig_compact(node: cst.FunctionDef | cst.ClassDef) -> str:
    """Compact label: 'fn name(params) -> ret' or 'async fn …' or 'cls Name'."""
    if isinstance(node, cst.ClassDef):
        return f"cls {node.name.value}"
    sig = _sig_first_line(node).rstrip(":")
    if sig.startswith("async def "):
        return "async fn " + sig[len("async def "):]
    return "fn " + sig[len("def "):]


def read_structure(file_path: str) -> str:
    """Return top-level functions/classes with compact signatures and line ranges."""
    try:
        source = pathlib.Path(file_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: file not found — {file_path}"
    try:
        tree = cst.parse_module(source)
    except cst.ParserSyntaxError as exc:
        return f"Error: could not parse {file_path} — {exc}"
    wrapper = MetadataWrapper(tree)
    positions = wrapper.resolve(PositionProvider)

    out: list[str] = []
    for stmt in wrapper.module.body:
        if isinstance(stmt, cst.FunctionDef):
            rng = positions[stmt]
            out.append(f"{_sig_compact(stmt)}  L{rng.start.line}-{rng.end.line}")
        elif isinstance(stmt, cst.ClassDef):
            rng = positions[stmt]
            out.append(f"{_sig_compact(stmt)}  L{rng.start.line}-{rng.end.line}")
            for item in stmt.body.body:
                if isinstance(item, cst.FunctionDef):
                    mr = positions[item]
                    out.append(
                        f"  {_sig_compact(item)}  L{mr.start.line}-{mr.end.line}"
                    )

    return "\n".join(out) if out else "(empty file)"


def measure_edit(
    file_path: str,
    function_name: str,
    new_body: str,
    class_name: str | None = None,
) -> EditResult:
    """Dry-run edit_function_body: metrics and diff without writing the file."""
    if class_name is not None:
        return EditResult(
            success=False,
            syntax_valid=True,
            diff="",
            error=(
                "measure_edit does not yet support class methods. "
                "Call edit_class_method directly and check blast_radius in the result."
            ),
            blast_radius=None,
            patch_locality=None,
            token_cost=None,
        )
    try:
        source = pathlib.Path(file_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return _file_not_found_result(file_path)
    tree = cst.parse_module(source)

    if find_symbol(tree, function_name) is None:
        return EditResult(
            success=False,
            syntax_valid=True,
            diff="",
            error=(
                f"function '{function_name}' not found at top level; "
                "for class methods use edit_class_method"
            ),
            blast_radius=None,
            patch_locality=None,
            token_cost=None,
        )

    parsed_body = _parse_new_body(new_body)
    if parsed_body is None:
        return EditResult(
            success=False,
            syntax_valid=False,
            diff="",
            error="new_body has a syntax error",
            blast_radius=None,
            patch_locality=None,
            token_cost=None,
        )

    replacer = _TopLevelFunctionReplacer(function_name, parsed_body)
    new_tree = tree.visit(replacer)
    new_source = new_tree.code
    diff = _make_diff(source, new_source, file_path)
    br = blast_radius(source, new_source)
    pl = patch_locality(diff, len(new_source.splitlines()))
    tc = token_cost(source + function_name + new_body, diff)

    return EditResult(
        success=True,
        syntax_valid=True,
        diff=diff,
        error=None,
        blast_radius=br,
        patch_locality=pl,
        token_cost=tc,
    )
