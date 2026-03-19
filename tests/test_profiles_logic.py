import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.models import EventModel, ProfileModel
from app.ui.profiles import EventListFrame, EventRow, KeystrokeProfiles
from app.utils.i18n import set_language


class FakeWidget:
    def __init__(self, **kwargs):
        self._state = dict(kwargs)

    def config(self, **kwargs):
        self._state.update(kwargs)

    def cget(self, key):
        return self._state.get(key)


class FakeEntry(FakeWidget):
    def get(self):
        return self._state.get("text", "")

    def delete(self, _start, _end):
        self._state["text"] = ""

    def insert(self, _index, text):
        self._state["text"] = text


class FakeVar:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value


class FakeToolTip:
    def __init__(self):
        self.text = ""

    def update_text(self, text):
        self.text = text


class FakeDestroyable:
    def __init__(self):
        self.destroyed = False
        self.row_num = 0

    def destroy(self):
        self.destroyed = True


def _make_event_list_frame_stub():
    """GUI 없이 EventListFrame의 메서드만 테스트하기 위한 stub"""
    stub = EventListFrame.__new__(EventListFrame)
    return stub


class TestGetKeySortOrder(unittest.TestCase):
    """EventListFrame._get_key_sort_order: 키 정렬 순서"""

    def setUp(self):
        set_language("en")
        self.stub = _make_event_list_frame_stub()

    def test_digit(self):
        """숫자 키 '3' → 카테고리 0"""
        result = self.stub._get_key_sort_order("3")
        self.assertEqual(result, (0, 3, "3"))

    def test_alpha(self):
        """알파벳 키 'a' → 카테고리 1, 대문자 변환"""
        result = self.stub._get_key_sort_order("a")
        self.assertEqual(result, (1, ord("A"), "A"))

    def test_function_key_f5(self):
        """펑션키 F5 → 카테고리 2"""
        result = self.stub._get_key_sort_order("F5")
        self.assertEqual(result, (2, 5, "F5"))

    def test_function_key_f13_out_of_range(self):
        """F13은 1-12 밖 → 기타 카테고리 4"""
        result = self.stub._get_key_sort_order("F13")
        self.assertEqual(result[0], 4)

    def test_special_key_space(self):
        """특수키 SPACE → 카테고리 3"""
        result = self.stub._get_key_sort_order("SPACE")
        self.assertEqual(result, (3, 0, "SPACE"))

    def test_combo_key(self):
        """조합키 'ctrl+a' → 베이스 키 'A' 기준"""
        result = self.stub._get_key_sort_order("ctrl+a")
        self.assertEqual(result, (1, ord("A"), "A"))

    def test_none_key(self):
        """None → 최하위 정렬"""
        result = self.stub._get_key_sort_order(None)
        self.assertEqual(result, (99, 0, ""))


class TestUpdateConditionReferences(unittest.TestCase):
    """EventListFrame._update_condition_references: 조건 참조 업데이트"""

    def _make_stub_with_events(self, events):
        stub = _make_event_list_frame_stub()
        stub.profile = ProfileModel(event_list=events)
        return stub

    def test_old_name_replaced(self):
        """old_name이 new_name으로 교체됨"""
        events = [
            EventModel(event_name="A", conditions={"OldName": True}),
            EventModel(event_name="B", conditions={"OldName": False}),
        ]
        stub = self._make_stub_with_events(events)
        stub._update_condition_references("OldName", "NewName")

        self.assertIn("NewName", events[0].conditions)
        self.assertNotIn("OldName", events[0].conditions)
        self.assertTrue(events[0].conditions["NewName"])

        self.assertIn("NewName", events[1].conditions)
        self.assertFalse(events[1].conditions["NewName"])

    def test_unrelated_conditions_unchanged(self):
        """관련 없는 조건은 변경 안 됨"""
        events = [
            EventModel(event_name="A", conditions={"Other": True}),
        ]
        stub = self._make_stub_with_events(events)
        stub._update_condition_references("OldName", "NewName")

        self.assertIn("Other", events[0].conditions)
        self.assertNotIn("NewName", events[0].conditions)

    def test_no_match_no_op(self):
        """해당 이름이 conditions에 없으면 무동작"""
        events = [
            EventModel(event_name="A", conditions={"X": True}),
        ]
        stub = self._make_stub_with_events(events)
        stub._update_condition_references("NonExistent", "NewName")

        self.assertEqual(events[0].conditions, {"X": True})


class TestEditorSaveRenamePropagation(unittest.TestCase):
    """EventListFrame._on_editor_save: 편집기 저장 시 이름 변경 전파"""

    def test_edit_rename_updates_dependent_conditions(self):
        stub = _make_event_list_frame_stub()
        dependent = EventModel(event_name="Dependent", conditions={"OldName": True})
        stub.profile = ProfileModel(
            event_list=[
                EventModel(event_name="OldName", key_to_enter="A"),
                dependent,
            ]
        )
        stub.update_events = MagicMock()
        stub.save_cb = MagicMock()

        edited = EventModel(event_name="NewName", key_to_enter="A")
        stub._on_editor_save(edited, is_edit=True, row=0)

        self.assertEqual(stub.profile.event_list[0].event_name, "NewName")
        self.assertEqual(dependent.conditions, {"NewName": True})
        stub.update_events.assert_called_once()
        stub.save_cb.assert_called_once_with(check_name=False)

    def test_add_event_does_not_touch_existing_conditions(self):
        stub = _make_event_list_frame_stub()
        dependent = EventModel(event_name="Dependent", conditions={"Existing": False})
        stub.profile = ProfileModel(event_list=[dependent])
        stub.update_events = MagicMock()
        stub.save_cb = MagicMock()

        new_evt = EventModel(event_name="NewEvent", key_to_enter="B")
        stub._on_editor_save(new_evt, is_edit=False, row=1)

        self.assertEqual(stub.profile.event_list[-1].event_name, "NewEvent")
        self.assertEqual(dependent.conditions, {"Existing": False})
        stub.update_events.assert_called_once()
        stub.save_cb.assert_called_once_with(check_name=False)

    def test_edit_preserves_runtime_toggle_member_and_use_event(self):
        stub = _make_event_list_frame_stub()
        original = EventModel(
            event_name="OldName",
            key_to_enter="A",
            runtime_toggle_member=True,
            use_event=False,
        )
        stub.profile = ProfileModel(event_list=[original])
        stub.update_events = MagicMock()
        stub.save_cb = MagicMock()

        edited = EventModel(event_name="OldName", key_to_enter="B")
        stub._on_editor_save(edited, is_edit=True, row=0)

        self.assertTrue(stub.profile.event_list[0].runtime_toggle_member)
        self.assertFalse(stub.profile.event_list[0].use_event)
        stub.update_events.assert_called_once()
        stub.save_cb.assert_called_once_with(check_name=False)

    def test_edit_duplicate_name_is_rejected(self):
        stub = _make_event_list_frame_stub()
        stub.profile = ProfileModel(
            event_list=[
                EventModel(event_name="A", key_to_enter="X"),
                EventModel(event_name="B", key_to_enter="Y"),
            ]
        )
        stub.update_events = MagicMock()
        stub.save_cb = MagicMock()
        stub.win = object()

        edited = EventModel(event_name="B", key_to_enter="X")
        with patch("app.ui.profiles.messagebox.showerror") as mock_error:
            stub._on_editor_save(edited, is_edit=True, row=0)

        self.assertEqual(stub.profile.event_list[0].event_name, "A")
        stub.update_events.assert_not_called()
        stub.save_cb.assert_not_called()
        mock_error.assert_called_once()

    def test_save_names_keeps_pending_rename_after_row_refresh(self):
        frame = _make_event_list_frame_stub()
        dependent = EventModel(event_name="Dependent", conditions={"OldName": True})
        renamed = EventModel(event_name="OldName", key_to_enter="A")
        frame.profile = ProfileModel(event_list=[renamed, dependent])

        row = EventRow.__new__(EventRow)
        row.event = renamed
        row.use_var = FakeVar()
        row.entry = FakeEntry(text="NewName")
        row.lbl_cond = FakeWidget(text="")
        row.lbl_grp = FakeWidget(text="")
        row.lbl_key = FakeWidget(text="")
        row._tip_cond = FakeToolTip()
        row._tip_grp = FakeToolTip()
        row._tip_key = FakeToolTip()
        row._last_saved_name = "OldName"
        row._bound_event_id = id(renamed)
        row.cbs = {"save": lambda: None}

        EventRow._on_name_changed(row)
        row.update_display()

        frame.rows = [row]
        frame.save_names()

        self.assertEqual(frame.profile.event_list[0].event_name, "NewName")
        self.assertEqual(dependent.conditions, {"NewName": True})


class TestRemoveRowConditionCleanup(unittest.TestCase):
    """EventListFrame._remove_row: 삭제 시 조건 참조 정리"""

    def test_remove_row_cleans_orphaned_condition_references(self):
        stub = _make_event_list_frame_stub()
        dependent = EventModel(event_name="B", conditions={"A": True, "Other": False})
        stub.profile = ProfileModel(
            event_list=[
                EventModel(event_name="A"),
                dependent,
                EventModel(event_name="C"),
            ]
        )
        first_row = FakeDestroyable()
        second_row = FakeDestroyable()
        third_row = FakeDestroyable()
        stub.rows = [first_row, second_row, third_row]
        stub._update_row_indices = MagicMock()
        stub._update_delete_buttons = MagicMock()
        stub._sync_empty_state = MagicMock()
        stub.save_cb = MagicMock()
        stub.win = type("FakeWin", (), {"update_idletasks": lambda self: None})()

        stub._remove_row(first_row, 0)

        self.assertTrue(first_row.destroyed)
        self.assertEqual(dependent.conditions, {"Other": False})
        stub.save_cb.assert_called_once()

    def test_remove_row_preserves_conditions_when_same_name_still_exists(self):
        stub = _make_event_list_frame_stub()
        dependent = EventModel(event_name="B", conditions={"A": True})
        stub.profile = ProfileModel(
            event_list=[
                EventModel(event_name="A"),
                EventModel(event_name="A"),
                dependent,
            ]
        )
        first_row = FakeDestroyable()
        second_row = FakeDestroyable()
        third_row = FakeDestroyable()
        stub.rows = [first_row, second_row, third_row]
        stub._update_row_indices = MagicMock()
        stub._update_delete_buttons = MagicMock()
        stub._sync_empty_state = MagicMock()
        stub.save_cb = MagicMock()
        stub.win = type("FakeWin", (), {"update_idletasks": lambda self: None})()

        stub._remove_row(first_row, 0)

        self.assertEqual(dependent.conditions, {"A": True})


class TestSortEventsLogic(unittest.TestCase):
    """이벤트 정렬 로직 검증"""

    def _make_sortable_stub(self, events):
        set_language("en")
        stub = _make_event_list_frame_stub()
        stub.profile = ProfileModel(event_list=events)
        return stub

    def _name_sort_key(self, stub, e):
        name = e.event_name or ""
        return (stub._get_event_type_sort_order(e), name.casefold(), name)

    def _key_sort_key(self, stub, e):
        """_sort_events_by_key 내부 sort_key 람다 재현"""
        name = e.event_name or ""
        type_order = stub._get_event_type_sort_order(e)
        if type_order == 0:
            return (type_order, 0, name.casefold(), name)
        return (
            type_order,
            1,
            *stub._get_key_sort_order(getattr(e, "key_to_enter", None)),
            name.casefold(),
            name,
        )

    def test_condition_type_before_action_type(self):
        """조건 전용 이벤트가 키 입력 실행 이벤트보다 먼저"""
        events = [
            EventModel(event_name="Action", execute_action=True, key_to_enter="A"),
            EventModel(event_name="Condition", execute_action=False, key_to_enter=None),
        ]
        stub = self._make_sortable_stub(events)
        sorted_events = sorted(events, key=lambda e: self._name_sort_key(stub, e))
        self.assertEqual(sorted_events[0].event_name, "Condition")

    def test_action_type_sorted_by_input_key_order(self):
        """실행 이벤트는 입력 키 순서"""
        events = [
            EventModel(event_name="Zebra", execute_action=True, key_to_enter="B"),
            EventModel(event_name="Apple", execute_action=True, key_to_enter="A"),
        ]
        stub = self._make_sortable_stub(events)
        sorted_events = sorted(events, key=lambda e: self._key_sort_key(stub, e))
        self.assertEqual(sorted_events[0].event_name, "Apple")

    def test_condition_type_sorted_by_name(self):
        """조건 이벤트는 이름순"""
        events = [
            EventModel(event_name="Zulu", execute_action=False, key_to_enter="B"),
            EventModel(event_name="Alpha", execute_action=False, key_to_enter="A"),
        ]
        stub = self._make_sortable_stub(events)
        sorted_events = sorted(events, key=lambda e: self._key_sort_key(stub, e))
        self.assertEqual([e.event_name for e in sorted_events], ["Alpha", "Zulu"])

    def test_same_key_order_falls_back_to_name(self):
        """입력 키가 같으면 이름으로 안정 정렬"""
        events = [
            EventModel(event_name="Zebra", execute_action=True, key_to_enter="A"),
            EventModel(event_name="Apple", execute_action=True, key_to_enter="A"),
        ]
        stub = self._make_sortable_stub(events)
        sorted_events = sorted(events, key=lambda e: self._key_sort_key(stub, e))
        self.assertEqual([e.event_name for e in sorted_events], ["Apple", "Zebra"])

    def test_name_sort_uses_name_within_action_type(self):
        events = [
            EventModel(event_name="Zulu", execute_action=True, key_to_enter="A"),
            EventModel(event_name="Alpha", execute_action=True, key_to_enter="B"),
        ]
        stub = self._make_sortable_stub(events)
        sorted_events = sorted(events, key=lambda e: self._name_sort_key(stub, e))
        self.assertEqual([e.event_name for e in sorted_events], ["Alpha", "Zulu"])

    def test_type_order_applies_before_name(self):
        """이름보다 타입 우선 정렬"""
        events = [
            EventModel(event_name="Alpha", execute_action=True, key_to_enter="A"),
            EventModel(event_name="Zulu", execute_action=False, key_to_enter=None),
        ]
        stub = self._make_sortable_stub(events)
        sorted_events = sorted(events, key=lambda e: self._name_sort_key(stub, e))
        self.assertEqual([e.event_name for e in sorted_events], ["Zulu", "Alpha"])

    def test_sort_events_by_key_uses_default_language_dialog_message(self):
        events = [
            EventModel(event_name="B", execute_action=True, key_to_enter="B"),
            EventModel(event_name="A", execute_action=False, key_to_enter=None),
        ]
        stub = self._make_sortable_stub(events)
        stub.win = object()
        stub.save_names = lambda: None
        stub.update_events = lambda: None
        stub.save_cb = lambda *args, **kwargs: None

        with patch("app.ui.profiles.messagebox.showinfo") as mock_show:
            stub._sort_events_by_key()

        mock_show.assert_called_once()
        args, kwargs = mock_show.call_args
        self.assertEqual(args[0], "Key Sort Complete")
        self.assertIn("Condition", args[1])
        self.assertIn("Input Key", args[1])
        self.assertEqual(kwargs["parent"], stub.win)

    def test_sort_events_by_name_uses_default_language_dialog_message(self):
        events = [
            EventModel(event_name="B", execute_action=True, key_to_enter="B"),
            EventModel(event_name="A", execute_action=False, key_to_enter=None),
        ]
        stub = self._make_sortable_stub(events)
        stub.win = object()
        stub.save_names = lambda: None
        stub.update_events = lambda: None
        stub.save_cb = lambda *args, **kwargs: None

        with patch("app.ui.profiles.messagebox.showinfo") as mock_show:
            stub._sort_events_by_name()

        mock_show.assert_called_once()
        args, kwargs = mock_show.call_args
        self.assertEqual(args[0], "Name Sort Complete")
        self.assertIn("Event Type", args[1])
        self.assertIn("Name", args[1])
        self.assertEqual(kwargs["parent"], stub.win)


class TestEventRowBadges(unittest.TestCase):
    def _make_row(self, event: EventModel):
        set_language("en")
        row = EventRow.__new__(EventRow)
        row.event = event
        row.use_var = FakeVar()
        row.entry = FakeEntry(text="")
        row.lbl_cond = FakeWidget(text="")
        row.lbl_grp = FakeWidget(text="")
        row.lbl_key = FakeWidget(text="")
        row._tip_cond = FakeToolTip()
        row._tip_grp = FakeToolTip()
        row._tip_key = FakeToolTip()
        row._last_saved_name = ""
        return row

    def test_row_displays_condition_badges(self):
        evt = EventModel(
            event_name="Evt",
            execute_action=False,
            group_id="G1",
            key_to_enter="A",
        )
        row = self._make_row(evt)

        row.update_display()

        self.assertEqual(row.lbl_cond.cget("text"), "🔎 Cond")
        self.assertEqual(row.lbl_grp.cget("text"), "G1")
        self.assertEqual(row.lbl_key.cget("text"), "🔎 Condition")
        self.assertEqual(row.entry.cget("foreground"), "gray")

    def test_row_displays_invert_and_missing_key_badges(self):
        evt = EventModel(
            event_name="Evt",
            execute_action=True,
            invert_match=True,
            key_to_enter=None,
        )
        row = self._make_row(evt)

        row.update_display()

        self.assertEqual(row.lbl_key.cget("text"), "🔁 ⌨️ None")
        self.assertIn("Invert match", row._tip_key.text)


class TestProfileOverviewBadges(unittest.TestCase):
    def _make_profile_stub(self, events):
        set_language("en")
        stub = KeystrokeProfiles.__new__(KeystrokeProfiles)
        stub.profile = ProfileModel(name="Test", event_list=events)
        stub.main_win = type(
            "MainWinStub",
            (),
            {
                "settings": type(
                    "SettingsStub",
                    (),
                    {
                        "toggle_start_stop_mac": False,
                        "use_alt_shift_hotkey": False,
                        "start_stop_key": "DISABLED",
                    },
                )()
            },
        )()
        stub.lbl_events_badge = FakeWidget()
        stub.lbl_groups_badge = FakeWidget()
        stub.lbl_attention_badge = FakeWidget()
        stub.lbl_save_badge = FakeWidget()
        stub.lbl_status = FakeWidget()
        stub._overview_status_text = ""
        return stub

    def test_refresh_profile_overview_updates_counts(self):
        events = [
            EventModel(event_name="A", group_id="G1", execute_action=False),
            EventModel(
                event_name="B", group_id="G2", execute_action=True, key_to_enter=None
            ),
            EventModel(event_name="C", execute_action=True, key_to_enter="X"),
        ]
        stub = self._make_profile_stub(events)

        stub._refresh_profile_overview()

        self.assertEqual(stub.lbl_events_badge.cget("text"), "⚙️ Events 3")
        self.assertEqual(stub.lbl_groups_badge.cget("text"), "🧩 Groups 2")
        self.assertEqual(stub.lbl_attention_badge.cget("text"), "⚠ Attention 1")
        self.assertIn("missing key: 1", stub._overview_status_text)

    def test_refresh_profile_overview_treats_condition_only_as_normal_info(self):
        stub = self._make_profile_stub(
            [EventModel(event_name="A", execute_action=False)]
        )

        stub._refresh_profile_overview()

        self.assertEqual(stub.lbl_attention_badge.cget("text"), "✅ Attention 0")
        self.assertEqual(
            stub._overview_status_text,
            "Condition-only events are configured: 1.",
        )

    def test_refresh_profile_overview_sets_ok_detail_when_attention_zero(self):
        stub = self._make_profile_stub(
            [EventModel(event_name="A", execute_action=True, key_to_enter="X")]
        )

        stub._refresh_profile_overview()

        self.assertEqual(stub.lbl_attention_badge.cget("text"), "✅ Attention 0")
        self.assertEqual(
            stub._overview_status_text,
            "All events are ready for autosave and run checks.",
        )

    def test_refresh_profile_overview_includes_runtime_toggle_conflict(self):
        stub = self._make_profile_stub(
            [
                EventModel(event_name="Base", execute_action=True, key_to_enter="F6"),
                EventModel(
                    event_name="Extra",
                    execute_action=True,
                    key_to_enter="A",
                    runtime_toggle_member=True,
                ),
            ]
        )
        stub.profile.runtime_toggle_enabled = True
        stub.profile.runtime_toggle_key = "F6"

        stub._refresh_profile_overview()

        self.assertEqual(stub.lbl_attention_badge.cget("text"), "⚠ Attention 1")
        self.assertIn("conflicts with event input key 'F6'", stub._overview_status_text)

    def test_save_status_badge_prefixes(self):
        stub = self._make_profile_stub([EventModel(event_name="A", key_to_enter="X")])

        stub._set_save_status("saving")
        self.assertEqual(stub.lbl_save_badge.cget("text"), "💾 Saving...")

        stub._set_save_status("error", "bad")
        self.assertEqual(stub.lbl_save_badge.cget("text"), "⚠ Save failed")
        self.assertEqual(stub.lbl_status.cget("text"), "bad")

    def test_saved_status_uses_overview_text_when_detail_missing(self):
        stub = self._make_profile_stub([EventModel(event_name="A", key_to_enter="X")])

        with patch("app.ui.profiles.time.strftime", return_value="12:34:56"):
            stub._set_save_status("saved")

        self.assertEqual(stub.lbl_save_badge.cget("text"), "✅ Saved 12:34:56")
        self.assertEqual(
            stub.lbl_status.cget("text"),
            "All events are ready for autosave and run checks.",
        )


class TestProfileSaveValidation(unittest.TestCase):
    def test_save_rejects_duplicate_event_names(self):
        set_language("en")
        stub = KeystrokeProfiles.__new__(KeystrokeProfiles)
        stub.profile = ProfileModel(
            name="Test",
            event_list=[
                EventModel(event_name="A", key_to_enter="X"),
                EventModel(event_name="A", key_to_enter="Y"),
            ],
            favorite=False,
        )
        stub.prof_name = "Test"
        stub.prof_dir = Path(".")
        stub.p_frame = MagicMock(get_data=lambda: ("Test", False))
        stub._last_saved_fingerprint = None
        stub.ext_save_cb = None

        with self.assertRaisesRegex(ValueError, "Duplicate event names"):
            stub._save(check_name=True, reload=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
