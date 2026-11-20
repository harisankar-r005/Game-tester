import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from apkharness.device import DeviceUnavailable
from apkharness.actions import Action
from apkharness.plan import default_plan
from apkharness.policies import HeuristicPolicy
from apkharness.run import CHECKPOINT_FILE, RunConfig, Session
from apkharness.simulator import SimDevice
from apkharness.studio import Studio, StudioError


class TapPolicy(HeuristicPolicy):
    def act(self, observation, memory):
        return Action(type="tap", x=20, y=30)


class StopTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="apkharness_stop_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_stop_mid_test_is_quick_and_keeps_a_report(self):
        flag = threading.Event()
        config = RunConfig(simulate=True, steps=100_000, time_budget_s=600, out_root=self.out,
                           step_delay_s=0.5, seed=2)
        session = Session(config, should_stop=flag.is_set)
        threading.Timer(1.0, flag.set).start()
        started = time.monotonic()
        result = session.run()
        self.assertLess(time.monotonic() - started, 6, "stop must not wait for the whole plan")
        self.assertTrue(result.summary["stopped_by_user"])
        self.assertLess(result.summary["steps_run"], 100_000)
        self.assertTrue(result.summary["steps_run"] > 0)

    def test_section_time_limit_can_resume_with_a_fresh_time_budget(self):
        time_now = 0.0

        def record_step(_record):
            nonlocal time_now
            time_now += 2.0

        config = RunConfig(simulate=True, steps=4, section_size=2, time_budget_s=1,
                           step_delay_s=0.0, out_root=self.out)
        flag = threading.Event()
        session = Session(config, on_step=record_step, should_stop=flag.is_set, allow_resume=True)
        with patch("apkharness.run.time.monotonic", side_effect=lambda: time_now):
            result = session.run()
            self.assertEqual(result.summary["steps_run"], 1)
            self.assertEqual(result.summary["end_reason"], "section_time_limit")
            self.assertFalse(session.at_section_boundary)
            result = session.run()
            self.assertEqual(result.summary["steps_run"], 2)
            self.assertEqual(result.summary["end_reason"], "section_complete")
            self.assertTrue(session.at_section_boundary)
            flag.set()
            result = session.run()
            self.assertEqual(result.summary["steps_run"], 2)
            self.assertEqual(result.summary["end_reason"], "stopped")
            self.assertFalse(session.at_section_boundary)
        session.close()

    def test_repeated_unchanged_inputs_pause_with_screen_and_recent_actions(self):
        phone = SimDevice()
        screenshot = phone.screenshot()
        config = RunConfig(simulate=True, steps=25, stuck_after=3, out_root=self.out, step_delay_s=0)
        session = Session(config, device=phone, policy=TapPolicy(), allow_resume=True)
        with patch.object(phone, "screenshot", return_value=screenshot):
            result = session.run()
            step = session.memory.step
            self.assertEqual(result.summary["end_reason"], "stuck")
            self.assertEqual(session.stuck["attempts"], 3)
            self.assertTrue(session.stuck["actions"])
            self.assertTrue(os.path.isfile(os.path.join(session.out_dir, session.stuck["screenshot"])))
            session.run()
            self.assertGreater(session.memory.step, step)
        session.close()

    def test_uncertain_input_is_recorded_and_not_dispatched_again_after_restart(self):
        config = RunConfig(simulate=True, steps=3, out_root=self.out, step_delay_s=0)
        session = Session(config, policy=TapPolicy(), allow_resume=True, checkpoint_context={})
        with patch.object(session.device, "tap", side_effect=OSError("tester exited during input")):
            with self.assertRaisesRegex(OSError, "tester exited"):
                session.run()
        with open(os.path.join(session.out_dir, CHECKPOINT_FILE), encoding="utf-8") as handle:
            state = json.load(handle)
        restored = Session(RunConfig(**state["config"]), policy=TapPolicy(), allow_resume=True, checkpoint_context={})
        restored.restore_checkpoint(session.out_dir, state)
        self.assertEqual(restored.memory.step, 1)
        with patch.object(restored.device, "tap", wraps=restored.device.tap) as tap:
            result = restored.run()
        self.assertEqual(tap.call_count, 2)
        self.assertEqual(result.summary["unconfirmed_inputs"], 1)
        self.assertIn("delivery unconfirmed", result.timeline[0]["action"])


class UnpluggedPhone(SimDevice):
    def alive(self, package):
        if self.step >= 6:
            raise DeviceUnavailable("adb.exe: device 'abc' not found")
        return super().alive(package)


class PhoneLostTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="apkharness_lost_")

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_unplugged_phone_is_not_a_game_crash(self):
        config = RunConfig(simulate=True, steps=40, out_root=self.out, step_delay_s=0.0, seed=4)
        flag = threading.Event()
        session = Session(config, device=UnpluggedPhone(seed=4), should_stop=flag.is_set)
        threading.Timer(2.0, flag.set).start()  # don't wait the full 20 s grace in a unit test
        result = session.run()
        self.assertTrue(result.summary["device_lost"])
        self.assertFalse([c for c in result.crashes if c["kind"] == "process_death"])

    def test_short_disconnect_retries_the_same_step(self):
        class ReconnectingPhone(SimDevice):
            def alive(self, package):
                if self.step in (3, 4):
                    raise DeviceUnavailable("device offline")
                return super().alive(package)

        config = RunConfig(simulate=True, steps=6, out_root=self.out, step_delay_s=0.0)
        phases = []
        session = Session(config, device=ReconnectingPhone(), on_phase=phases.append, allow_resume=True)
        result = session.run()
        self.assertEqual([row["step"] for row in result.timeline], list(range(1, 7)))
        self.assertEqual(result.summary["end_reason"], "completed")
        self.assertIn("phone-lost", phases)
        self.assertEqual(phases.count("running"), 2)

    def test_long_disconnect_can_continue_without_restarting_the_game(self):
        class ReconnectingPhone(SimDevice):
            unplugged = False

            def alive(self, package):
                if self.unplugged:
                    raise DeviceUnavailable("device offline")
                return super().alive(package)

        phone = ReconnectingPhone()
        config = RunConfig(simulate=True, steps=6, out_root=self.out, step_delay_s=0.0)

        def unplug_after_second_step(record):
            phone.unplugged = record["step"] == 2

        session = Session(config, device=phone, on_step=unplug_after_second_step, allow_resume=True)
        with patch("apkharness.run.PHONE_RECONNECT_GRACE_S", 0):
            first = session.run()
        self.assertEqual(first.summary["end_reason"], "phone_lost")
        self.assertEqual(first.summary["steps_run"], 2)
        self.assertTrue(session.resumable)
        phone.unplugged = False
        with patch.object(phone, "launch", wraps=phone.launch) as launch:
            complete = session.run()
        launch.assert_not_called()
        self.assertEqual([row["step"] for row in complete.timeline], list(range(1, 7)))
        self.assertEqual(complete.summary["end_reason"], "completed")


class StudioResumeTests(unittest.TestCase):
    def test_reopening_restores_partial_results_and_continues_the_same_run(self):
        with tempfile.TemporaryDirectory(prefix="apkharness_disk_resume_") as out:
            studio = Studio(workdir=out)
            plan = studio.plan.to_dict()
            plan.update(target="simulator", steps=4, record_video=False)
            studio.set_plan(plan)
            studio.start(section_size=2)
            studio.thread.join(timeout=15)
            self.assertEqual(studio.summary["end_reason"], "section_complete")
            self.assertEqual(studio.qa_review["decision"], "INCOMPLETE")
            first_actions = [row["action"] for row in studio.step_log]
            original_dir = studio.session_dir

            reopened = Studio(workdir=out)
            self.assertTrue(os.path.samefile(reopened.session_dir, original_dir))
            self.assertEqual(reopened.progress["step"], 2)
            self.assertEqual([row["action"] for row in reopened.step_log], first_actions)
            self.assertTrue(os.path.isfile(reopened.frame_path("latest")))
            self.assertEqual(reopened.qa_review["decision"], "INCOMPLETE")
            self.assertTrue(reopened.qa_review["checklist"]["resumable"])
            with open(os.path.join(original_dir, "report.html"), encoding="utf-8") as handle:
                self.assertIn("Results so far", handle.read())
            with open(os.path.join(original_dir, "junit.xml"), encoding="utf-8") as handle:
                self.assertIn('<skipped message="Results so far: 2 of 4 planned steps"', handle.read())
            self.assertTrue(reopened.resume()["resumed"])
            reopened.thread.join(timeout=15)
            self.assertEqual(reopened.status, "done", reopened.error)
            self.assertEqual(reopened.summary["steps_run"], 4)
            self.assertEqual(reopened.summary["end_reason"], "completed")
            self.assertFalse(os.path.exists(os.path.join(original_dir, CHECKPOINT_FILE)))
            self.assertIsNone(Studio(workdir=out)._paused_session)

    def test_each_section_requires_a_new_start_and_keeps_previous_steps(self):
        with tempfile.TemporaryDirectory(prefix="apkharness_sections_") as out:
            studio = Studio(workdir=out)
            plan = studio.plan.to_dict()
            plan.update(target="simulator", steps=7, record_video=False)
            studio.set_plan(plan)
            studio.start(section_size=2)
            run_dir = None
            for section, end in enumerate((2, 4, 6, 7), start=1):
                studio.thread.join(timeout=15)
                self.assertEqual(studio.status, "done", studio.error)
                run_dir = run_dir or studio.session_dir
                self.assertEqual(studio.session_dir, run_dir)
                self.assertEqual(studio.progress["section"], section)
                self.assertEqual([row["step"] for row in studio.step_log], list(range(1, end + 1)))
                if end != 7:
                    self.assertEqual(studio.summary["end_reason"], "section_complete")
                    self.assertTrue(studio._paused_session.at_section_boundary)
                    run_id = os.path.basename(run_dir)
                    with self.assertRaisesRegex(StudioError, "paused run changed"):
                        studio.resume(expected_run=run_id, after_step=end - 1)
                    self.assertEqual(studio.status, "done")
                    self.assertTrue(studio.resume(expected_run=run_id, after_step=end)["resumed"])
            self.assertEqual(studio.summary["end_reason"], "completed")
            self.assertIsNone(studio._paused_session)

    def test_manual_stop_and_start_preserve_the_run(self):
        with tempfile.TemporaryDirectory(prefix="apkharness_resume_") as out:
            studio = Studio(workdir=out)
            plan = studio.plan.to_dict()
            plan.update(target="simulator", steps=5, record_video=False)
            studio.set_plan(plan)
            record_step = studio._on_step

            def stop_on_second_step(record):
                record_step(record)
                if record["step"] == 2:
                    studio.stop()

            studio._on_step = stop_on_second_step
            studio.start()
            studio.thread.join(timeout=15)
            self.assertEqual(studio.status, "done", studio.error)
            self.assertEqual(studio.summary["steps_run"], 2)
            original_dir = studio.session_dir
            session = studio._paused_session
            self.assertIsNotNone(session)
            self.assertTrue(session.device.running)
            self.assertTrue(studio.start()["resumed"])
            studio.thread.join(timeout=15)
            self.assertEqual(studio.status, "done", studio.error)
            self.assertEqual(studio.session_dir, original_dir)
            self.assertEqual([row["step"] for row in studio.step_log], list(range(1, 6)))
            self.assertEqual([row["step"] for row in session.result.timeline], list(range(1, 6)))
            self.assertEqual(studio.summary["end_reason"], "completed")
            self.assertFalse(session.device.running)
            with self.assertRaisesRegex(StudioError, "no paused exploration"):
                studio.resume()

    def test_watcher_resumes_only_when_the_same_phone_reconnects(self):
        with tempfile.TemporaryDirectory(prefix="apkharness_reconnect_") as out:
            studio = Studio(workdir=out, adb_path="adb")
            plan = default_plan(target="device")
            plan.steps, plan.capture, plan.record_video = 4, "frames", False
            phone = SimDevice()
            phone.install("practice.apk")
            config = RunConfig(package=phone.package, activity=f"{phone.package}/.Main", serial="same-phone",
                               no_install=True, steps=4, out_root=studio.runs_dir,
                               step_delay_s=0.0, plan=plan.to_dict())
            online = True
            original_alive = phone.alive

            def alive(package):
                if not online:
                    raise DeviceUnavailable("device offline")
                return original_alive(package)

            def record(record):
                nonlocal online
                studio._on_step(record)
                if record["step"] == 2:
                    online = False

            phone.alive = alive
            session = Session(config, device=phone, on_step=record, allow_resume=True,
                              should_stop=studio.stop_event.is_set)
            with patch("apkharness.run.PHONE_RECONNECT_GRACE_S", 0):
                session.run()
            studio._paused_session = session
            studio.status = "done"
            wrong = {"devices": [{"serial": "different-phone", "state": "device"}]}
            right = {"devices": [{"serial": "same-phone", "state": "device"}]}
            with patch.object(studio, "device_list", return_value=wrong):
                with self.assertRaisesRegex(StudioError, "same phone"):
                    studio.resume()
            self.assertIs(studio._paused_session, session)
            self.assertIsNone(studio.thread)

            online = True
            with patch.object(studio._watch_stop, "wait", side_effect=[False, False, True]), \
                    patch.object(studio, "device_list", side_effect=[wrong, right, right]):
                studio._watch_loop()
            studio.thread.join(timeout=15)
            self.assertEqual(studio.status, "done", studio.error)
            self.assertEqual(studio.summary["steps_run"], 4)
            self.assertEqual([row["step"] for row in studio.step_log], [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
