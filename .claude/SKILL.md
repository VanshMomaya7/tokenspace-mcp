# Tokenspace — MCP Skill

Tokenspace edits Python functions and methods by symbol name, not text position.
Every edit returns a diff, blast radius, and token cost automatically.

---

## When to use Tokenspace (not str_replace)

**Use Tokenspace when:**
- Editing a specific Python function or method by name
- You need to understand what's in a file before editing (use `read_structure` — 3.4× cheaper than reading the file)
- You want to estimate cost and risk before writing (use `measure_edit` — dry run, no disk write)
- Making multiple edits to the same file (`read_structure` cost is paid once; 95.4% token reduction vs str_replace across 5 edits)

**Use str_replace when:**
- Editing non-Python files
- Rewriting the whole file
- Changing only imports, comments, or docstrings (no function body change)

---

## Optimal Workflow

### Single edit
```
1. read_structure(file_path)
   → confirms exact symbol name and line range, costs ~200 tokens vs ~700 for the full file

2. measure_edit(file_path, function_name, new_body)
   → dry run: get blast_radius and token_cost without writing

3. If blast_radius < 0.10 and cost looks acceptable:
   edit_function_body(file_path, function_name, new_body)
   or
   edit_class_method(file_path, class_name, method_name, new_body)

4. Check the format_result output: success, patch_locality, diff line count
```

### Multi-edit session (same file)
```
1. read_structure(file_path)          ← once, amortized across all edits

2. For each function to edit:
   edit_function_body(...)  or  edit_class_method(...)
   check result after each

   (Skip measure_edit in bulk — read_structure already confirmed symbol names)
```

---

## Tool Reference

### `read_structure`

**When:** Before any edit. Use instead of reading the full file.

```
read_structure(file_path: str) -> str
```

**Returns:** One line per top-level symbol. Methods indented under their class. Compact signatures with line ranges. No bodies.

**Real output** (`requests/auth.py`, 354 lines → 21 lines):
```
fn _basic_auth_str(username: bytes | str, password: bytes | str) -> str  L34-75
cls AuthBase  L78-82
  fn __call__(self, r: PreparedRequest) -> PreparedRequest  L81-82
cls HTTPBasicAuth  L85-113
  fn __init__(self, username: bytes | str, password: bytes | str) -> None  L96-98
  fn __eq__(self, other: object) -> bool  L100-106
  fn __call__(self, r: PreparedRequest) -> PreparedRequest  L111-113
cls HTTPDigestAuth  L124-354
  fn build_digest_header(self, method: str, url: str) -> str | None  L157-266
  fn handle_401(self, r: Response, **kwargs: Any) -> Response  L273-319
  fn __call__(self, r: PreparedRequest) -> PreparedRequest  L321-343
```

**Mistakes:**
- Do not call once per edit in a loop — call once per file per session.
- Output has no function bodies. To read a body, read those specific line numbers from the file.
- If a method is indented under a class in the output, you must use `edit_class_method`, not `edit_function_body`.

---

### `measure_edit`

**When:** Before `edit_function_body`, when you want to verify blast radius or token cost without committing. Top-level functions only (not class methods).

```
measure_edit(file_path: str, function_name: str, new_body: str) -> str
```

**Real output:**
```
Dry-run metrics for '_basic_auth_str':
  blast_radius:   0.00
  patch_locality: 0.99
  token_cost:     3483
```

**Blast radius guide:**
| Value | Meaning |
|---|---|
| `0.00` | No signatures changed — safe to proceed |
| `0.01–0.10` | One or two signatures changed — review before writing |
| `> 0.10` | Broad structural change — confirm this is intentional |

**Mistakes:**
- `measure_edit` does not support class methods. For methods, call `edit_class_method` directly and check success/blast_radius in the result.
- A passing `measure_edit` only confirms parse validity and cost — not correctness of the logic.

---

### `edit_function_body`

**When:** Replacing a top-level function body. **Writes to disk on success.**

```
edit_function_body(file_path: str, function_name: str, new_body: str) -> str
```

- `function_name`: exact name as shown in `read_structure` output (e.g. `_basic_auth_str`)
- `new_body`: body source only — do not include the `def name(...):` line
- Indentation is normalised automatically

**Real success output:**
```
Edit successful
  Blast radius:   0.00  (0% of symbols affected)
  Patch locality: 0.99  (edit is well-contained)
  Token cost:     3483 tokens
  Diff: 52 lines changed
```

**Real failure output:**
```
Edit failed: function 'validate' not found at top level; for class methods use edit_class_method
```

**Mistakes:**
- Do not include the signature line in `new_body`.
- If `read_structure` shows the symbol indented under a class, use `edit_class_method` — this tool will fail with a clear error message.

---

### `edit_class_method`

**When:** Replacing a method body inside a class. **Writes to disk on success.**

```
edit_class_method(file_path: str, class_name: str, method_name: str, new_body: str) -> str
```

- `class_name`: the containing class name (`HTTPDigestAuth`)
- `method_name`: the method name only — not `ClassName.method` (`build_digest_header`)
- `class_name` is the disambiguator when two classes have the same method name

**Example:**
```python
edit_class_method(
    "requests/auth.py",
    "HTTPDigestAuth",
    "handle_401",
    """
    self.num_401_calls += 1
    if self.num_401_calls > 1:
        r.content
        r.close()
        return r
    return self.handle_response(r)
    """
)
```

**Same success/failure format as `edit_function_body`.**

**Mistakes:**
- `method_name` is the bare name, not `Class.method`.
- Do not use `edit_function_body` for class methods — use this tool.

---

## Why This Exists (Benchmark Numbers)

Measured on **406 real functions** from requests, flask, fastapi, django, httpx, pydantic, black, click, and rich. All 10 files passed libcst round-trip.

| Scenario | str_replace total tokens | Tokenspace total tokens | Reduction |
|---|---|---|---|
| Single edit — 406 functions | 36,907 | 18,674 | **49.4%** |
| 5 edits / file — 10 files | 70,948 | 2,039 | **95.4%** |

The multi-edit gap is large because `str_replace` pays full file content on every single edit. Tokenspace pays for `read_structure` once and only the function name + new body per edit.

---

## Quick Decision Table

| I want to... | Use |
|---|---|
| See what's in a file without reading it all | `read_structure` |
| Check cost before modifying a top-level function | `measure_edit` |
| Edit a top-level function | `edit_function_body` |
| Edit a class method | `edit_class_method` |
| Rewrite a whole file / edit non-Python / change imports only | `str_replace` |
