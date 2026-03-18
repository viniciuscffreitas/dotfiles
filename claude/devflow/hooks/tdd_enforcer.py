"""
PostToolUse hook (Write|Edit|MultiEdit) — warns about implementation without tests.
Non-blocking: never blocks, only advises with suggested test path.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import GENERATED_PATTERNS, SKIP_DIRS, get_edited_file, hook_context, read_hook_stdin

_TEST_PATTERNS = {
    "test_", "_test.", ".test.", "_spec.", ".spec.",
    "tests/", "/test/", "/tests/", "__tests__/",
    "conftest.", "fixture", "mock",
}
_IMPL_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".dart", ".kt", ".swift"}
_SKIP_NAMES = {
    "setup.py", "conftest.py", "manage.py", "wsgi.py", "asgi.py",
    "main.dart", "app.ts", "index.ts", "index.js",
}


def is_test_file(path: Path) -> bool:
    str_path = str(path).lower()
    return any(pattern in str_path for pattern in _TEST_PATTERNS)


def is_impl_file(path: Path) -> bool:
    if path.suffix not in _IMPL_EXTENSIONS:
        return False
    if path.name in _SKIP_NAMES:
        return False
    name = path.name.lower()
    if any(name.endswith(p) for p in GENERATED_PATTERNS):
        return False
    for part in path.parts:
        if part in SKIP_DIRS:
            return False
    return True


def suggest_test_path(impl_path: Path) -> str:
    stem = impl_path.stem
    ext = impl_path.suffix
    parts = list(impl_path.parts)

    impl_dirs = {"lib", "src", "internal", "pkg", "app"}
    test_dirs = {"lib": "test", "src": "tests", "internal": "tests", "pkg": "tests", "app": "tests"}
    test_suffixes = {
        ".dart": f"{stem}_test{ext}",
        ".py": f"test_{stem}{ext}",
        ".go": f"{stem}_test{ext}",
        ".ts": f"{stem}.test{ext}",
        ".tsx": f"{stem}.test{ext}",
        ".js": f"{stem}.test{ext}",
        ".jsx": f"{stem}.test{ext}",
        ".kt": f"{stem}Test{ext}",
        ".swift": f"{stem}Tests{ext}",
    }

    test_filename = test_suffixes.get(ext, f"test_{stem}{ext}")

    for i, part in enumerate(parts):
        if part in impl_dirs:
            mirrored = list(parts)
            mirrored[i] = test_dirs.get(part, "tests")
            mirrored[-1] = test_filename
            return str(Path(*mirrored))

    return str(impl_path.parent / test_filename)


def find_test_file(impl_path: Path, max_depth: int = 5) -> bool:
    stem = impl_path.stem
    root = impl_path.parent

    test_dir_names = ["tests", "test", "__tests__"]
    monorepo_patterns = ["packages/*/test", "packages/*/tests", "apps/*/test", "apps/*/tests"]

    for _ in range(max_depth):
        # Check standard test dirs with targeted glob (not rglob)
        for test_dir in test_dir_names:
            td = root / test_dir
            if td.is_dir():
                for pattern in [
                    f"test_{stem}.*", f"{stem}_test.*", f"{stem}.test.*", f"{stem}.spec.*",
                    f"**/test_{stem}.*", f"**/{stem}_test.*", f"**/{stem}.test.*",
                ]:
                    if list(td.glob(pattern)):
                        return True

        # Check sibling test files
        for pattern in [f"test_{stem}", f"{stem}_test", f"{stem}.test", f"{stem}.spec"]:
            for ext in _IMPL_EXTENSIONS:
                if (root / f"{pattern}{ext}").exists():
                    return True

        # Check monorepo patterns from this level
        for mono_pattern in monorepo_patterns:
            for td in root.glob(mono_pattern):
                if td.is_dir():
                    for f in td.glob(f"**/*{stem}*"):
                        if is_test_file(f):
                            return True

        parent = root.parent
        if parent == root:
            break
        root = parent

    return False


def main() -> int:
    hook_data = read_hook_stdin()
    file_path = get_edited_file(hook_data)

    if not file_path or not file_path.exists():
        return 0

    if is_test_file(file_path) or not is_impl_file(file_path):
        return 0

    has_test = find_test_file(file_path)
    if not has_test:
        suggested = suggest_test_path(file_path)
        context = (
            f"[devflow TDD] {file_path.name}: implementation without corresponding test.\n"
            f"Suggestion: create `{suggested}`\n"
            f"TDD: RED -> GREEN -> REFACTOR"
        )
        print(hook_context(context))

    return 0


if __name__ == "__main__":
    sys.exit(main())
