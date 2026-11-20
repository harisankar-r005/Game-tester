"""Unit tests for action parsing and validation."""

import unittest

from apkharness.actions import Action, ActionError, back, tap


class ActionTests(unittest.TestCase):
    def test_tap_defaults(self):
        action = tap(100, 200, note="ui:Play")
        self.assertEqual(action.type, "tap")
        self.assertEqual((action.x, action.y), (100, 200))
        self.assertEqual(action.duration_ms, 60)
        self.assertIn("tap(100,200)", action.label)
        self.assertIn("ui:Play", action.label)

    def test_wait_default_duration(self):
        self.assertEqual(Action(type="wait").duration_ms, 500)

    def test_back_uses_keycode(self):
        self.assertEqual(back().keycode, 4)

    def test_unknown_type_rejected(self):
        with self.assertRaises(ActionError):
            Action(type="teleport")

    def test_negative_coordinates_rejected(self):
        with self.assertRaises(ActionError):
            Action(type="tap", x=-1, y=10)

    def test_from_dict_roundtrip(self):
        original = Action(type="swipe", x=1, y=2, x2=3, y2=4, duration_ms=250, note="scroll")
        restored = Action.from_dict(original.to_dict())
        self.assertEqual(original, restored)

    def test_from_dict_ignores_zero_fields(self):
        self.assertEqual(Action.from_dict({"type": "tap", "x": 5, "y": 6}).x, 5)

    def test_from_dict_rejects_unknown_field(self):
        with self.assertRaises(ActionError):
            Action.from_dict({"type": "tap", "x": 1, "y": 1, "zoom": 3})

    def test_clamped_stays_on_screen(self):
        action = Action(type="swipe", x=5000, y=3000, x2=2000, y2=99999)
        clamped = action.clamped(1080, 1920)
        self.assertEqual(clamped.x, 1079)
        self.assertEqual(clamped.y, 1919)
        self.assertEqual(clamped.x2, 1079)
        self.assertEqual(clamped.y2, 1919)

    def test_clamped_without_size_is_identity(self):
        action = tap(10, 10)
        self.assertEqual(action.clamped(0, 0), action)


if __name__ == "__main__":
    unittest.main()
