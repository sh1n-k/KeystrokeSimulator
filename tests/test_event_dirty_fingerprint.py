import dataclasses
import unittest

from PIL import Image

from app.core.models import EventModel
from app.ui.profiles import (
    EVENT_DIRTY_FIELD_NAMES,
    _event_fingerprint,
    event_dirty_field_names,
)


def _mutated_event(field_name: str) -> EventModel:
    """Return an EventModel that differs from defaults only on field_name."""
    evt = EventModel()
    if field_name == "event_name":
        evt.event_name = "Changed"
    elif field_name == "latest_position":
        evt.latest_position = (10, 20)
    elif field_name == "clicked_position":
        evt.clicked_position = (3, 4)
    elif field_name == "held_screenshot":
        evt.held_screenshot = Image.new("RGB", (8, 8), color=(1, 2, 3))
    elif field_name == "ref_pixel_value":
        evt.ref_pixel_value = (9, 8, 7)
    elif field_name == "key_to_enter":
        evt.key_to_enter = "F8"
    elif field_name == "press_duration_ms":
        evt.press_duration_ms = 200.0
    elif field_name == "randomization_ms":
        evt.randomization_ms = 15.0
    elif field_name == "use_event":
        evt.use_event = False
    elif field_name == "capture_size":
        evt.capture_size = (200, 200)
    elif field_name == "match_mode":
        evt.match_mode = "region"
    elif field_name == "invert_match":
        evt.invert_match = True
    elif field_name == "region_size":
        evt.region_size = (30, 40)
    elif field_name == "execute_action":
        evt.execute_action = False
    elif field_name == "group_id":
        evt.group_id = "g1"
    elif field_name == "priority":
        evt.priority = 7
    elif field_name == "conditions":
        evt.conditions = {"Other": True}
    elif field_name == "runtime_toggle_member":
        evt.runtime_toggle_member = True
    else:
        raise AssertionError(f"No mutation defined for field {field_name!r}")
    return evt


class TestEventDirtyFingerprintCoverage(unittest.TestCase):
    def test_dirty_field_names_cover_all_event_model_fields(self) -> None:
        model_fields = {field.name for field in dataclasses.fields(EventModel)}
        dirty_fields = event_dirty_field_names()

        self.assertEqual(
            model_fields,
            dirty_fields,
            msg=(
                "EventModel fields and dirty/fingerprint coverage diverged. "
                f"missing_from_dirty={sorted(model_fields - dirty_fields)} "
                f"extra_in_dirty={sorted(dirty_fields - model_fields)}. "
                "Update EVENT_DIRTY_FIELD_NAMES and _event_fingerprint together."
            ),
        )
        self.assertIs(dirty_fields, EVENT_DIRTY_FIELD_NAMES)

    def test_each_event_model_field_affects_fingerprint(self) -> None:
        """Fail if _event_fingerprint omits a field listed in dirty coverage."""
        base_fp = _event_fingerprint(EventModel())
        for field_name in sorted(event_dirty_field_names()):
            with self.subTest(field=field_name):
                changed_fp = _event_fingerprint(_mutated_event(field_name))
                self.assertNotEqual(
                    base_fp,
                    changed_fp,
                    msg=(
                        f"Field {field_name!r} is in EVENT_DIRTY_FIELD_NAMES but "
                        f"mutating it does not change _event_fingerprint — "
                        f"autosave may skip real edits."
                    ),
                )


if __name__ == "__main__":
    unittest.main()
