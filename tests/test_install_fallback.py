import os
import shutil
import tempfile
import unittest

from apkharness.adb import AdbError
from apkharness.run import RunConfig, Session
from apkharness.simulator import SimDevice


class _FakeAdb:
    def installed_version(self, package):
        return {"version_name": "0.1.19", "version_code": "19"}


class NewerOnPhone(SimDevice):
    """A phone that already has a newer build: installing the older file is refused."""

    def __init__(self, error):
        super().__init__(package="com.example.game", seed=1)
        self.adb = _FakeAdb()
        self.error = error
        self.installed = True  # the newer copy is there

    def install(self, apk):
        raise AdbError(self.error)


class InstallFallbackTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="apkharness_fallback_")
        self.apk = os.path.join(self.out, "old.apk")
        with open(self.apk, "wb") as handle:
            handle.write(b"not really an apk")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def run_with(self, error):
        config = RunConfig(apk=self.apk, package="com.example.game", activity="com.example.game/.Main",
                           steps=5, out_root=self.out, step_delay_s=0.0)
        return Session(config, device=NewerOnPhone(error)).run()

    def test_downgrade_tests_installed_version(self):
        result = self.run_with("install failed: Failure [INSTALL_FAILED_VERSION_DOWNGRADE: Downgrade detected]")
        self.assertIn("newer", result.meta["install_note"])
        self.assertEqual(result.meta["apk"]["version_code"], "19")
        self.assertEqual(result.summary["steps_run"], 5)

    def test_other_install_errors_still_fail(self):
        with self.assertRaises(AdbError):
            self.run_with("install failed: Failure [INSTALL_FAILED_INSUFFICIENT_STORAGE]")


if __name__ == "__main__":
    unittest.main()
