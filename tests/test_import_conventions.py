import ast
import tempfile
import unittest
from collections.abc import Callable
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
    "main",
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


APP_ROOT = PROJECT_ROOT / "app"
GUI_TOOLKIT_MODULES = {"tkinter", "PySide6"}
OS_SERVICE_MODULES = {
    "AppKit",
    "ApplicationServices",
    "Quartz",
    "ScreenCaptureKit",
    "ctypes",
    "mss",
    "objc",
    "pynput",
}
DOMAIN_FORBIDDEN_APP_PACKAGES = ("app.engine", "app.platform", "app.storage", "app.ui")


def _app_python_files(package: str | None = None) -> list[Path]:
    base = APP_ROOT / package if package else APP_ROOT
    return sorted(
        path for path in base.rglob("*.py") if "__pycache__" not in path.parts
    )


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    """Return (line, dotted module) for every import, including nested ones."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise AssertionError(
                    f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: "
                    "relative imports are not used in app/"
                )
            module = node.module or ""
            modules.append((node.lineno, module))
            # `from app import ui` imports the subpackage app.ui.
            modules.extend(
                (node.lineno, f"{module}.{alias.name}") for alias in node.names
            )
    return modules


def _is_under(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def _is_os_service_module(module: str) -> bool:
    root = module.split(".", 1)[0]
    return root in OS_SERVICE_MODULES or root.startswith(("win32", "pywintypes"))


def _boundary_violations(
    files: list[Path], forbidden: Callable[[str], bool]
) -> list[str]:
    violations: list[str] = []
    for path in files:
        rel_path = path.relative_to(PROJECT_ROOT)
        for lineno, module in _imported_modules(path):
            if forbidden(module):
                violations.append(f"{rel_path}:{lineno}: {module}")
    return sorted(set(violations))


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


class TestPackageBoundaries(unittest.TestCase):
    def test_gui_toolkits_are_imported_only_in_ui(self):
        ui_root = APP_ROOT / "ui"
        files = [path for path in _app_python_files() if ui_root not in path.parents]
        violations = _boundary_violations(
            files, lambda module: module.split(".", 1)[0] in GUI_TOOLKIT_MODULES
        )
        self.assertEqual(
            violations,
            [],
            "tkinter/PySide6 may only be imported under app/ui:\n"
            + "\n".join(violations),
        )

    def test_domain_has_no_os_ui_or_io_layer_imports(self):
        def forbidden(module: str) -> bool:
            return (
                any(_is_under(module, pkg) for pkg in DOMAIN_FORBIDDEN_APP_PACKAGES)
                or _is_os_service_module(module)
                or module.split(".", 1)[0] in GUI_TOOLKIT_MODULES
            )

        violations = _boundary_violations(_app_python_files("domain"), forbidden)
        self.assertEqual(
            violations,
            [],
            "app/domain must stay free of engine/platform/storage/ui and OS "
            "modules:\n" + "\n".join(violations),
        )

    def test_non_ui_packages_do_not_import_ui(self):
        files = [
            path
            for package in ("engine", "platform", "presenters", "storage", "utils")
            for path in _app_python_files(package)
        ]
        violations = _boundary_violations(
            files, lambda module: _is_under(module, "app.ui")
        )
        self.assertEqual(
            violations,
            [],
            "engine/platform/presenters/storage/utils must not import app.ui:\n"
            + "\n".join(violations),
        )

    def test_boundary_checker_detects_forbidden_imports(self):
        sample = "\n".join(
            [
                "import tkinter as tk",
                "from app import ui",
                "from app.platform.keys import KeyUtils",
                "def f():",
                "    import win32api",
                "    from Quartz import CGEventTapCreate",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.py"
            path.write_text(sample, encoding="utf-8")
            modules = {module for _line, module in _imported_modules(path)}
        self.assertTrue({"tkinter", "app.ui", "win32api", "Quartz"} <= modules)
        self.assertTrue(_is_under("app.platform.keys", "app.platform"))
        self.assertFalse(_is_under("app.platformx", "app.platform"))
        self.assertTrue(_is_os_service_module("win32api"))
        self.assertTrue(_is_os_service_module("Quartz"))
        self.assertFalse(_is_os_service_module("PIL.Image"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
