"""Accessibility tree parsing and candidate ranking tests."""

import unittest

from apkharness import ui

SAMPLE = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.example.game"
        content-desc="" clickable="false" enabled="true" bounds="[0,0][1080,1920]">
    <node index="0" text="Play" resource-id="com.example.game:id/play" class="android.widget.Button"
          package="com.example.game" content-desc="" clickable="true" enabled="true" bounds="[100,900][980,1020]" />
    <node index="1" text="" resource-id="com.example.game:id/settings" class="android.widget.ImageButton"
          package="com.example.game" content-desc="Settings" clickable="true" enabled="true" bounds="[900,80][1040,220]" />
    <node index="2" text="Version 1.0.3" resource-id="com.example.game:id/version" class="android.widget.TextView"
          package="com.example.game" content-desc="" clickable="false" enabled="true" bounds="[40,1800][400,1840]" />
    <node index="3" text="Disabled" resource-id="com.example.game:id/off" class="android.widget.Button"
          package="com.example.game" content-desc="" clickable="true" enabled="false" bounds="[100,300][400,380]" />
    <node index="4" text="Home" resource-id="com.android.systemui:id/home" class="android.widget.ImageView"
          package="com.android.systemui" content-desc="Home" clickable="true" enabled="true" bounds="[500,1850][560,1910]" />
  </node>
</hierarchy>
"""


class ParseTests(unittest.TestCase):
    def test_parse_sample(self):
        nodes = ui.parse_ui(SAMPLE)
        self.assertEqual(len(nodes), 6)
        play = next(n for n in nodes if n.text == "Play")
        self.assertEqual(play.bounds, (100, 900, 980, 1020))
        self.assertEqual(play.center, (540, 960))
        self.assertTrue(play.clickable)
        self.assertEqual(play.short_id, "play")

    def test_parse_tolerates_junk(self):
        junk = "UI hierchary dumped to: /sdcard/window.xml\n" + SAMPLE
        self.assertEqual(len(ui.parse_ui(junk)), 6)
        self.assertEqual(ui.parse_ui("ERROR: could not get idle state"), [])
        self.assertEqual(ui.parse_ui(""), [])
        self.assertEqual(ui.parse_ui("<hierarchy><node bounds='nonsense'"), [])

    def test_noise_is_filtered(self):
        nodes = ui.parse_ui(SAMPLE)
        usable = ui.usable(nodes, 1080, 1920)
        ids = {n.rid for n in usable}
        self.assertNotIn("com.android.systemui:id/home", ids)
        # full-screen container is not tappable
        self.assertNotIn((0, 0, 1080, 1920), {n.bounds for n in usable})

    def test_ranking_prefers_labelled_buttons(self):
        ranked = ui.rank_candidates(ui.parse_ui(SAMPLE), 1080, 1920)
        self.assertEqual(ranked[0].text, "Play")
        self.assertEqual(ranked[1].desc, "Settings")
        self.assertEqual(ranked[-1].text, "Version 1.0.3")

    def test_describe_lists_labels(self):
        text = ui.describe(ui.parse_ui(SAMPLE), 1080, 1920)
        self.assertIn("'Play'", text)
        self.assertIn("'Settings'", text)

    def test_find_by_label(self):
        nodes = ui.parse_ui(SAMPLE)
        self.assertIsNotNone(ui.find_by_label(nodes, "settings"))
        self.assertIsNone(ui.find_by_label(nodes, "nonexistent"))

    def test_screen_area(self):
        self.assertEqual(ui.screen_area(ui.parse_ui(SAMPLE)), (1080, 1920))


if __name__ == "__main__":
    unittest.main()
