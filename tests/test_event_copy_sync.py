import copy
import dataclasses
import unittest

from PIL import Image

from keystroke_event_importer import EventImporter
from keystroke_models import EventModel


def _make_importer_stub() -> EventImporter:
    """GUI 없이 _copy_event만 테스트하기 위한 stub"""
    return EventImporter.__new__(EventImporter)


class TestEventCopySync(unittest.TestCase):
    """_copy_event: EventModel 필드 동기화 검증"""

    def _make_full_event(self) -> EventModel:
        """모든 필드가 채워진 테스트용 이벤트"""
        evt = EventModel(
            event_name="TestEvent",
            latest_position=(100, 200),
            clicked_position=(10, 20),
            latest_screenshot=Image.new("RGB", (5, 5), color=(1, 2, 3)),
            held_screenshot=Image.new("RGB", (10, 10), color=(10, 20, 30)),
            ref_pixel_value=(10, 20, 30),
            key_to_enter="F5",
            press_duration_ms=150.0,
            randomization_ms=50.0,
            independent_thread=True,
            match_mode="region",
            invert_match=True,
            region_size=(20, 20),
            execute_action=False,
            group_id="G1",
            priority=5,
            conditions={"OtherEvent": True},
        )
        evt.use_event = False
        return evt

    def test_field_coverage(self):
        """EventModel의 모든 필드가 _copy_event 결과에 반영됨 (latest_screenshot 제외)"""
        stub = _make_importer_stub()
        evt = self._make_full_event()
        copied = stub._copy_event(evt)

        all_fields = {f.name for f in dataclasses.fields(EventModel)}
        skip = {"latest_screenshot"}

        for fname in all_fields - skip:
            orig = getattr(evt, fname)
            dup = getattr(copied, fname)
            # Image는 별도 객체이므로 크기 비교
            if isinstance(orig, Image.Image):
                self.assertEqual(orig.size, dup.size, f"Field '{fname}' image size mismatch")
            else:
                self.assertEqual(orig, dup, f"Field '{fname}' mismatch: {orig!r} != {dup!r}")

        # latest_screenshot은 항상 None
        self.assertIsNone(copied.latest_screenshot)

    def test_deep_copy_held_screenshot(self):
        """held_screenshot 수정이 복사본에 영향 없음"""
        stub = _make_importer_stub()
        evt = self._make_full_event()
        copied = stub._copy_event(evt)

        # 원본 이미지 수정
        evt.held_screenshot.putpixel((0, 0), (255, 255, 255))
        # 복사본은 영향 없음
        self.assertNotEqual(copied.held_screenshot.getpixel((0, 0)), (255, 255, 255))

    def test_deep_copy_conditions(self):
        """conditions dict 수정이 복사본에 영향 없음"""
        stub = _make_importer_stub()
        evt = self._make_full_event()
        copied = stub._copy_event(evt)

        # 원본 conditions 수정
        evt.conditions["NewCond"] = False
        # 복사본은 영향 없음
        self.assertNotIn("NewCond", copied.conditions)

    def test_use_event_copied(self):
        """__init__ 후 설정되는 use_event 필드도 복사됨"""
        stub = _make_importer_stub()
        evt = self._make_full_event()
        evt.use_event = False
        copied = stub._copy_event(evt)
        self.assertFalse(copied.use_event)


if __name__ == "__main__":
    unittest.main(verbosity=2)
