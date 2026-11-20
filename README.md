# apkharness

Black-box crash, ANR and performance testing for Android **game** APKs.

Point it at an `.apk`; it installs the build on a device or emulator, drives it with an
exploration policy, watches logcat and process liveness for failures, samples frame and
memory statistics, and writes a self-contained HTML report plus JUnit XML.

No third-party Python packages. No test hooks in the app. No rooted device.

```
apkharness demo          # full sample report in ~15 s, no device, no APK
```

---

## Inspect and test an APK

Inspect the manifest of your own APK without a connected device:

```bash
python -m apkharness inspect path/to/game.apk
```

To test it, plug in a device (or boot an emulator) with USB debugging authorised, then:

```bash
python -m apkharness run --apk path/to/game.apk --steps 400 --minutes 20 --policy heuristic
```

The package and launcher activity are picked up from the manifest automatically, the
APK is installed with `-r -g`, and the run ends with `report.html` + `junit.xml`.
A Unity game will show an empty accessibility tree on gameplay screens, which is
exactly what the perceptual-hash explorer is for; menus still come through as
labelled buttons.

No device available right now? `python -m apkharness demo` exercises the identical
pipeline against the built-in simulator.

---

## QA Studio (the editor you can hand to a tester)

```bash
python -m apkharness serve --open
```

That starts a local web app on `http://127.0.0.1:8765` with three panels:

1. **APK** - drag a build in; the manifest is parsed offline (package, version,
   launcher activity, ABIs, permissions) and shown immediately.
2. **Test plan** - a JSON editor holding the whole check logic (see below); it
   validates as you type and the same document runs from the CLI.
3. **Live screen** - the game as the harness sees it, updating while the test runs,
   plus a filmstrip, a progress bar, findings as they appear, and the checks table.

Choose **Quick** (50 steps), **Standard** (150), or **Extended** (400) for Auto QA.
With **AI player** enabled, enter a gameplay objective before starting exploration.
It guides the AI during the run and is saved with the report. For the Unity game,
**Use first-customer objective** fills in the joystick and till goal. This setup
uses the game-specific prompt idea described by [GamingAgent](https://github.com/lmgame-org/GamingAgent#customize-your-settings).

For the Unity game with the first-customer objective, choose **Guide me through the
first-customer tutorial** to play each step on the phone and confirm its expected result.

Press **Test** to start. During exploration, **Stop** pauses after the current step.
Press **Resume testing** to continue, or reconnect the same phone if the USB
connection drops. Auto QA pauses after every 100 steps and asks whether to continue.
Choose **Not now** to stay paused and start the next section later. If exploration
stays on the same screen after repeated inputs, Game Tester pauses with the last
screenshot and recent moves so you can help. Reopen Game Tester and choose
**Resume testing** to restore saved exploration progress. For a phone run, open
the game on the same phone first. When the run
finishes you get the verdict (PASS / WARN / FAIL), the checks table with expected vs
actual, the findings list, and downloads for `report.html`, `junit.xml`, the
recording (`session.gif` / `session.mp4`), `session.json` and `checks.json`.

```
POST /api/upload    raw APK bytes, X-Filename header
POST /api/plan      JSON plan (validated), POST /api/plan/default resets it
POST /api/run       start a session        POST /api/stop  stop it
GET  /api/state     status, frames, findings, checks, artifacts
GET  /api/frame?i=N live frame (N or "latest")
GET  /api/artifact?name=report.html
```

The server binds `127.0.0.1` only and keeps every artifact on disk under
`--workdir` (default `./studio`). It is a single-user QA tool, not a multi-tenant
service - do not expose the port.

### Device video vs frame recording

The plan's `capture` field picks how motion is captured:

| `capture` | What happens | Output |
| --- | --- | --- |
| `screenrecord` (default for devices) | the phone encodes its own H.264 via `adb shell screenrecord` while the harness drives it | `session.mp4`, real 30/60 fps |
| `both` | device video **and** an animated GIF from the captured frames | `session.mp4` + `session.gif` |
| `frames` | only per-step PNGs, assembled into a GIF | `session.gif` |

`screenrecord` is limited to 180 s per file by Android; the harness stops it
explicitly (`pkill -INT screenrecord`), pulls the file and cleans up the device.

### Connecting a phone

1. On the phone: **Settings → About phone → tap Build number 7×**, then
   **Developer options → USB debugging**.
2. Plug it in, accept the *Allow USB debugging* prompt.
3. In the studio press **Refresh** in the Device panel; the model appears and is
   selected automatically. Choose **Run on: Connected phone (real game)** and press
   **Test**.

If `adb devices` shows `unauthorized`, the RSA prompt on the phone has not been
accepted. If it shows `offline`, replug the cable and press Refresh.

### Run logic panel

While the test runs, every decision streams into the **Run logic** table: step,
the exact input sent, why it was chosen (`ui:` labelled control, `explore` novelty
input, `new` unseen screen, `dead` process gone), the frame's health and FPS. That
is the harness's reasoning, not a summary written afterwards - useful when a
tester asks "why did it tap there?".

### The check logic, editable

Everything the verdict depends on lives in one JSON plan
([examples/plan.json](examples/plan.json) is a full example):

```json
{
  "name": "Neon Drift smoke",
  "target": "device",
  "policy": "heuristic",
  "steps": 300,
  "minutes": 20,
  "seed": 7,
  "record_video": true,
  "ignore": ["libc.*harmless"],
  "checks": [
    {"id": "no-crash", "type": "no_findings", "kinds": ["java_crash", "native_crash"], "severity": "blocker"},
    {"id": "no-anr", "type": "no_findings", "kinds": ["anr"], "severity": "blocker"},
    {"id": "fps", "type": "min_metric", "metric": "avg_fps", "value": 45, "severity": "warning"},
    {"id": "memory", "type": "max_metric", "metric": "peak_pss_kb", "value": 1500000, "severity": "warning"},
    {"id": "explore", "type": "require_screens", "value": 3, "severity": "warning"}
  ]
}
```

| Check type | Meaning |
| --- | --- |
| `no_findings` | zero findings of `kinds` (all kinds when omitted) |
| `max_findings` | at most `value` findings of `kinds` |
| `min_metric` / `max_metric` | compare a session metric to `value` |
| `require_metric` | the metric must have been measured |
| `require_screens` | at least `value` distinct screens reached |

Metrics available to checks: `avg_fps`, `min_fps`, `avg_jank_percent`,
`peak_pss_kb`, `unique_crashes`, `total_crash_events`, `anr_count`, `java_crashes`,
`native_crashes`, `screens_explored`, `steps_run`, `relaunches`, `duration_s`.

Severity `blocker` fails the run (and JUnit); `warning` only downgrades the verdict
to WARN. `ignore` holds regexes matched against a finding's signature and message,
applied *before* checks, so known-benign noise does not fail the gate.

The same plan runs headless - useful in CI:

```bash
python -m apkharness run --plan examples/plan.json --apk game.apk
# prints a PASS/FAIL line per check, exits 2 when a blocker failed
```

### Recording

Every step's frame is captured. When the session ends the harness writes
`session.mp4` if `ffmpeg` is on PATH, otherwise an optimised `session.gif` using
Pillow, and otherwise leaves the PNG frames (the UI reports which backend was used).
The HUD burned into the recording shows the step number, the action that was sent and
a red `FINDING` marker on frames that produced a crash.

---

## Why a separate harness for games?

Games are the hard case for Android UI automation:

* they draw an opaque GL surface, so `uiautomator` usually exposes a single
  full-screen node and there is nothing to click by id or text;
* frames change constantly, so "has the screen changed?" cannot be answered by
  comparing images byte-for-byte;
* a crash often shows up as a black screen and a `SIGSEGV` in logcat, minutes after
  the input that caused it.

`apkharness` handles those three facts directly: it hashes frames with a perceptual
hash (64-bit dHash) to detect *new screens*, falls back to weighted random input on
game surfaces, and correlates logcat crash blocks with process death and the step
that preceded it.

---

## Quick start

### 1. Run the built-in simulator (no device needed)

```bash
cd AITeatApkForGames
python -m apkharness demo --steps 160
```

The simulator is a deterministic fake game ("Neon Drift") that renders real PNG
frames, serves a `uiautomator` hierarchy, streams threadtime logcat and fails on a
schedule (Java crash, native crash, ANR). The run produces exactly the artifacts a
real device run produces, including three findings.

Output ends with:

```
findings:
  - [java_crash] step 17: java.lang.NullPointerException
  - [native_crash] step 49: Fatal signal 11 (SIGSEGV)
  - [anr] step 76: ANR in com.example.neondrift (...)

report    : runs/20261111_113525_com.example.neondrift/report.html
```

Open `report.html` in any browser, or `session.json` for the raw data.

### 2. Run it against a real APK

Prerequisites:

* Android platform-tools (`adb` on `PATH`, or pass `--adb C:\path\to\adb.exe`)
* an emulator or a phone with USB debugging authorised (`apkharness devices` lists them)
* Python 3.9+

```bash
# read the manifest offline first - no device needed
python -m apkharness inspect woolfunv1.apk

# package name and launcher activity come from the manifest (or pass them explicitly)
python -m apkharness run --apk C:\builds\neondrift-1.4.2.apk --steps 300 --minutes 20

# explicit target
python -m apkharness run --apk game.apk --package com.studio.neondrift \
       --activity com.studio.neondrift/.MainActivity --policy heuristic --seed 42
```

The app is installed with `adb install -r -g` (reinstall, grant runtime permissions)
and relaunched after each crash until the relaunch budget is spent.

```bash
python -m apkharness devices            # list targets, --json for tooling
python -m apkharness inspect app.apk --json
python -m apkharness run --apk app.apk --policy scripted --actions examples/actions.json
python -m apkharness report runs/20261111_113525_com.example.neondrift --junit
```

Exit codes: `0` finished, `1` error/usage, `2` crashes found **and** `--fail-on-crash`
was passed, `130` interrupted (report is still written).

---

## What it looks for

| Kind | Source | Typical signature |
| --- | --- | --- |
| `java_crash` | `AndroidRuntime` `FATAL EXCEPTION` block | `java.lang.NullPointerException` + stack |
| `native_crash` | `Fatal signal N (SIGSEGV/SIGABRT)` | `libunity.so`, `libUE4.so` frames |
| `anr` | `ActivityManager: ANR in <pkg>` | `Input dispatching timed out` |
| `process_death` | `ActivityManager: Process ... has died`, or the pid vanishes | silent death |
| `low_memory` | `lowmemorykiller` | LMK kill of the tested package |
| `exception` | engine-level "uncaught exception" lines | Unity/Unreal/RN logging |

Findings are deduplicated by a normalised signature (addresses, pids and numbers are
stripped), so a crash that fires 40 times is one finding with `count: 40` and the first
stack trace plus screenshot.

Each finding carries the step number, timestamp, stack and (when a screenshot was in
flight at that step) the frame that was on screen.

---

## How it decides what to tap

Three interchangeable policies implement the same `act(observation) -> Action` contract.

**`heuristic`** (default, no network, reproducible with `--seed`)

1. If the accessibility tree has labelled, clickable nodes, prefer those
   (`ui:Play` in the timeline); avoid re-tapping what was just tapped.
2. On a game surface, mix taps (~58 %), swipes (~20 %), back (~10 %) and waits.
3. Score novelty with the perceptual hash: a frame more than `--novelty-threshold`
   bits away from every known frame counts as a new screen and resets the mixed
   strategy toward exploration.
4. If one screen has been visited `stuck_screens` times, press back or scroll to
   escape it.

**`llm`** (any OpenAI-compatible `/chat/completions` endpoint)

The model receives the screen size, a ranked accessibility summary, the last six
inputs, recent error/warning logcat lines and the crash history, and must reply with a
single JSON action. Every reply is validated against the same `Action` rules as every
other policy and clamped to the screen; any timeout, HTTP error, malformed JSON or
off-screen coordinate falls back to the heuristic for that step (and is counted in the
report as `failures`). Screenshots can be included with `--llm-vision`.

```bash
set OPENAI_API_KEY=sk-...
python -m apkharness run --apk game.apk --policy llm --llm-model gpt-4o-mini --steps 200
```

Environment variables: `APKHARNESS_LLM_API_KEY` / `OPENAI_API_KEY`,
`APKHARNESS_LLM_MODEL` / `OPENAI_MODEL`, `APKHARNESS_LLM_BASE_URL` / `OPENAI_BASE_URL`
(for local servers such as vLLM or LM Studio).

**`scripted`** — replay a JSON action list, optionally looping. Use it for a
reproducible regression script:

```json
{"loop": true, "actions": [
  {"type": "wait", "duration_ms": 1500},
  {"type": "tap", "x": 540, "y": 1320, "note": "play"},
  {"type": "swipe", "x": 540, "y": 1400, "x2": 540, "y2": 700, "duration_ms": 250}
]}
```

`python -m apkharness check-script examples/actions.json` validates one before use.

---

## Performance sampling

Every `--metrics-every` steps (default 5) the harness runs `dumpsys gfxinfo`,
`dumpsys meminfo`, `dumpsys cpuinfo` and `dumpsys battery` for the package and parses:

* frame count, janky frame percentage, 50/90/95/99th percentile frame times
* an FPS estimate from the delta in `Total frames rendered` (window ≥ 0.3 s, reset-aware)
* total PSS, Java and native heap, CPU share, battery level and temperature

The report charts FPS and PSS over the run and puts the worst numbers in the summary
cards. `metrics.json` holds every sample.

FPS is an estimate derived from gfxinfo counters, not a measurement from inside the
engine. For real frame timing in a shipped game, instrument the game itself; use this
to find *regressions and stalls* across builds.

---

## Output layout

```
runs/20261111_113525_com.example.neondrift/
├── report.html        self-contained report (images inlined where practical)
├── session.json       config, metadata, summary, every step, every finding
├── junit.xml          one testcase per finding; fails CI when a crash is found
├── logcat.txt         the logcat slices collected during the session
├── metrics.json       all performance samples
└── screenshots/       step_00017_crash.png, step_00001_new.png, ...
```

JUnit maps cleanly onto CI: `testsuite/failures` equals the number of distinct
findings, so a crash fails the build without extra glue.

Report sections: verdict badge, summary cards (steps, crashes, ANRs, screens, FPS,
jank, peak memory), session metadata (device, Android version, APK SHA-256, policy),
one card per finding with stack and crash frame, FPS/PSS charts, and the full input
timeline marking new screens and crash steps.

---

## Options worth knowing

| Flag | Default | Meaning |
| --- | --- | --- |
| `--steps` | 200 | maximum inputs to send |
| `--minutes` | unlimited | wall-clock budget; whichever limit hits first |
| `--delay` | 0.4 s | pause between inputs |
| `--seed` | 7 | makes `heuristic` runs reproducible |
| `--novelty-threshold` | 10 | hash distance that counts as a new screen |
| `--max-relaunches` | 3 | relaunches after a crash before giving up |
| `--stop-after-crashes` | 0 | stop after N distinct findings |
| `--screenshot-every` | 1 | save a frame every N steps |
| `--metrics-every` | 5 | sample `dumpsys` every N steps |
| `--no-install` | off | APK is already installed; `--package` required |
| `--no-relaunch` | off | stop at the first crash instead of relaunching |
| `--simulate` | off | run the built-in simulator with `run` semantics |

---

## Project layout

```
apkharness/
├── adb.py          adb wrapper: devices, install, launch, logcat, screencap, input, dumpsys
├── apk.py          offline APK inspection: binary AndroidManifest (AXML) parser
├── device.py       Device interface, AdbDevice, Observation, apply_action()
├── simulator.py    deterministic fake game (PNG frames, logcat, scheduled failures)
├── run.py          Session: install → drive → detect → sample → report
├── policies/       heuristic, llm, scripted + shared Memory/context
├── logs.py         threadtime parsing, crash/ANR detection, signature dedupe
├── metrics.py      gfxinfo / meminfo / cpuinfo / battery parsers
├── ui.py           uiautomator hierarchy parsing, node ranking, prompt summary
├── png.py          PNG encode/decode + perceptual hash (stdlib only)
├── plan.py         editable test plan + check evaluation (the QA logic)
├── studio.py       HTTP API for the web editor (stdlib http.server)
├── webui.py        the single-page studio UI
├── video.py        session recording (mp4 via ffmpeg, gif via Pillow)
├── report.py       HTML report, JUnit XML, session.json loading
└── cli.py          argparse front-end
tests/              unittest suite (172 tests, no device required)
examples/           action script, example plan, sample demo run
```

### Design notes

* **The harness never needs root.** Everything goes through the public `adb shell`
  surface (`input`, `screencap`, `uiautomator dump`, `dumpsys`).
* **The APK is read, not guessed.** A small binary-XML parser extracts package,
  version, launcher activity, SDK levels, permissions and ABIs offline — no `aapt`,
  no install round trip.
* **Detection is separable from collection.** `logs.CrashDetector` is a pure function
  of log lines, so its fixtures run in milliseconds in CI.
* **The policy is swappable.** The runner only depends on `Observation`, `Action` and
  `Memory`; adding a policy (vision model, RL agent, recorded trace) is one file.
* **Failures never wedge a session.** Policy exceptions, adb timeouts and screenshot
  failures degrade to a wait/continue instead of aborting the run.

---

## Tests

```bash
python -m unittest discover -s tests        # 172 tests, ~6 s, no device
```

Coverage: action validation, binary manifest parsing (synthetic + real APK), PNG
round-trip and hash stability, logcat parsing and every crash category, dumpsys
parsers against real-world output, the adb layer with a stubbed transport (device
listing, screen size, screencap fallback, install failures, logcat dedupe), UI
ranking, policy determinism and LLM fallback behaviour, simulator behaviour,
report/JUnit escaping, and a full simulated session asserting that artifacts,
crashes and metrics all land correctly.

---

## Limitations

* **Coordinates are absolute pixels** in the current orientation; the harness does not
  rotate the device or model notches/cutouts.
* **`uiautomator dump` can be slow** (100–400 ms) on dense screens; it is sampled every
  step by default, lower `--ui-every` on slow lab devices.
* **Frame rate is derived from gfxinfo counters**, not engine instrumentation.
* **No audio, network or GPU-driver level checks.** This is a black-box UI/perf harness.
* **LLM policies cost money and add latency**; the fallback keeps sessions running but
  invalidates the "same actions" reproducibility that the heuristic and scripted
  policies provide.
* **The simulator is a model, not Android.** It exists to demo and test the harness; it
  is not a compatibility shim for real APKs.

### Safety

`adb install -r` replaces the installed build, and relaunching kills the app process.
Use a dedicated test device or emulator; do not point this at a device with data you
care about, and do not run it against production accounts.
