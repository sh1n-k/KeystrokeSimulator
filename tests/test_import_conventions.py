import ast
import unittest
from pathlib import Path

from app.compat.legacy import legacy_module_names


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_IMPORT_ROOTS = set(legacy_module_names())
ALLOWED_LEGACY_IMPORT_FILES = {
    PROJECT_ROOT / f"{module_name}.py" for module_name in LEGACY_IMPORT_ROOTS
}


def _project_python_files() -> list[Path]:
    files: list[Path] = []
    for path in PROJECT_ROOT.rglob("*.py"):
        relative_parts = path.relative_to(PROJECT_ROOT).parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        if "__pycache__" in relative_parts:
            continue
        files.append(path)
    return sorted(files)


def _legacy_import_violations(path: Path) -> list[str]:
    if path in ALLOWED_LEGACY_IMPORT_FILES:
        return []

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_root = alias.name.split(".", 1)[0]
                if import_root in LEGACY_IMPORT_ROOTS:
                    violations.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            import_root = node.module.split(".", 1)[0]
            if import_root in LEGACY_IMPORT_ROOTS:
                violations.append(f"line {node.lineno}: from {node.module} import ...")

    return violations


class TestImportConventions(unittest.TestCase):
    def test_non_shim_files_do_not_import_legacy_root_modules(self):
        violations: list[str] = []

        for path in _project_python_files():
            path_violations = _legacy_import_violations(path)
            if not path_violations:
                continue

            rel_path = path.relative_to(PROJECT_ROOT)
            violations.extend(
                f"{rel_path}: {violation}" for violation in path_violations
            )

        self.assertEqual(
            violations,
            [],
            "Canonical app imports only. Legacy root modules are shim-only:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
