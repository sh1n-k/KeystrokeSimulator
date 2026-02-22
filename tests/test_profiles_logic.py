import unittest
from unittest.mock import patch

from keystroke_models import EventModel, ProfileModel
from keystroke_profiles import EventListFrame, EventRow, KeystrokeProfiles
from i18n import set_language


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


class TestSortEventsLogic(unittest.TestCase):
    """이벤트 정렬 로직 검증"""

    def _make_sortable_stub(self, events):
        set_language("en")
        stub = _make_event_list_frame_stub()
        stub.profile = ProfileModel(event_list=events)
        return stub

    def _sort_key(self, stub, e):
        """_sort_events 내부 sort_key 람다 재현"""
        is_indep = 0 if getattr(e, "independent_thread", False) else 1
        grp = getattr(e, "group_id", "") or ""
        grp_order = 0 if grp else 1
        prio = getattr(e, "priority", 0)
        key_order = stub._get_key_sort_order(e.key_to_enter)
        name = e.event_name or ""
        return (is_indep, grp_order, grp, prio, key_order, name)

    def test_independent_thread_first(self):
        """independent_thread=True 이벤트가 먼저"""
        events = [
            EventModel(event_name="Normal", independent_thread=False, key_to_enter="A"),
            EventModel(event_name="Indep", independent_thread=True, key_to_enter="B"),
        ]
        stub = self._make_sortable_stub(events)
        sorted_events = sorted(events, key=lambda e: self._sort_key(stub, e))
        self.assertEqual(sorted_events[0].event_name, "Indep")

    def test_group_before_no_group(self):
        """그룹 있는 이벤트가 그룹 없는 이벤트보다 먼저"""
        events = [
            EventModel(event_name="NoGroup", group_id=None, key_to_enter="A"),
            EventModel(event_name="HasGroup", group_id="G1", key_to_enter="A"),
        ]
        stub = self._make_sortable_stub(events)
        sorted_events = sorted(events, key=lambda e: self._sort_key(stub, e))
        self.assertEqual(sorted_events[0].event_name, "HasGroup")

    def test_same_group_by_priority(self):
        """같은 그룹 내 priority 순 (오름차순)"""
        events = [
            EventModel(event_name="Low", group_id="G1", priority=10, key_to_enter="A"),
            EventModel(event_name="High", group_id="G1", priority=1, key_to_enter="A"),
        ]
        stub = self._make_sortable_stub(events)
        sorted_events = sorted(events, key=lambda e: self._sort_key(stub, e))
        self.assertEqual(sorted_events[0].event_name, "High")

    def test_key_order_digit_before_alpha_before_function(self):
        """키 순서: 숫자 < 알파벳 < 펑션키"""
        events = [
            EventModel(event_name="Alpha", group_id="G1", priority=0, key_to_enter="A"),
            EventModel(event_name="Func", group_id="G1", priority=0, key_to_enter="F1"),
            EventModel(event_name="Digit", group_id="G1", priority=0, key_to_enter="3"),
        ]
        stub = self._make_sortable_stub(events)
        sorted_events = sorted(events, key=lambda e: self._sort_key(stub, e))
        self.assertEqual([e.event_name for e in sorted_events], ["Digit", "Alpha", "Func"])

    def test_same_conditions_by_name(self):
        """모든 조건 동일 시 이름순"""
        events = [
            EventModel(event_name="Zebra", group_id="G1", priority=0, key_to_enter="A"),
            EventModel(event_name="Apple", group_id="G1", priority=0, key_to_enter="A"),
        ]
        stub = self._make_sortable_stub(events)
        sorted_events = sorted(events, key=lambda e: self._sort_key(stub, e))
        self.assertEqual(sorted_events[0].event_name, "Apple")

    def test_sort_events_uses_default_language_dialog_message(self):
        events = [
            EventModel(event_name="B", key_to_enter="B"),
            EventModel(event_name="A", key_to_enter="A"),
        ]
        stub = self._make_sortable_stub(events)
        stub.win = object()
        stub.save_names = lambda: None
        stub.update_events = lambda: None
        stub.save_cb = lambda *args, **kwargs: None

        with patch("keystroke_profiles.messagebox.showinfo") as mock_show:
            stub._sort_events()

        mock_show.assert_called_once()
        args, kwargs = mock_show.call_args
        self.assertEqual(args[0], "Auto Sort Complete")
        self.assertIn("Events were sorted by:", args[1])
        self.assertEqual(kwargs["parent"], stub.win)


class TestEventRowBadges(unittest.TestCase):
    def _make_row(self, event: EventModel):
        set_language("en")
        row = EventRow.__new__(EventRow)
        row.event = event
        row.use_var = FakeVar()
        row.entry = FakeEntry(text="")
        row.lbl_indep = FakeWidget(text="")
        row.lbl_cond = FakeWidget(text="")
        row.lbl_grp = FakeWidget(text="")
        row.lbl_key = FakeWidget(text="")
        row._tip_indep = FakeToolTip()
        row._tip_cond = FakeToolTip()
        row._tip_grp = FakeToolTip()
        row._tip_key = FakeToolTip()
        row._last_saved_name = ""
        return row

    def test_row_displays_independent_and_condition_badges(self):
        evt = EventModel(
            event_name="Evt",
            independent_thread=True,
            execute_action=False,
            group_id="G1",
            key_to_enter="A",
        )
        row = self._make_row(evt)

        row.update_display()

        self.assertEqual(row.lbl_indep.cget("text"), "🧵 Indep")
        self.assertEqual(row.lbl_cond.cget("text"), "🔎 Cond")
        self.assertEqual(row.lbl_grp.cget("text"), "G1")
        self.assertEqual(row.lbl_key.cget("text"), "A")
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
        stub.lbl_events_badge = FakeWidget()
        stub.lbl_groups_badge = FakeWidget()
        stub.lbl_attention_badge = FakeWidget()
        stub.lbl_save_badge = FakeWidget()
        stub.lbl_status = FakeWidget()
        return stub

    def test_refresh_profile_overview_updates_counts(self):
        events = [
            EventModel(event_name="A", group_id="G1", execute_action=False),
            EventModel(event_name="B", group_id="G2", execute_action=True, key_to_enter=None),
            EventModel(event_name="C", execute_action=True, key_to_enter="X"),
        ]
        stub = self._make_profile_stub(events)

        stub._refresh_profile_overview()

        self.assertEqual(stub.lbl_events_badge.cget("text"), "⚙️ Events 3")
        self.assertEqual(stub.lbl_groups_badge.cget("text"), "🧩 Groups 2")
        self.assertEqual(stub.lbl_attention_badge.cget("text"), "⚠ Attention 2")

    def test_save_status_badge_prefixes(self):
        stub = self._make_profile_stub([EventModel(event_name="A", key_to_enter="X")])

        stub._set_save_status("saving")
        self.assertEqual(stub.lbl_save_badge.cget("text"), "💾 Saving...")

        stub._set_save_status("error", "bad")
        self.assertEqual(stub.lbl_save_badge.cget("text"), "⚠ Save failed")
        self.assertEqual(stub.lbl_status.cget("text"), "bad")


if __name__ == "__main__":
    unittest.main(verbosity=2)
