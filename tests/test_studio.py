"""End-to-end tests for the QA studio: state, HTTP API, run, checks, video."""

import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apkharness.plan import default_plan
from apkharness.studio import Handler, Studio, StudioError, make_server

SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
os.makedirs(SCRATCH, exist_ok=True)


def _wait_for(condition, timeout=90.0, interval=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return False


class StudioPresetTests(unittest.TestCase):
    def test_exploration_uses_selected_length_for_manual_and_automatic_start(self):
        with tempfile.TemporaryDirectory(prefix="apkharness_presets_") as workdir:
            studio = Studio(workdir=workdir)

            def finish(_plan, _config, _serial):
                with studio.lock:
                    studio.status = "done"

            with patch.object(studio, "_worker", side_effect=finish) as worker:
                for preset, steps in ((None, 50), ("standard", 150), ("extended", 400)):
                    studio.auto_start(where="practice", preset=preset)
                    studio.thread.join(timeout=5)
                    config = worker.call_args.args[1]
                    self.assertEqual(config.steps, steps)
                    self.assertEqual(config.section_size, 100)
                    self.assertEqual(studio.progress["total"], steps)
                    studio.restart()
                studio.set_autoqa({"preset": "standard"})
                studio.auto_start(where="practice")
                studio.thread.join(timeout=5)
                self.assertEqual(worker.call_args.args[1].steps, 150)
            with self.assertRaisesRegex(StudioError, "Quick, Standard or Extended"):
                studio.set_autoqa({"preset": "unknown"})

    def test_exploration_objective_requires_ai_and_is_passed_to_the_run(self):
        with tempfile.TemporaryDirectory(prefix="apkharness_objective_") as workdir:
            studio = Studio(workdir=workdir)
            with self.assertRaisesRegex(StudioError, "Enable the AI player"):
                studio.auto_start(where="practice", objective="Reach the till")
            with self.assertRaisesRegex(StudioError, "300 characters"):
                studio.auto_start(where="practice", objective="x" * 301)
            with patch.object(studio, "_ai_config_for_run", return_value={"provider": "ollama"}), \
                    patch.object(studio, "_worker") as worker:
                studio.auto_start(where="practice", objective="  Reach the till  ")
                studio.thread.join(timeout=5)
            config = worker.call_args.args[1]
            self.assertEqual(config.policy, "agent")
            self.assertEqual(config.gameplay_objective, "Reach the till")
            self.assertEqual(studio.progress["gameplay_objective"], config.gameplay_objective)


class StudioDeleteRunTests(unittest.TestCase):
    def setUp(self):
        workdir = tempfile.TemporaryDirectory(prefix="apkharness_delete_")
        self.addCleanup(workdir.cleanup)
        self.studio = Studio(workdir=workdir.name)
        self.first = self.make_run("20261120_090000_com.example.first")
        self.second = self.make_run("20261120_100000_com.example.second")

    def make_run(self, name):
        path = Path(self.studio.runs_dir) / name
        (path / "screenshots").mkdir(parents=True)
        (path / "screenshots" / "step_00001.png").write_bytes(b"test screenshot")
        (path / "session.mp4").write_bytes(b"test recording")
        (path / "session.json").write_text("{}", encoding="utf-8")
        return path

    def test_removes_only_selected_run_and_clears_its_cached_preview(self):
        self.studio.session_dir = str(self.first)
        self.studio.status = "done"
        self.studio.qa_review = {"decision": "GO"}
        self.studio._on_frame(1, b"cached screenshot", "", False)
        frame = Path(self.studio.live_frames[0].path)
        uploaded_apk = Path(self.studio.uploads_dir) / "game.apk"
        uploaded_apk.write_bytes(b"test apk")

        result = self.studio.delete_saved_runs([self.first.name, self.first.name])

        self.assertEqual(result, {"deleted": [self.first.name], "errors": []})
        self.assertFalse(self.first.exists())
        self.assertFalse(frame.exists())
        self.assertTrue((self.second / "session.mp4").exists())
        self.assertTrue(uploaded_apk.exists())
        self.assertIsNone(self.studio.qa_review)
        self.assertEqual([run["id"] for run in self.studio.run_history()["runs"]], [self.second.name])

    def test_rejects_mixed_selection_with_running_or_paused_run(self):
        for status in ("running", "done"):
            with self.subTest(status=status):
                self.studio.status = status
                self.studio.session_dir = str(self.second)
                if status == "done":
                    self.studio._paused_session = SimpleNamespace(out_dir=str(self.second))
                with self.assertRaisesRegex(StudioError, "running, paused or linked"):
                    self.studio.delete_saved_runs([self.first.name, self.second.name])
                self.assertTrue(self.first.is_dir())
                history = {run["id"]: run for run in self.studio.run_history()["runs"]}
                self.assertFalse(history[self.second.name]["deletable"])

    def test_rejects_targets_that_resolve_outside_the_run_folder(self):
        with self.assertRaisesRegex(StudioError, "saved test runs"):
            self.studio.delete_saved_runs(["../uploads"])
        realpath = os.path.realpath

        def resolve(path):
            return self.studio.uploads_dir if Path(path) == self.first else realpath(path)

        with patch("apkharness.studio.os.path.realpath", side_effect=resolve), \
                patch("apkharness.studio.shutil.rmtree") as remove:
            with self.assertRaisesRegex(StudioError, "linked test"):
                self.studio.delete_saved_runs([self.first.name])
            remove.assert_not_called()

    def test_delete_endpoint_requires_a_local_origin_and_json(self):
        handler = object.__new__(Handler)
        handler.path = "/api/runs/delete"
        handler.studio = self.studio
        handler._json = Mock()
        handler._error = Mock()
        handler._body = Mock(return_value=json.dumps({"runs": [self.first.name]}).encode())
        for origin, content_type, status in (("https://other.example", "application/json", 403),
                                              ("http://127.0.0.1:8765", "text/plain", 415)):
            handler.headers = Message()
            handler.headers["Host"] = "127.0.0.1:8765"
            handler.headers["Origin"] = origin
            handler.headers["Content-Type"] = content_type
            handler.do_POST()
            self.assertEqual(handler._error.call_args.args[1], status)
            self.assertTrue(self.first.exists())
        handler.headers.replace_header("Content-Type", "application/json")
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0]["deleted"], [self.first.name])
        self.assertFalse(self.first.exists())


class StudioRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = os.path.join(SCRATCH, f"studio_{os.getpid()}")
        shutil.rmtree(cls.workdir, ignore_errors=True)
        cls.studio = Studio(workdir=cls.workdir)
        plan = default_plan()
        payload = plan.to_dict()
        payload["steps"] = 16
        payload["video_fps"] = 4
        payload["checks"].append({"id": "no-findings", "type": "no_findings", "kinds": ["anr"],
                                  "severity": "warning"})
        cls.studio.set_plan(payload)
        cls.studio.start()
        if not _wait_for(lambda: cls.studio.status in ("done", "error")):
            raise AssertionError(f"studio did not finish: {cls.studio.status} {cls.studio.error}")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def test_run_completed(self):
        self.assertEqual(self.studio.status, "done", self.studio.error)
        self.assertGreater(self.studio.summary.get("steps_run", 0), 5)

    def test_frames_were_captured(self):
        self.assertGreater(len(self.studio.live_frames), 0)
        first = self.studio.live_frames[0]
        self.assertTrue(os.path.exists(first.path))
        with open(first.path, "rb") as handle:
            self.assertTrue(handle.read(8).startswith(b"\x89PNG"))

    def test_checks_were_evaluated(self):
        self.assertTrue(self.studio.checks)
        for check in self.studio.checks:
            self.assertIn("passed", check)
            self.assertIn("severity", check)
        verdict = self.studio.summary.get("check_summary", {}).get("verdict")
        self.assertIn(verdict, ("pass", "warn", "fail"))

    def test_findings_recorded(self):
        # the simulator crashes at step 32 by default; with 16 steps there may be none
        self.assertIsInstance(self.studio.findings, list)

    def test_artifacts_exist(self):
        for name in ("report.html", "junit.xml", "session.json", "checks.json"):
            path = self.studio.artifact_path(name)
            self.assertTrue(os.path.exists(path), name)

    def test_video_produced(self):
        with open(self.studio.session_dir and os.path.join(self.studio.session_dir, "session.json")) as handle:
            json.load(handle)
        meta = self.studio.video_meta
        if not meta.get("available"):
            self.skipTest("no video backend available")
        self.assertTrue(meta.get("path"), meta)
        self.assertTrue(os.path.exists(str(meta["path"])))

    def test_report_contains_checks(self):
        path = self.studio.artifact_path("report.html")
        with open(path, "r", encoding="utf-8") as handle:
            html = handle.read()
        self.assertIn("Checks (", html)
        self.assertIn("check-pass", html)

    def test_junit_declares_tests(self):
        path = self.studio.artifact_path("junit.xml")
        with open(path, "r", encoding="utf-8") as handle:
            xml = handle.read()
        self.assertIn("<testsuite", xml)
        self.assertIn("apkharness.check", xml)

    def test_run_logic_is_streamed(self):
        snapshot = self.studio.snapshot()
        steps = snapshot["steps"]
        self.assertGreater(len(steps), 0)
        first = steps[0]
        for key in ("step", "action", "kind", "alive", "new_screen", "elapsed"):
            self.assertIn(key, first)
        self.assertGreaterEqual(snapshot["steps_total"], len(steps))

    def test_device_selection_state(self):
        payload = self.studio.snapshot()
        self.assertIn("device", payload)
        self.assertIn("selected", payload["device"])

    def test_plan_is_stored_with_metadata(self):
        with open(self.studio.artifact_path("session.json"), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(data["meta"]["plan"]["steps"], 16)


class StudioHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workdir = os.path.join(SCRATCH, f"studio_http_{os.getpid()}")
        shutil.rmtree(cls.workdir, ignore_errors=True)
        cls.studio = Studio(workdir=cls.workdir)
        cls.httpd = make_server(cls.studio, port=0)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, kwargs={"poll_interval": 0.1},
                                      daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def _post_raw(self, path, payload, filename, content_type="application/octet-stream"):
        request = urllib.request.Request(
            self.base + path, data=payload, method="POST",
            headers={"Content-Type": content_type, "X-Filename": filename},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as response:
            return response.status, response.read()

    def _post(self, path, body=None, headers=None):
        data = json.dumps(body).encode("utf-8") if body is not None else b""
        request = urllib.request.Request(self.base + path, data=data, method="POST",
                                         headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_index_page(self):
        status, body = self._get("/studio")
        self.assertEqual(status, 200)
        self.assertIn(b"apkharness studio", body)
        status, home = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Start testing", home)
        self.assertIn(b"/api/state", body)

    def test_health(self):
        status, body = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_state_shape(self):
        status, body = self._get("/api/state")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        for key in ("status", "plan", "progress", "frames", "findings", "checks", "artifacts"):
            self.assertIn(key, payload)

    def test_devices_endpoint(self):
        status, body = self._get("/api/device")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertIn("devices", payload)

    def test_valid_plan_accepted(self):
        plan = default_plan().to_dict()
        plan["steps"] = 33
        status, body = self._post("/api/plan", plan)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["plan"]["steps"], 33)

    def test_invalid_plan_rejected(self):
        status, body = self._post("/api/plan", {"steps": -5, "policy": "magic"})
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body))

    def test_capture_mode_is_validated(self):
        plan = default_plan().to_dict()
        plan["capture"] = "telepathy"
        status, body = self._post("/api/plan", plan)
        self.assertEqual(status, 400)
        self.assertIn("capture", json.loads(body)["error"])

    def test_selecting_unknown_device_fails(self):
        status, body = self._post("/api/device/select", {"serial": "not-a-real-device"})
        self.assertEqual(status, 400)
        self.assertIn("not connected", json.loads(body)["error"])

    def test_requirements_upload_generates_suite(self):
        document = (
            "# Spec\n\n## Menu\n- The game must show a Play button on the main menu.\n"
            "- The game must not crash when the Play button is pressed.\n"
            "## Economy\n- Collecting a coin must add 10 coins to the balance.\n"
        ).encode("utf-8")
        status, body = self._post_raw("/api/requirements", document, "spec.md")
        self.assertEqual(status, 200, body)
        payload = json.loads(body)
        self.assertEqual(payload["requirements"]["counts"]["total"], 3)
        self.assertGreaterEqual(len(payload["testcases"]), 3)
        self.assertTrue(all(case["id"].startswith("TC-") for case in payload["testcases"]))

    def test_case_update_and_verdict(self):
        document = b"- The game must show a Play button on the main menu.\n"
        self._post_raw("/api/requirements", document, "one.md")
        _, body = self._get("/api/state")
        state = json.loads(body)
        case = state["testcases"][0]
        status, body = self._post("/api/testcases/update", {"id": case["id"], "status": "PASS",
                                                           "actual": "menu visible"})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["case"]["status"], "PASS")
        _, body = self._get("/api/state")
        suite = json.loads(body)["suite"]
        self.assertEqual(suite["coverage"]["pass"], 1)

    def test_case_update_rejects_bad_status(self):
        _, body = self._get("/api/state")
        cases = json.loads(body)["testcases"]
        if not cases:
            self._post_raw("/api/requirements", b"- The menu must show Play.\n", "x.md")
            _, body = self._get("/api/state")
            cases = json.loads(body)["testcases"]
        status, body = self._post("/api/testcases/update", {"id": cases[0]["id"], "status": "MAYBE"})
        self.assertEqual(status, 400)
        self.assertIn("status", json.loads(body)["error"])

    def test_approve_and_regenerate(self):
        self._post_raw("/api/requirements", b"- The shop must list three coin packs.\n", "shop.md")
        status, body = self._post("/api/requirements/approve", {"approved": True})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["suite"]["approved"])
        status, body = self._post("/api/requirements/regenerate", {})
        self.assertEqual(status, 200)
        self.assertGreater(len(json.loads(body)["testcases"]), 0)

    def test_document_without_requirements_is_rejected(self):
        status, body = self._post_raw("/api/requirements", b"# Just a title\n", "empty.md")
        self.assertEqual(status, 400)
        self.assertIn("no requirement", json.loads(body)["error"].lower())

    def test_unknown_artifact_is_404(self):
        try:
            self._get("/api/artifact?name=../../secret.txt")
        except urllib.error.HTTPError as exc:
            self.assertIn(exc.code, (400, 404))
        else:
            self.fail("path traversal attempt was served")

    def test_run_without_device_fails_cleanly(self):
        plan = default_plan().to_dict()
        plan["target"] = "device"
        self._post("/api/plan", plan)
        # either a device exists (then the run starts) or we get a clear 400
        status, body = self._post("/api/run")
        if status == 202:
            self.studio.stop()
            self.skipTest("a real device is connected")
        self.assertEqual(status, 400)
        self.assertIn("device", json.loads(body)["error"].lower())


if __name__ == "__main__":
    unittest.main()
