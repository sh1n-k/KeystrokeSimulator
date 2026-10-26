import dataclasses
import unittest

from PIL import Image

from app.domain.models import EventModel
from app.domain.profile_events import clone_event


class TestEventCopySync(unittest.TestCase):
    """clone_event: 복사·다른 프로필로 복사가 쓰는 필드 동기화 검증"""

    def _make_full_event(self) -> EventModel:
        """모든 필드가 채워진 테스트용 이벤트"""
        evt = EventModel(
            event_name="TestEvent",
            latest_position=(100, 200),
            clicked_position=(10, 20),
            held_screenshot=Image.new("RGB", (10, 10), color=(10, 20, 30)),
            ref_pixel_value=(10, 20, 30),
            key_to_enter="F5",
            press_duration_ms=150.0,
            randomization_ms=50.0,
            match_mode="region",
            invert_match=True,
            region_size=(20, 20),
            execute_action=False,
            group_id="G1",
            priority=5,
            conditions={"OtherEvent": True},
        )
        evt.use_event = False
        evt.runtime_toggle_member = True
        return evt

    def test_field_coverage(self):
        """EventModel의 모든 필드가 clone_event 결과에 반영됨"""
        evt = self._make_full_event()
        copied = clone_event(evt)

        all_fields = {f.name for f in dataclasses.fields(EventModel)}
        for fname in all_fields:
            orig = getattr(evt, fname)
            dup = getattr(copied, fname)
            # Image는 별도 객체이므로 크기 비교
            if isinstance(orig, Image.Image):
                self.assertEqual(orig.size, dup.size, f"Field '{fname}' image size mismatch")
            else:
                self.assertEqual(orig, dup, f"Field '{fname}' mismatch: {orig!r} != {dup!r}")

    def test_deep_copy_held_screenshot(self):
        """held_screenshot 수정이 복사본에 영향 없음"""
        evt = self._make_full_event()
        copied = clone_event(evt)

        # 원본 이미지 수정
        evt.held_screenshot.putpixel((0, 0), (255, 255, 255))
        # 복사본은 영향 없음
        self.assertNotEqual(copied.held_screenshot.getpixel((0, 0)), (255, 255, 255))

    def test_deep_copy_conditions(self):
        """conditions dict 수정이 복사본에 영향 없음"""
        evt = self._make_full_event()
        copied = clone_event(evt)

        # 원본 conditions 수정
        evt.conditions["NewCond"] = False
        # 복사본은 영향 없음
        self.assertNotIn("NewCond", copied.conditions)

    def test_use_event_copied(self):
        """__init__ 후 설정되는 use_event 필드도 복사됨"""
        evt = self._make_full_event()
        evt.use_event = False
        copied = clone_event(evt)
        self.assertFalse(copied.use_event)


if __name__ == "__main__":
    unittest.main(verbosity=2)
