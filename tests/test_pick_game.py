import shutil
import tempfile
import unittest

from apkharness.studio import Studio, StudioError


class PickGameTests(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="apkharness_pick_")
        self.studio = Studio(workdir=self.workdir, adb_path="")
        self.studio.adb_path = ""  # no adb: behave like a computer with no phone tools

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_starts_with_no_game(self):
        self.assertIsNone(self.studio.apk)
        self.assertFalse(self.studio._has_target())

    def test_installed_only_counts_as_target(self):
        self.studio.apk = {"package": "com.example.game", "installed_only": True}
        self.assertTrue(self.studio._has_target())
        self.studio.clear_apk()
        self.assertIsNone(self.studio.apk)
        self.assertFalse(self.studio._has_target())

    def test_no_phone_lists_nothing(self):
        result = self.studio.phone_apps()
        self.assertEqual(result["apps"], [])
        self.assertTrue(result["hint"])

    def test_rejects_bad_app_id(self):
        with self.assertRaises(StudioError):
            self.studio.choose_installed("rm -rf /")


if __name__ == "__main__":
    unittest.main()
