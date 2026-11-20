"""Policy tests: heuristic determinism, scripted replay, LLM validation."""

import contextlib
import itertools
import json
import os
import shutil
import unittest
from unittest.mock import patch

_SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scratch")
os.makedirs(_SCRATCH, exist_ok=True)
_ids = itertools.count()


@contextlib.contextmanager
def scratch_dir(tag: str = "case"):
    """Workspace-local scratch dir; the system temp dir is blocked in some sandboxes."""
    path = os.path.join(_SCRATCH, f"{tag}_{next(_ids)}_{os.getpid()}")
    os.makedirs(path, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


from apkharness.actions import Action
from apkharness.device import Observation
from apkharness.png import dimensions, encode_rgba
from apkharness.policies import build_policy
from apkharness.policies.agent import AIConfig, AgentPolicy, make_view, to_phone
from apkharness.policies.base import Memory, SessionContext
from apkharness.policies.heuristic import HeuristicPolicy
from apkharness.policies.llm import LLMPolicy, extract_json_object, parse_action
from apkharness.policies.scripted import ScriptedPolicy, load_script
from apkharness.ui import parse_ui


def observation(step=1, phash=12345, xml="", size=(1080, 1920)) -> Observation:
    return Observation(step=step, phash=phash, ui_nodes=parse_ui(xml) if xml else [], screen_size=size)


UI_XML = """<hierarchy>
  <node text="Play" class="android.widget.Button" clickable="true" enabled="true"
        bounds="[100,900][980,1020]" />
  <node text="Shop" class="android.widget.Button" clickable="true" enabled="true"
        bounds="[100,1200][980,1320]" />
</hierarchy>"""


class AgentPolicyTests(unittest.TestCase):
    def test_ai_coordinates_match_resized_landscape_frame(self):
        shot = encode_rgba(800, 407, bytes(800 * 407 * 4))
        obs = Observation(screenshot=shot, screen_size=(800, 407))
        view = make_view(obs)
        self.assertEqual((view.width, view.height), dimensions(view.image))
        self.assertEqual((view.width, view.height), (448, 227))
        action = to_phone(Action(type="swipe", x=45, y=180, x2=45, y2=140), view, obs)
        self.assertEqual((action.x, action.y, action.x2, action.y2), (80, 323, 80, 251))
        with patch("apkharness.policies.agent.shrink_png", return_value=shot):
            full_view = make_view(obs)
            self.assertEqual((full_view.width, full_view.height), (800, 407))
            self.assertEqual(to_phone(Action(type="tap", x=510, y=200), full_view, obs).x, 510)

    def test_objective_and_previous_action_are_visible_to_agent(self):
        requests = []

        def transport(_url, _headers, payload, _timeout):
            requests.append(payload["messages"])
            return {"message": {"content": '{"action":{"type":"tap","x":80,"y":80},"thought":"Try the joystick"}'}}

        policy = AgentPolicy(AIConfig(provider="ollama", vision=False), transport=transport)
        context = SessionContext(gameplay_objective="Reach the first-customer till")
        policy.begin(context)
        memory = Memory(visits={123: 1})
        first = Observation(step=1, screen_size=(800, 407), phash=123, screen_key=123)
        policy.act(first, memory)
        self.assertEqual(memory.visits[123], 1)
        self.assertIn("Reach the first-customer till", requests[0][1]["content"])
        self.assertIn("virtual joystick", requests[0][0]["content"])

        resumed = AgentPolicy(AIConfig(provider="ollama", vision=False), transport=transport)
        resumed.begin(context)
        resumed.restore_checkpoint(json.loads(json.dumps(policy.checkpoint_state())))
        memory.visits[123] = 2  # the runner classified the new observation
        resumed.act(Observation(step=2, screen_size=(800, 407), phash=123, screen_key=123), memory)
        self.assertEqual(memory.visits[123], 2)
        self.assertIn("step 1: tap(80,80) [ai: Try the joystick] → nothing changed", requests[1][1]["content"])


class HeuristicTests(unittest.TestCase):
    def test_deterministic_with_same_seed(self):
        def run():
            policy = HeuristicPolicy(seed=11)
            policy.begin(SessionContext(width=1080, height=1920))
            memory = Memory()
            actions = []
            for step in range(1, 15):
                obs = observation(step=step, phash=1000 + step)
                action = policy.act(obs, memory)
                memory.recent.append(action)
                memory.step = step
                memory.screen_key(obs.phash)
                actions.append(action.label)
            return actions

        self.assertEqual(run(), run())

    def test_uses_labelled_ui_nodes(self):
        policy = HeuristicPolicy(seed=3)
        policy.begin(SessionContext(width=1080, height=1920))
        action = policy.act(observation(xml=UI_XML), Memory())
        self.assertEqual(action.type, "tap")
        self.assertIn("ui:", action.note)

    def test_stays_on_screen(self):
        policy = HeuristicPolicy(seed=5)
        policy.begin(SessionContext(width=1080, height=1920))
        memory = Memory()
        for step in range(1, 30):
            action = policy.act(observation(step=step, phash=42 + step % 3), memory)
            self.assertLess(action.x, 1080)
            self.assertLess(action.y, 1920)
            self.assertGreaterEqual(action.x, 0)
            self.assertGreaterEqual(action.y, 0)
            memory.recent.append(action)

    def test_escapes_after_many_visits(self):
        policy = HeuristicPolicy(seed=1, stuck_screens=2)
        policy.begin(SessionContext(width=1080, height=1920))
        memory = Memory()
        memory.screen_key(777)   # candidate frame
        memory.screen_key(777)   # stable -> registered
        memory.visits[777] = 10
        action = policy.act(observation(phash=777), memory)
        self.assertIn(action.type, ("back", "swipe"))

    def test_build_policy_ignores_unknown_arguments(self):
        policy = build_policy("heuristic", seed=2, not_a_real_option=True)
        self.assertIsInstance(policy, HeuristicPolicy)


class ObserveTests(unittest.TestCase):
    def test_observe_policy_never_sends_input(self):
        policy = build_policy("observe")
        policy.begin(SessionContext(width=1080, height=2400))
        action = policy.act(observation(), Memory())
        self.assertEqual(action.type, "wait")
        self.assertIn("observe", action.note)

    def test_observe_is_a_valid_plan_policy(self):
        from apkharness.plan import validate_plan_dict

        self.assertFalse(validate_plan_dict({"policy": "observe"}))


class ScriptedTests(unittest.TestCase):
    def test_replays_in_order_then_waits(self):
        actions = [Action(type="tap", x=1, y=2), Action(type="back")]
        policy = ScriptedPolicy(actions=actions)
        policy.begin(SessionContext(width=100, height=200))
        memory = Memory()
        self.assertEqual(policy.act(observation(size=(100, 200)), memory).label, "tap(1,2)")
        self.assertEqual(policy.act(observation(size=(100, 200)), memory).type, "back")
        self.assertEqual(policy.act(observation(size=(100, 200)), memory).type, "wait")
        self.assertTrue(policy.exhausted)

    def test_loop_wraps(self):
        policy = ScriptedPolicy(actions=[Action(type="tap", x=5, y=5)], loop=True)
        policy.begin(SessionContext())
        for _ in range(3):
            self.assertEqual(policy.act(observation(), Memory()).type, "tap")

    def test_load_script_file(self):
        payload = {"loop": True, "actions": [{"type": "tap", "x": 10, "y": 20}, "back"]}
        with scratch_dir() as tmp:
            path = os.path.join(tmp, "script.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            actions, loop = load_script(path)
        self.assertEqual(len(actions), 2)
        self.assertTrue(loop)
        self.assertEqual(actions[1].type, "back")

    def test_load_script_rejects_bad_shape(self):
        with scratch_dir() as tmp:
            path = os.path.join(tmp, "bad.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"actions": [{"type": "teleport"}]}, handle)
            with self.assertRaises(Exception):
                load_script(path)


class LLMParsingTests(unittest.TestCase):
    def test_plain_json(self):
        action = parse_action('{"reasoning": "go", "action": {"type": "tap", "x": 10, "y": 20}}')
        self.assertEqual(action, Action(type="tap", x=10, y=20))

    def test_fenced_json(self):
        text = '```json\n{"action": {"type": "swipe", "x": 1, "y": 2, "x2": 3, "y2": 4}}\n```'
        action = parse_action(text)
        self.assertIsNotNone(action)
        self.assertEqual(action.type, "swipe")

    def test_prose_around_json(self):
        action = parse_action('I would tap Play. {"action":{"type":"tap","x":5,"y":6}} done')
        self.assertEqual((action.x, action.y), (5, 6))

    def test_invalid_payloads(self):
        self.assertIsNone(parse_action("no json here"))
        self.assertIsNone(parse_action('{"action": {"type": "teleport"}}'))
        self.assertIsNone(parse_action('{"action": {"x": 1}}'))
        self.assertIsNone(parse_action('{"reasoning": "only text"}'))

    def test_extract_object(self):
        self.assertEqual(extract_json_object('{"a": 1}'), {"a": 1})
        self.assertIsNone(extract_json_object("{broken"))


class LLMPolicyTests(unittest.TestCase):
    def setUp(self):
        self.context = SessionContext(package="com.example.game", width=1080, height=1920, max_steps=10)

    def _policy(self, transport, **kwargs):
        policy = LLMPolicy(
            api_key="test-key",
            transport=transport,
            max_retries=0,
            fallback=HeuristicPolicy(seed=4),
            **kwargs,
        )
        policy.begin(self.context)
        return policy

    def test_uses_model_action(self):
        def transport(url, headers, payload, timeout):
            self.assertIn("/chat/completions", url)
            self.assertEqual(headers["Authorization"], "Bearer test-key")
            return {
                "choices": [
                    {"message": {"content": '{"reasoning":"x","action":{"type":"tap","x":540,"y":960}}'}}
                ]
            }

        policy = self._policy(transport)
        action = policy.act(observation(), Memory())
        self.assertEqual((action.type, action.x, action.y), ("tap", 540, 960))
        self.assertEqual(policy.calls, 1)
        self.assertEqual(policy.failures, 0)

    def test_clamps_offscreen_coordinates(self):
        def transport(url, headers, payload, timeout):
            return {
                "choices": [
                    {"message": {"content": '{"action":{"type":"tap","x":99999,"y":99999}}'}}
                ]
            }

        action = self._policy(transport).act(observation(), Memory())
        self.assertEqual((action.x, action.y), (1079, 1919))

    def test_falls_back_when_transport_raises(self):
        def transport(url, headers, payload, timeout):
            raise OSError("connection reset")

        policy = self._policy(transport)
        action = policy.act(observation(), Memory())
        self.assertIn("llm:fallback", action.note)
        self.assertEqual(policy.failures, 1)

    def test_falls_back_without_api_key(self):
        policy = LLMPolicy(api_key="", fallback=HeuristicPolicy(seed=4))
        policy.begin(self.context)
        action = policy.act(observation(), Memory())
        self.assertIn("no-api-key", action.note)

    def test_prompt_contains_screen_and_history(self):
        captured = {}

        def transport(url, headers, payload, timeout):
            captured["payload"] = payload
            return {"choices": [{"message": {"content": '{"action":{"type":"wait","duration_ms":100}}'}}]}

        policy = self._policy(transport)
        memory = Memory()
        memory.recent.append(Action(type="tap", x=1, y=2, note="ui:Play"))
        policy.act(observation(xml=UI_XML), memory)
        messages = captured["payload"]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("1080x1920", messages[0]["content"])
        self.assertIn("Play", messages[-1]["content"])
        self.assertEqual(captured["payload"]["model"], policy.model)


if __name__ == "__main__":
    unittest.main()
