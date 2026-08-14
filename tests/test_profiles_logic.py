import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core.models import EventModel, ProfileModel
from app.ui import theme
from app.ui.profile_event_list import (
    EventListFrame,
    EventRow,
    resolve_selection,
    selection_mode_for_state,
)
from app.core.profile_events import (
    EventFilterState,
    event_group_key_sort_key,
    event_group_name_sort_key,
    event_needs_attention,
    filter_event_indices,
)
from app.ui.profiles import KeystrokeProfiles, _profile_fingerprint
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


class FakeBoolVar:
    def __init__(self, value=False):
        self.value = bool(value)

    def get(self):
        return self.value

    def set(self, value):
        self.value = bool(value)


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


class TestEventListDialogParent(unittest.TestCase):
    def test_resolve_dialog_parent_prefers_host_window(self):
        packing = object()
        host = object()
        self.assertIs(
            EventListFrame.resolve_dialog_parent(packing, host),  # type: ignore[arg-type]
            host,
        )

    def test_resolve_dialog_parent_falls_back_to_packing_parent(self):
        packing = object()
        self.assertIs(
            EventListFrame.resolve_dialog_parent(packing, None),  # type: ignore[arg-type]
            packing,
        )


class TestProfileGraphViewerGrabOwner(unittest.TestCase):
    def test_only_toplevel_parents_own_grab(self):
        from app.ui.profile_graph_viewer import ProfileGraphViewer

        viewer = ProfileGraphViewer.__new__(ProfileGraphViewer)
        viewer.parent = object()
        self.assertFalse(ProfileGraphViewer._parent_can_own_grab(viewer))

        class FakeTop:
            pass

        # isinstance check against real Tk types: non-Tk objects are false.
        viewer.parent = FakeTop()
        self.assertFalse(ProfileGraphViewer._parent_can_own_grab(viewer))


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
        stub.reveal_event = MagicMock()

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
        stub.reveal_event = MagicMock()

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
        stub.reveal_event = MagicMock()

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
        with patch("app.ui.profile_event_list.messagebox.showerror") as mock_error:
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
        row.last_saved_name = "OldName"
        row._bound_event_id = id(renamed)
        row.cbs = {"save": lambda: None}

        EventRow._on_name_changed(row)
        row.update_display()

        frame.rows = [row]
        frame.save_names()

        self.assertEqual(frame.profile.event_list[0].event_name, "NewName")
        self.assertEqual(dependent.conditions, {"NewName": True})


def _make_deletable_stub(events):
    """삭제/되돌리기 경로를 실행할 수 있는 EventListFrame stub."""
    set_language("en")
    stub = _make_event_list_frame_stub()
    stub.profile = ProfileModel(event_list=events)
    stub.rows = [FakeDestroyable() for _ in events]
    stub.selected_indices = set()
    stub.selection_anchor = None
    stub._undo_delete = None
    stub.update_events = MagicMock()
    stub._update_row_indices = MagicMock()
    stub._update_delete_buttons = MagicMock()
    stub._sync_empty_state = MagicMock()
    stub._sync_row_selection = MagicMock()
    stub._sync_bulk_bar = MagicMock()
    stub.select_cb = None
    stub.status_cb = MagicMock()
    stub.save_cb = MagicMock()
    stub.win = type("FakeWin", (), {"update_idletasks": lambda self: None})()
    return stub


class TestRemoveRowConditionCleanup(unittest.TestCase):
    """EventListFrame._remove_row: 삭제 시 조건 참조 정리"""

    def test_remove_row_cleans_orphaned_condition_references(self):
        dependent = EventModel(event_name="B", conditions={"A": True, "Other": False})
        stub = _make_deletable_stub(
            [EventModel(event_name="A"), dependent, EventModel(event_name="C")]
        )

        stub._remove_row(stub.rows[0], 0)

        self.assertEqual([e.event_name for e in stub.profile.event_list], ["B", "C"])
        self.assertEqual(dependent.conditions, {"Other": False})
        stub.save_cb.assert_called_once()

    def test_remove_row_preserves_conditions_when_same_name_still_exists(self):
        dependent = EventModel(event_name="B", conditions={"A": True})
        stub = _make_deletable_stub(
            [
                EventModel(event_name="A"),
                EventModel(event_name="A"),
                dependent,
            ]
        )

        stub._remove_row(stub.rows[0], 0)

        self.assertEqual(dependent.conditions, {"A": True})

    def test_remove_row_keeps_the_last_remaining_event(self):
        stub = _make_deletable_stub([EventModel(event_name="Only")])

        stub._remove_row(stub.rows[0], 0)

        self.assertEqual(len(stub.profile.event_list), 1)


class TestDeleteUndo(unittest.TestCase):
    """삭제는 되돌릴 수 있어야 한다 (자동저장이라 확인 대화상자만으로는 부족)."""

    def test_undo_restores_the_deleted_event_at_its_position(self):
        stub = _make_deletable_stub(
            [
                EventModel(event_name="A"),
                EventModel(event_name="B"),
                EventModel(event_name="C"),
            ]
        )

        stub._delete_indices([1])
        self.assertEqual([e.event_name for e in stub.profile.event_list], ["A", "C"])

        self.assertTrue(stub.undo_delete())
        self.assertEqual(
            [e.event_name for e in stub.profile.event_list], ["A", "B", "C"]
        )

    def test_undo_restores_condition_references_stripped_by_the_delete(self):
        dependent = EventModel(event_name="B", conditions={"A": True, "Other": False})
        stub = _make_deletable_stub([EventModel(event_name="A"), dependent])

        stub._delete_indices([0])
        self.assertEqual(dependent.conditions, {"Other": False})

        stub.undo_delete()

        self.assertEqual(dependent.conditions, {"A": True, "Other": False})

    def test_undo_restores_a_multi_selection_delete(self):
        stub = _make_deletable_stub(
            [
                EventModel(event_name="A"),
                EventModel(event_name="B"),
                EventModel(event_name="C"),
                EventModel(event_name="D"),
            ]
        )

        stub._delete_indices([0, 2])
        self.assertEqual([e.event_name for e in stub.profile.event_list], ["B", "D"])

        stub.undo_delete()

        self.assertEqual(
            [e.event_name for e in stub.profile.event_list], ["A", "B", "C", "D"]
        )

    def test_delete_offers_undo_through_the_status_line(self):
        stub = _make_deletable_stub(
            [EventModel(event_name="A"), EventModel(event_name="B")]
        )

        stub._delete_indices([0])

        _, kwargs = stub.status_cb.call_args
        self.assertEqual(kwargs["action_label"], "Undo")
        kwargs["action"]()
        self.assertEqual([e.event_name for e in stub.profile.event_list], ["A", "B"])

    def test_undo_is_a_no_op_without_a_pending_delete(self):
        stub = _make_deletable_stub([EventModel(event_name="A")])

        self.assertFalse(stub.undo_delete())

    def test_bulk_delete_never_empties_the_profile(self):
        stub = _make_deletable_stub(
            [EventModel(event_name="A"), EventModel(event_name="B")]
        )

        removed = stub._delete_indices([0, 1])

        self.assertEqual(removed, 1)
        self.assertEqual(len(stub.profile.event_list), 1)


class TestSortEventsLogic(unittest.TestCase):
    """이벤트 정렬 로직 검증"""

    def _make_sortable_stub(self, events):
        set_language("en")
        stub = _make_event_list_frame_stub()
        stub.profile = ProfileModel(event_list=events)
        return stub

    def _make_running_sort_stub(self, events):
        """정렬을 실제로 실행할 수 있는 stub (상태줄 콜백 포함)."""
        stub = self._make_sortable_stub(events)
        stub.win = object()
        stub.save_names = lambda: None
        stub.update_events = lambda: None
        stub.save_cb = lambda *args, **kwargs: None
        stub.clear_selection = lambda: None
        stub.status_cb = MagicMock()
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

    def test_sort_by_key_reports_in_the_status_line(self):
        events = [
            EventModel(event_name="B", execute_action=True, key_to_enter="B"),
            EventModel(event_name="A", execute_action=False, key_to_enter=None),
        ]
        stub = self._make_running_sort_stub(events)

        with patch("app.ui.profile_event_list.messagebox.showinfo") as mock_show:
            stub._sort_events_by_key()

        mock_show.assert_not_called()
        stub.status_cb.assert_called_once_with("Key Sort Complete")

    def test_sort_by_name_reports_in_the_status_line(self):
        events = [
            EventModel(event_name="B", execute_action=True, key_to_enter="B"),
            EventModel(event_name="A", execute_action=False, key_to_enter=None),
        ]
        stub = self._make_running_sort_stub(events)

        with patch("app.ui.profile_event_list.messagebox.showinfo") as mock_show:
            stub._sort_events_by_name()

        mock_show.assert_not_called()
        stub.status_cb.assert_called_once_with("Name Sort Complete")
        self.assertEqual([e.event_name for e in stub.profile.event_list], ["A", "B"])

    def test_sort_falls_back_to_a_dialog_without_a_status_line(self):
        events = [
            EventModel(event_name="B", execute_action=True, key_to_enter="B"),
            EventModel(event_name="A", execute_action=False, key_to_enter=None),
        ]
        stub = self._make_running_sort_stub(events)
        stub.status_cb = None

        with patch("app.ui.profile_event_list.messagebox.showinfo") as mock_show:
            stub._sort_events_by_name()

        mock_show.assert_called_once()
        args, kwargs = mock_show.call_args
        self.assertEqual(args[0], "Name Sort Complete")
        self.assertEqual(kwargs["parent"], stub.win)

    def test_group_name_sort_clusters_groups_then_names(self):
        events = [
            EventModel(event_name="Solo", group_id=None),
            EventModel(event_name="B2", group_id="Beta"),
            EventModel(event_name="A2", group_id="Alpha"),
            EventModel(event_name="B1", group_id="Beta"),
            EventModel(event_name="A1", group_id="Alpha"),
        ]
        ordered = sorted(events, key=event_group_name_sort_key)
        self.assertEqual(
            [e.event_name for e in ordered],
            ["A1", "A2", "B1", "B2", "Solo"],
        )

    def test_group_key_sort_uses_key_order_inside_group(self):
        events = [
            EventModel(event_name="Zulu", group_id="G", key_to_enter="B"),
            EventModel(event_name="Alpha", group_id="G", key_to_enter="A"),
            EventModel(event_name="Solo", group_id=None, key_to_enter="1"),
        ]
        ordered = sorted(events, key=event_group_key_sort_key)
        self.assertEqual([e.event_name for e in ordered], ["Alpha", "Zulu", "Solo"])

    def test_sort_by_group_name_reports_in_the_status_line(self):
        events = [
            EventModel(event_name="B", group_id="G", execute_action=True),
            EventModel(event_name="A", group_id=None, execute_action=False),
        ]
        stub = self._make_running_sort_stub(events)

        stub._sort_events_by_group_name()

        stub.status_cb.assert_called_once_with("Group / Name Sort Complete")
        self.assertEqual(
            [e.event_name for e in stub.profile.event_list],
            ["B", "A"],
        )

    def test_sort_by_group_key_reports_in_the_status_line(self):
        events = [
            EventModel(event_name="B", group_id="G", key_to_enter="B"),
            EventModel(event_name="A", group_id="G", key_to_enter="A"),
        ]
        stub = self._make_running_sort_stub(events)

        stub._sort_events_by_group_key()

        stub.status_cb.assert_called_once_with("Group / Key Sort Complete")
        self.assertEqual(
            [e.event_name for e in stub.profile.event_list],
            ["A", "B"],
        )


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
        row.last_saved_name = ""
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

        self.assertEqual(row.lbl_cond.cget("text"), "◐ Cond")
        self.assertEqual(row.lbl_grp.cget("text"), "▣ G1")
        self.assertEqual(row.lbl_key.cget("text"), "◐ Cond")
        self.assertEqual(row.entry.cget("foreground"), theme.INK_MUTED)

    def test_row_displays_invert_and_missing_key_badges(self):
        evt = EventModel(
            event_name="Evt",
            execute_action=True,
            invert_match=True,
            key_to_enter=None,
        )
        row = self._make_row(evt)

        row.update_display()

        self.assertEqual(row.lbl_key.cget("text"), "⇄ ⌨ None")
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

    def test_save_badge_flash_skips_destroyed_widget(self):
        stub = KeystrokeProfiles.__new__(KeystrokeProfiles)
        stub.lbl_save_badge = MagicMock()
        stub.lbl_save_badge.winfo_exists.return_value = False

        stub._set_save_badge_bg("#fff")

        stub.lbl_save_badge.config.assert_not_called()


class TestProfileNavRailFilters(unittest.TestCase):
    """NavRail은 액션이 아니라 필터를 소유한다 (액션은 리스트 툴바로 일원화)."""

    def _make_stub(self, events=None):
        set_language("en")
        stub = KeystrokeProfiles.__new__(KeystrokeProfiles)
        stub.profile = ProfileModel(event_list=events or [])
        stub.filter_state = EventFilterState()
        stub.e_frame = MagicMock()
        stub.nav_filter_vars = {
            key: FakeBoolVar() for key in ("active", "grouped", "cond", "attention")
        }
        stub._refresh_nav_groups = MagicMock()
        return stub

    def test_rail_no_longer_exposes_action_forwards(self):
        for removed in (
            "_nav_action_add",
            "_nav_action_import",
            "_nav_action_sort",
            "_nav_action_graph",
        ):
            self.assertFalse(
                hasattr(KeystrokeProfiles, removed),
                f"{removed} should be gone: actions live in the list toolbar",
            )

    def test_checkbox_state_reaches_the_event_list(self):
        stub = self._make_stub()
        stub.nav_filter_vars["cond"].set(True)

        stub._on_nav_filter_changed()

        self.assertTrue(stub.filter_state.condition_only)
        stub.e_frame.set_filter_state.assert_called_once_with(stub.filter_state)

    def test_group_click_toggles_that_group(self):
        stub = self._make_stub()

        stub._toggle_group_filter("Alpha")
        self.assertEqual(stub.filter_state.group_ids, frozenset({"Alpha"}))

        stub._toggle_group_filter("Alpha")
        self.assertEqual(stub.filter_state.group_ids, frozenset())

    def test_search_query_survives_a_rail_toggle(self):
        stub = self._make_stub()
        stub.filter_state = EventFilterState(query="atk")
        stub.nav_filter_vars["active"].set(True)

        stub._on_nav_filter_changed()

        self.assertEqual(stub.filter_state.query, "atk")
        self.assertTrue(stub.filter_state.active_only)

    def test_attention_badge_click_filters_to_events_missing_a_key(self):
        stub = self._make_stub(
            [
                EventModel(event_name="A", execute_action=True, key_to_enter=None),
                EventModel(event_name="B", execute_action=True, key_to_enter="X"),
            ]
        )

        stub._on_attention_badge_click()

        self.assertTrue(stub.filter_state.attention_only)

    def test_attention_badge_click_is_inert_when_nothing_needs_attention(self):
        stub = self._make_stub(
            [EventModel(event_name="B", execute_action=True, key_to_enter="X")]
        )

        stub._on_attention_badge_click()

        self.assertFalse(stub.filter_state.attention_only)
        stub.e_frame.set_filter_state.assert_not_called()


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

    def test_save_allows_empty_event_list(self):
        set_language("en")
        stub = KeystrokeProfiles.__new__(KeystrokeProfiles)
        stub.profile = ProfileModel(name="Quick", event_list=[], favorite=False)
        stub.prof_name = "Quick"
        stub.prof_dir = Path(".")
        stub.p_frame = MagicMock(get_data=lambda: ("Quick", False))
        stub._last_saved_fingerprint = _profile_fingerprint(
            stub.profile, "Quick", False
        )
        stub.ext_save_cb = None
        stub.runtime_toggle_frame = None

        with patch("app.ui.profiles.save_profile") as mock_save:
            renamed = stub._save(check_name=True, reload=False)

        self.assertFalse(renamed)
        mock_save.assert_not_called()


class TestEventFiltering(unittest.TestCase):
    """검색/필터는 순수 함수라 GUI 없이 검증한다."""

    def setUp(self):
        set_language("en")
        self.events = [
            EventModel(
                event_name="Attack", key_to_enter="A", group_id="Combat", use_event=True
            ),
            EventModel(
                event_name="Heal", key_to_enter="H", group_id=None, use_event=False
            ),
            EventModel(
                event_name="Watch HP",
                execute_action=False,
                key_to_enter=None,
                group_id="Combat",
            ),
            EventModel(
                event_name="Broken", execute_action=True, key_to_enter=None, group_id=None
            ),
        ]

    def test_no_filter_shows_everything(self):
        state = EventFilterState()
        self.assertFalse(state.is_active())
        self.assertEqual(filter_event_indices(self.events, state), [0, 1, 2, 3])

    def test_query_matches_name_key_and_group(self):
        self.assertEqual(
            filter_event_indices(self.events, EventFilterState(query="att")), [0]
        )
        self.assertEqual(
            filter_event_indices(self.events, EventFilterState(query="combat")), [0, 2]
        )
        self.assertEqual(
            filter_event_indices(self.events, EventFilterState(query="h")), [1, 2]
        )

    def test_query_is_case_insensitive_and_trimmed(self):
        self.assertEqual(
            filter_event_indices(self.events, EventFilterState(query="  ATTACK ")), [0]
        )

    def test_active_only_keeps_checked_events(self):
        self.assertEqual(
            filter_event_indices(self.events, EventFilterState(active_only=True)),
            [0, 2, 3],
        )

    def test_grouped_only_keeps_events_with_a_group(self):
        self.assertEqual(
            filter_event_indices(self.events, EventFilterState(grouped_only=True)),
            [0, 2],
        )

    def test_condition_only_keeps_non_action_events(self):
        self.assertEqual(
            filter_event_indices(self.events, EventFilterState(condition_only=True)), [2]
        )

    def test_attention_only_keeps_action_events_without_a_key(self):
        self.assertEqual(
            filter_event_indices(self.events, EventFilterState(attention_only=True)), [3]
        )

    def test_group_ids_restrict_to_the_picked_groups(self):
        state = EventFilterState(group_ids=frozenset({"Combat"}))
        self.assertEqual(filter_event_indices(self.events, state), [0, 2])

    def test_filters_combine_with_and(self):
        state = EventFilterState(
            query="watch", group_ids=frozenset({"Combat"}), condition_only=True
        )
        self.assertEqual(filter_event_indices(self.events, state), [2])

    def test_conflicting_filters_yield_nothing(self):
        state = EventFilterState(condition_only=True, attention_only=True)
        self.assertEqual(filter_event_indices(self.events, state), [])

    def test_condition_only_events_never_need_attention(self):
        self.assertFalse(event_needs_attention(self.events[2]))
        self.assertTrue(event_needs_attention(self.events[3]))

    def test_whitespace_key_still_needs_attention(self):
        self.assertTrue(
            event_needs_attention(EventModel(event_name="X", key_to_enter="   "))
        )


class TestSelectionGestures(unittest.TestCase):
    """다중선택 제스처는 순수 함수로 분리해 검증한다."""

    def test_plain_click_replaces_the_selection(self):
        selection, anchor = resolve_selection({1, 2}, 1, 5, "replace")
        self.assertEqual(selection, {5})
        self.assertEqual(anchor, 5)

    def test_toggle_adds_and_removes(self):
        selection, _ = resolve_selection({1}, 1, 3, "toggle")
        self.assertEqual(selection, {1, 3})
        selection, _ = resolve_selection(selection, 3, 1, "toggle")
        self.assertEqual(selection, {3})

    def test_range_spans_from_the_anchor_in_either_direction(self):
        selection, anchor = resolve_selection({2}, 2, 5, "range")
        self.assertEqual(selection, {2, 3, 4, 5})
        self.assertEqual(anchor, 2)

        selection, _ = resolve_selection({5}, 5, 2, "range")
        self.assertEqual(selection, {2, 3, 4, 5})

    def test_range_without_an_anchor_behaves_like_a_plain_click(self):
        selection, anchor = resolve_selection(set(), None, 4, "range")
        self.assertEqual(selection, {4})
        self.assertEqual(anchor, 4)

    def test_modifier_bits_map_to_gestures(self):
        self.assertEqual(selection_mode_for_state(0), "replace")
        self.assertEqual(selection_mode_for_state(0x0001), "range")
        self.assertEqual(selection_mode_for_state(0x0004), "toggle")

    def test_shift_wins_over_control(self):
        self.assertEqual(selection_mode_for_state(0x0005), "range")


class TestBulkActions(unittest.TestCase):
    """선택한 여러 이벤트를 한 번에 바꾼다."""

    def _make_stub(self):
        stub = _make_deletable_stub(
            [
                EventModel(event_name="A", use_event=True),
                EventModel(event_name="B", use_event=True),
                EventModel(event_name="C", use_event=True),
            ]
        )
        stub.selected_indices = {0, 2}
        return stub

    def test_bulk_use_off_only_touches_the_selection(self):
        stub = self._make_stub()

        stub._bulk_set_use(False)

        self.assertEqual(
            [e.use_event for e in stub.profile.event_list], [False, True, False]
        )

    def test_bulk_toggle_set_adds_when_any_member_is_missing(self):
        stub = self._make_stub()
        stub.profile.event_list[0].runtime_toggle_member = True

        stub._bulk_toggle_runtime_member()

        self.assertEqual(
            [e.runtime_toggle_member for e in stub.profile.event_list],
            [True, False, True],
        )

    def test_bulk_toggle_set_removes_when_all_are_members(self):
        stub = self._make_stub()
        for index in (0, 2):
            stub.profile.event_list[index].runtime_toggle_member = True

        stub._bulk_toggle_runtime_member()

        self.assertEqual(
            [e.runtime_toggle_member for e in stub.profile.event_list],
            [False, False, False],
        )

    def test_bulk_actions_are_inert_without_a_selection(self):
        stub = self._make_stub()
        stub.selected_indices = set()

        stub._bulk_set_use(False)

        self.assertEqual([e.use_event for e in stub.profile.event_list], [True] * 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
