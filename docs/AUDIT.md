# APKHarness — Phase 1 audit & Phase 2 design

Audited: 2026-11-11, against the working tree in this folder.
Evidence: `python -m unittest discover -s tests` → **177 tests, 0 failures, 1 skip** (the skip is
the real-APK fixture test, which needs `woolfunv1.apk` next to the code).

---

## 1. What actually exists (measured, not aspirational)

| Module | Lines | Role | Verified by |
| --- | ---: | --- | --- |
| `apk.py` | 321 | Binary AXML parse: package, version, launcher, SDK, permissions, ABIs | `test_apk` (14) incl. real 123 MB APK |
| `adb.py` | 425 | adb wrapper: devices, install, launch, logcat, screencap, uiautomator, dumpsys, SurfaceFlinger, screenrecord plumbing | `test_adb` (20) |
| `device.py` | 310 | `Device` abstraction, `AdbDevice`, `SimDevice` binding, observation, input probe | `test_adb`, `test_simulator` |
| `simulator.py` | 491 | Deterministic fake Unity game: PNG frames, hierarchy, logcat, scheduled crashes | `test_simulator` (7) |
| `run.py` | 622 | Session orchestration, crash correlation, metrics sampling, artifacts, phases | `test_session` (10) |
| `logs.py` | 322 | threadtime parsing, Java/native/ANR/LMK detection, signature dedupe | `test_logs` (11) |
| `metrics.py` | 240 | gfxinfo/meminfo/cpuinfo/battery parsers + SurfaceFlinger frame pacing | `test_metrics` (13) |
| `ui.py` | 195 | uiautomator hierarchy parsing, node ranking, prompt summary | `test_ui` (7) |
| `png.py` | 234 | PNG codec + 64-bit perceptual hash (no Pillow required) | `test_png` (6) |
| `plan.py` | 518 | Editable plan: checks, severity, ignore regex, validation, evaluation | `test_plan` (23) |
| `policies/` | 640 | heuristic / LLM / scripted / observe, shared `Memory` | `test_policies` (21) |
| `report.py` | 443 | HTML + JUnit + JSON report, checks table, evidence images | `test_report` (7) |
| `studio.py` | 795 | HTTP API, worker thread, device readiness, capture, artifacts | `test_studio` (21) |
| `webui.py` | 932 | Single-page dashboard (pipeline, live view, run logic, checks) | e2e via API |
| `video.py` | 230 | MP4 (ffmpeg) or palette GIF from frames, HUD overlay | `test_plan` video tests |
| `screen.py` | 137 | `screenrecord` start/stop/pull with 180 s segment handling | `test_screen` (7) |
| `cli.py` | 373 | `devices inspect run demo report check-script serve` | manual + tests |

Working today, proven on hardware and in CI:

- offline APK inspection; install/launch; UI hierarchy + screenshots at 1080×2400;
- **device video** via `screenrecord` (verified: 15 MB MP4 from the Redmi);
- FPS from SurfaceFlinger `--latency` (Unity has no `gfxinfo`), memory/CPU/battery;
- crash/ANR detection and dedupe with stacks, screenshots, step attribution;
- three interactive policies + watch-only; plan/check engine with blockers and JUnit;
- dashboard with device readiness (adb / authorised / input injection), live frames, run log;
- real-device reality check: MIUI revokes `INJECT_EVENTS`, so drive-mode needs
  *USB debugging (Security settings)*; watch-only works without it.

## 2. Gap analysis against the requested product

Status: **DONE** (implemented + tested), **PARTIAL**, **MISSING**.

| Requirement area | Status | Evidence / gap |
| --- | --- | --- |
| APK upload + validation + metadata | DONE | `/api/upload`, APK card shows 8 fields |
| Device/emulator panel, multi-device | PARTIAL | lists all, selects one; no emulator lifecycle control |
| Requirement document upload (.md/.txt/.pdf/.docx) | **MISSING** | nothing parses documents today |
| Requirement → test-case generation + traceability | **MISSING** | plan checks are hand-written |
| Editable, approvable test plan | PARTIAL | JSON plan editor only, no per-case review |
| Screen-state detection (menu/gameplay/gameover/…) | **MISSING** | only "new screen" hashing |
| OCR / text recognition | **MISSING** | no OCR (no third-party deps today) |
| Gameplay agent with verify-after-action | PARTIAL | policies act, but no post-action assertion |
| Levels / economy / ads / IAP modules | **MISSING** | no domain testers |
| Currency balance verification | **MISSING** | no screen text reading |
| Crash/ANR detection + evidence | DONE | logcat + process + dedupe + screenshots |
| Performance thresholds configurable | DONE | plan checks (`min_metric`/`max_metric`) |
| Dashboard KPI overview + charts | PARTIAL | run-level cards; no cross-session KPIs/charts |
| Executive HTML/JUnit/JSON report | PARTIAL | session report exists; no requirement-wise, level-wise, ads/IAP sections |
| PDF export | **MISSING** | — |
| Session persistence / resume after crash | **MISSING** | sessions are in-memory + final artifacts |
| Pause / resume / retry-failed | **MISSING** | only Stop |
| Multi-session history/KPIs | **MISSING** | no database, runs are folders |
| Security: upload validation, no doc execution | PARTIAL | APK validated; docs not yet accepted |

## 3. Risks and hard truths

1. **Input injection is an OEM permission, not a code problem.** Verified on the Redmi:
   `input`, `monkey`, `sendevent` are all denied, no root. The harness must keep a
   watch-only mode and a *readiness gate* (already implemented) rather than pretend.
2. **Visual proof ≠ logic proof.** Without instrumented counters, "coins went 1000 → 800"
   can only be inferred from pixels/OCR. The product needs an explicit
   `VISUALLY_OBSERVED` vs `INSTRUMENTED` evidence grade, and must never turn the former
   into a PASS on arithmetic.
3. **No OCR today.** Adding Tesseract/Paddle would break the zero-dependency promise and
   is a heavy install. Plan: pluggable `visual_verifier` with a pure-Python template/digit
   reader for HUD numbers first, OCR adapter behind an optional extra.
4. **Ads/IAP cannot be truly automated black-box.** No-fill, test ad units, sandbox
   accounts, and Play Billing make this a *guided* test with explicit BLOCKED outcomes.
   Anyone claiming otherwise is fabricating results.
5. **`screenrecord` caps at 180 s per file**; long sessions need segmentation (planned).
6. **Single-process HTTP server** with a worker thread: fine for one tester, not
   multi-user. Must stay bound to 127.0.0.1 and never be exposed.
7. **No database**: run folders + JSON scale to hundreds of sessions, not thousands.

## 4. Proposed architecture (incremental, keeps existing modules)

```
requirements.py   document → Requirement[]        (md/txt native, docx/pdf optional)
analyzer.py       Requirement[] → features, deps, state graph, clarifications
testgen.py        Requirement[] → TestCase[]      (deterministic templates + LLM hook)
cases.py          TestCase model, statuses, traceability, persistence (JSON)
orchestrator.py   runs suites: suite → cases → session(s), resumable
states.py         screen classifier (hash + hierarchy + optional OCR)
visual.py         number/text extraction, change detection, evidence grading
domain/           economy.py, ads.py, iap.py, levels.py  (assertions + evidence)
history.py        cross-session index (SQLite) for dashboard KPIs/charts
report_qa.py      requirement-wise, level-wise, ads/IAP sections + PDF (optional)
```

Data model (JSON today, SQLite when history lands):

```
Requirement{id, feature, text, source, priority, status, note}
TestCase{id, requirement_id, title, feature, preconditions[], steps[],
         expected, priority, mode(auto/manual), status, actual, evidence{}}
Suite{id, apk, doc, cases[], approved, created_at}
Run{session_dir, coverage, results{case_id: status}}
```

Execution pipeline:

```
upload APK ─┐
upload doc ─┴→ analyze → generate cases → tester reviews/approves → orchestrator
   → per case: prepare (precondition) → act (policy) → observe → verify (multi-method)
   → record evidence + status → next case
   → stability/perf monitor runs alongside → report + KPIs
```

Verdict rules: `PASS` only if every `mandatory` case is PASS and coverage ≥ threshold;
`INCOMPLETE` when mandatory cases are NOT_RUN/BLOCKED; `FAIL` on any mandatory FAIL;
`WARN` for advisory-only issues. Enforced in code, not prose.

## 5. Delivery plan (with acceptance criteria)

| Phase | Scope | Done when |
| --- | --- | --- |
| 3 | `requirements.py`, `testgen.py`, `cases.py`, studio upload + review UI, tests | a real `.md` yields traceable REQ→TC rows, editable, approved, 20+ tests |
| 4 | `states.py`, `visual.py`, verify-after-action in policies | each action produces a verified transition or UNVERIFIED, on device |
| 5 | economy/ads/IAP/levels testers | cases execute with evidence and honest BLOCKED states |
| 6 | crash analyzer, ANR watchdog, perf gates | no silent failure; every finding has evidence |
| 7 | dashboard KPIs/charts, history index, PDF report | cross-session dashboard + requirement-wise report |
| 8 | regression: unit, simulator, emulator, device, recovery | full suite green, real-device run captured |

Phase 3 starts in this commit; later phases build on it without touching working paths.
