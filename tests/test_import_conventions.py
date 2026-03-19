import ast
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REMOVED_LEGACY_MODULES = {
    "i18n",
    "keystroke_capturer",
    "keystroke_event_editor",
    "keystroke_event_graph",
    "keystroke_event_importer",
    "keystroke_models",
    "keystroke_modkeys",
    "keystroke_processor",
    "keystroke_profile_storage",
    "keystroke_profiles",
    "keystroke_quick_event_editor",
    "keystroke_settings",
    "keystroke_simulator_app",
    "keystroke_sounds",
    "keystroke_sort_events",
    "keystroke_utils",
    "profile_display",
    "runtime_toggle_sound_assets",
    "runtime_toggle_utils",
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
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_root = alias.name.split(".", 1)[0]
                if import_root in REMOVED_LEGACY_MODULES:
                    violations.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            import_root = node.module.split(".", 1)[0]
            if import_root in REMOVED_LEGACY_MODULES:
                violations.append(f"line {node.lineno}: from {node.module} import ...")

    return violations


class TestImportConventions(unittest.TestCase):
    def test_project_does_not_import_removed_legacy_root_modules(self):
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
            "Removed legacy root modules must not be imported:\n"
            + "\n".join(violations),
        )

    def test_removed_legacy_root_files_are_absent(self):
        existing_paths = [
            str((PROJECT_ROOT / f"{module_name}.py").relative_to(PROJECT_ROOT))
            for module_name in sorted(REMOVED_LEGACY_MODULES)
            if (PROJECT_ROOT / f"{module_name}.py").exists()
        ]
        self.assertEqual(existing_paths, [], "\n".join(existing_paths))


if __name__ == "__main__":
    unittest.main(verbosity=2)
