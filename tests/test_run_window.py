"""4단계 실행 창: 실행 콤보 통합, 선택 이관, Esc, 상태 한 줄."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.models import ProfileModel
from app.storage.profile_storage import save_profile
from app.storage.run_sets_storage import CURRENT_RUN_SET_ID, get_run_set, upsert_run_set
from app.ui.main_frames import RunTargetFrame
from app.ui.simulator_app import KeystrokeSimulatorApp
from app.utils.i18n import set_language
from tests.test_keystroke_simulator_app_flow import FakeVar, _make_app_stub


def _frame(tmp: Path) -> RunTargetFrame:
    """Tk 없이 RunTargetFrame의 선택 규칙만 쓰는 stub."""
    frame = RunTargetFrame.__new__(RunTargetFrame)
    frame.profiles_dir = tmp / "profiles"
    frame.sets_path = tmp / "run_sets.json"
    frame.profile_var = FakeVar("")
    frame.run_set_var = FakeVar(CURRENT_RUN_SET_ID)
    frame._edit_cb = MagicMock()
    frame._favorites = set()
    frame.profile_names = []
    frame.run_set_names = []
    frame.targets = []
    frame.combobox = MagicMock()
    frame.combobox.current.return_value = -1
    return frame


class TestRunTargetFrame(unittest.TestCase):
    """M-01: one combo lists profiles, a separator, then saved run sets."""

    def setUp(self):
        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        for name, fav in (("B", False), ("A", True)):
            save_profile(
                self.dir / "profiles",
                ProfileModel(name=name, event_list=[], favorite=fav),
                name=name,
            )
        upsert_run_set("Raid", ["A", "Gone"], self.dir / "run_sets.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_targets_are_profiles_separator_then_sets(self):
        frame = _frame(self.dir)

        frame.load()

        self.assertEqual(
            frame.targets,
            [("profile", "Quick"), ("profile", "A"), ("profile", "B"), None, ("run_set", "Raid")],
        )
        values = frame.combobox.configure.call_args.kwargs["values"]
        self.assertTrue(values[3].startswith("─"))
        self.assertEqual(values[4], "Set · Raid")
        # Nothing selected before → falls back to Quick.
        self.assertEqual(frame.get_target(), ("profile", "Quick"))

    def test_choosing_a_profile_or_set_writes_the_selection(self):
        frame = _frame(self.dir)
        frame.load()

        frame.set_target("run_set", "Raid")
        self.assertEqual(frame.get_target(), ("run_set", "Raid"))
        # Members that no longer exist are dropped.
        self.assertEqual(frame.get_run_profiles(), ["A"])

        frame.set_target("profile", "B")
        self.assertEqual(frame.run_set_var.get(), CURRENT_RUN_SET_ID)
        self.assertEqual(frame.get_run_profiles(), ["B"])

    def test_separator_cannot_be_selected(self):
        frame = _frame(self.dir)
        frame.load(select=("profile", "A"))
        frame.combobox.current.return_value = 3  # the separator row

        frame._on_selected()

        self.assertEqual(frame.get_target(), ("profile", "A"))

    def test_edit_opens_the_selected_target(self):
        frame = _frame(self.dir)
        frame.load(select=("run_set", "Raid"))

        frame._on_edit()

        frame._edit_cb.assert_called_once_with(("run_set", "Raid"))


class TestSelectionMigration(unittest.TestCase):
    """M-01: app_state.json keeps working without the virtual current set."""

    def setUp(self):
        self.app = _make_app_stub()
        self.frame = MagicMock()
        self.frame.run_set_names = ["Raid"]
        self.app.run_target_frame = self.frame

    def test_named_set_is_selected(self):
        KeystrokeSimulatorApp._restore_run_set_selection(self.app, {"run_set": "Raid"})

        self.frame.set_target.assert_called_once_with("run_set", "Raid")

    def test_legacy_current_set_keeps_the_profile(self):
        KeystrokeSimulatorApp._restore_run_set_selection(
            self.app, {"run_set": CURRENT_RUN_SET_ID}
        )

        self.frame.set_target.assert_not_called()
        self.frame.load.assert_not_called()

    def test_legacy_multi_profile_list_becomes_a_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.app.run_sets_path = Path(tmp) / "run_sets.json"

            KeystrokeSimulatorApp._restore_run_set_selection(
                self.app, {"run_profiles": ["A", "B"]}
            )

            self.assertEqual(get_run_set("Migrated", self.app.run_sets_path), ["A", "B"])
        self.frame.load.assert_called_once_with(select=("run_set", "Migrated"))


class TestRunWindowBehaviour(unittest.TestCase):
    def setUp(self):
        set_language("en")

    @patch("app.ui.simulator_app.platform.system", return_value="Linux")
    @patch("app.ui.simulator_app.pynput.keyboard.Listener")
    def test_escape_no_longer_quits(self, _listener, _system):
        """M-05."""
        app = _make_app_stub()
        app.start_stop_mouse_listener = None

        KeystrokeSimulatorApp.setup_event_handlers(app)

        bound = [c.args[0] for c in app.bind.call_args_list]
        self.assertNotIn("<Escape>", bound)

    def _status_app(self, snapshot):
        app = _make_app_stub()
        app.lbl_status_badge = MagicMock()
        app.btn_status_fix = MagicMock()
        app.status_tooltip = MagicMock()
        app.lbl_run_status = MagicMock()
        app._get_readiness_snapshot = MagicMock(return_value=snapshot)
        del app._update_main_status  # use the real method
        return app

    def test_ready_status_is_one_line_without_fix_button(self):
        """M-03: ready uses the READY tone and shows no fix button."""
        app = self._status_app(
            {
                "can_start": True,
                "badge_text": "Ready",
                "title": "t",
                "summary": "rules 13 · signals 13",
                "detail": "d",
                "bg": "#E6F0E4",
                "fg": "#1F4A2E",
            }
        )

        KeystrokeSimulatorApp._update_main_status(app)

        text = app.lbl_status_badge.config.call_args.kwargs["text"]
        self.assertIn("Ready · rules 13 · signals 13", text)
        self.assertNotIn("\n", text)
        app.btn_status_fix.pack_forget.assert_called_once()

    def test_blocked_status_offers_a_single_fix(self):
        app = self._status_app(
            {
                "can_start": False,
                "badge_text": "Permissions",
                "title": "macOS permissions are blocking capture.",
                "detail": "d",
                "bg": "#F7DAD4",
                "fg": "#7A2820",
                "missing_permissions": ["accessibility"],
                "action": "permissions",
            }
        )
        app._open_macos_permission_setting = MagicMock()

        KeystrokeSimulatorApp._update_main_status(app)
        KeystrokeSimulatorApp._on_status_fix(app)

        app.btn_status_fix.pack.assert_called_once()
        app._open_macos_permission_setting.assert_called_once_with("accessibility")

    def test_workspace_fix_opens_the_workspace(self):
        app = _make_app_stub()
        app._status_action = "workspace"
        app.open_profile = MagicMock()

        KeystrokeSimulatorApp._on_status_fix(app)

        app.open_profile.assert_called_once()

    @patch("app.ui.simulator_app.Workspace")
    def test_edit_opens_workspace_on_the_selected_run_set(self, mock_workspace):
        """M-06."""
        app = _make_app_stub()
        app.selected_profile = FakeVar("A")

        KeystrokeSimulatorApp.open_workspace_for(app, ("run_set", "Raid"))

        kwargs = mock_workspace.call_args.kwargs
        self.assertEqual((kwargs["profile"], kwargs["run_set"]), ("A", "Raid"))


class TestRunControlDisabledText(unittest.TestCase):
    def test_disabled_start_keeps_its_text_color(self):
        """The disabled Start label must not fall back to Tk's faint disabled text."""
        button = MagicMock()

        KeystrokeSimulatorApp._apply_run_disabled_button(button)

        kwargs = button.configure.call_args_list[0].kwargs
        self.assertEqual(kwargs["disabledforeground"], kwargs["fg"])


class TestWorkspaceEscape(unittest.TestCase):
    def test_escape_clears_search_before_closing(self):
        from app.ui.workspace import Workspace

        ws = Workspace.__new__(Workspace)
        ws.search_var = FakeVar("abc")

        self.assertEqual(ws._on_search_escape(None), "break")
        self.assertEqual(ws.search_var.get(), "")
        # Empty search: Esc propagates to the window binding, which closes it.
        self.assertIsNone(ws._on_search_escape(None))


class TestRunSetRenameKeepsSelection(unittest.TestCase):
    """Review fix: renaming the selected run set must not fall back to a profile."""

    def test_main_window_follows_renamed_run_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            save_profile(d / "profiles", ProfileModel(name="A", event_list=[]), name="A")
            upsert_run_set("Raid", ["A"], d / "run_sets.json")
            frame = _frame(d)
            frame.load(select=("run_set", "Raid"))
            app = _make_app_stub()
            app.profiles_dir = d / "profiles"
            app.run_sets_path = d / "run_sets.json"
            app.selected_profile = frame.profile_var
            app.selected_run_set = frame.run_set_var
            app.run_target_frame = frame

            from app.storage.run_sets_storage import rename_run_set

            rename_run_set("Raid", "Raid v2", app.run_sets_path)
            KeystrokeSimulatorApp._on_run_set_renamed(app, "Raid", "Raid v2")
            KeystrokeSimulatorApp.reload_profiles(app, None)

            self.assertEqual(frame.get_target(), ("run_set", "Raid v2"))


class TestRunSetEditorRefusal(unittest.TestCase):
    """Review fix: a refused uncheck is reverted so it cannot leak into the next save."""

    def test_refused_toggle_restores_checkboxes(self):
        from app.ui.workspace import RunSetEditor

        editor = RunSetEditor.__new__(RunSetEditor)
        editor.available = ["A", "B"]
        editor.vars = {"A": FakeVar(True), "B": FakeVar(False)}
        editor._saved = ["A"]
        editor.lbl_error = MagicMock()
        saved = []
        editor.on_members_changed = lambda members: bool(members) and not saved.append(members)

        editor.vars["A"].set(False)
        editor._on_toggle()  # refused: nothing left
        self.assertTrue(editor.vars["A"].get())

        editor.vars["B"].set(True)
        editor._on_toggle()
        self.assertEqual(saved, [["A", "B"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
