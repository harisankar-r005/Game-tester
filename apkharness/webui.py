"""The single-page UI served by :mod:`apkharness.studio`.

Plain HTML/CSS/JS, no build step, no CDN: it has to work on an air-gapped QA
machine. The page polls ``/api/state`` and updates in place, so a running test
shows frames, decisions, findings and checks as they appear.
"""

UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>apkharness studio</title>
<style>
:root{
  --bg:#0b0f14; --panel:#131a23; --panel2:#182130; --line:#25303f; --text:#e6edf3;
  --muted:#8b98a8; --accent:#58a6ff; --good:#3fb950; --bad:#f85149; --warn:#d29922;
  --mono:ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;
}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 15% -10%,#16202c 0%,var(--bg) 55%);
  color:var(--text);font:14px/1.5 "Segoe UI",Roboto,Helvetica,Arial,sans-serif;min-height:100vh}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.top{display:flex;align-items:center;gap:12px;padding:12px 18px;border-bottom:1px solid var(--line);
  background:rgba(13,18,25,.9);backdrop-filter:blur(8px);position:sticky;top:0;z-index:20}
.brand{display:flex;align-items:center;gap:10px;font-weight:650;letter-spacing:.2px}
.logo{width:30px;height:30px;border-radius:8px;background:linear-gradient(135deg,#58a6ff,#7c3aed);
  display:grid;place-items:center;font-size:16px;color:#04121f;font-weight:800}
.brand small{display:block;font-weight:400;font-size:11px;color:var(--muted);letter-spacing:.04em}
.spacer{flex:1}
.pill{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;padding:5px 10px;
  border-radius:999px;border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.pill.running{color:#0d1117;background:var(--warn);border-color:var(--warn)}
.pill.done{color:#0d1117;background:var(--good);border-color:var(--good)}
.pill.error{color:#fff;background:var(--bad);border-color:var(--bad)}
.chip{font-family:var(--mono);font-size:11px;color:var(--muted);border:1px solid var(--line);
  border-radius:7px;padding:4px 8px;max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
button{font:inherit;font-weight:600;border-radius:9px;border:1px solid var(--line);background:var(--panel2);
  color:var(--text);padding:9px 14px;cursor:pointer;transition:.15s background}
button:hover:not(:disabled){background:#203044}
button:disabled{opacity:.45;cursor:not-allowed}
button.primary{background:linear-gradient(180deg,#2f81f7,#1f6feb);border-color:#1f6feb;color:#fff}
button.danger{border-color:#5c2126;color:#ffb3ad;background:#2a1417}
button.small{padding:5px 9px;font-size:12px;border-radius:7px}
button.tiny{padding:3px 7px;font-size:11px;border-radius:6px}
button.on{background:#1f6feb;border-color:#1f6feb;color:#fff}
main{display:grid;grid-template-columns:370px minmax(0,1fr);gap:16px;padding:16px 18px 60px;
  max-width:1620px;margin:0 auto;align-items:start}
@media(max-width:1120px){main{grid-template-columns:1fr}}
.stack{display:flex;flex-direction:column;gap:14px;min-width:0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:14px 15px}
.card h2{margin:0 0 10px;font-size:11.5px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
  font-weight:700;display:flex;align-items:center;gap:8px}
.card h2 .count{font-family:var(--mono);color:var(--text);font-weight:600;letter-spacing:0;text-transform:none}
.drop{border:1.5px dashed #2f3d4f;border-radius:11px;padding:16px 12px;text-align:center;cursor:pointer}
.drop:hover,.drop.over{background:#16202c;border-color:var(--accent)}
.drop b{display:block;margin-bottom:2px}
.drop span{font-size:12px;color:var(--muted)}
.apk-info{display:grid;grid-template-columns:auto 1fr;gap:3px 10px;margin-top:11px;font-size:12.5px}
.apk-info dt{color:var(--muted)}
.apk-info dd{margin:0;font-family:var(--mono);font-size:11.5px;overflow-wrap:anywhere}
textarea{width:100%;min-height:300px;resize:vertical;background:#0b1118;color:#d7e2ee;border:1px solid var(--line);
  border-radius:10px;padding:11px 12px;font-family:var(--mono);font-size:12px;line-height:1.55;tab-size:2}
textarea:focus{outline:1px solid var(--accent)}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.plan-errors{margin:10px 0 0;padding:9px 11px;border-radius:9px;background:#2a1417;border:1px solid #5c2126;
  color:#ffb3ad;font-size:12px;font-family:var(--mono);white-space:pre-wrap}
.ready{display:grid;grid-template-columns:1fr 1fr;gap:4px 10px;margin:8px 0 4px;font-size:12px}
.ready .r{display:flex;gap:7px;align-items:center;color:var(--muted);font-family:var(--mono);font-size:11px}
.ready .r b{width:14px;text-align:center}
.ready .r.ok{color:#7dd3a0}
.ready .r.bad{color:#ffb3ad}
.banner{margin-top:8px;padding:9px 11px;border-radius:9px;background:#2a1417;border:1px solid #5c2126;
  color:#ffb3ad;font-size:12px;line-height:1.45}
.dev{display:flex;flex-direction:column;gap:6px;margin:8px 0}
.dev label{display:flex;gap:8px;align-items:center;border:1px solid var(--line);border-radius:8px;
  padding:7px 9px;cursor:pointer;font-size:12.5px}
.dev label.sel{border-color:var(--accent);background:#16202c}
.dev input{accent-color:var(--accent)}
.dev .m{font-family:var(--mono);font-size:11px;color:var(--muted);margin-left:auto}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:9px}
.field{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--muted);
  text-transform:uppercase;letter-spacing:.05em}
.field select,.field input{font:13px/1.4 inherit;color:var(--text);background:#0b1118;border:1px solid var(--line);
  border-radius:7px;padding:6px 8px;width:100%}
.field input[type=checkbox]{width:auto}
.stage{position:relative;border:1px solid var(--line);border-radius:12px;overflow:auto;
  background:repeating-conic-gradient(#0e141c 0% 25%,#0b1117 0% 50%) 50%/18px 18px;
  min-height:40vh;max-height:66vh;display:grid;place-items:center}
.stage img{display:block;height:auto;max-width:none;image-rendering:auto}
.stage img.pixel{image-rendering:pixelated}
.stage .placeholder{color:var(--muted);font-size:13px;text-align:center;padding:40px 24px}
.overlay{position:absolute;inset:0;pointer-events:none;display:flex;justify-content:space-between;
  align-items:flex-start;padding:10px;font-family:var(--mono);font-size:11px}
.overlay .badge-rec{background:rgba(6,10,15,.8);border:1px solid #5c2126;color:#ffb3ad;padding:3px 8px;
  border-radius:6px;display:none;align-items:center;gap:6px}
.overlay .badge-rec.on{display:flex}
.dot{width:8px;height:8px;border-radius:50%;background:var(--bad);animation:pulse 1.1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
.res{font-family:var(--mono);font-size:11px;color:var(--muted);background:rgba(6,10,15,.8);
  border:1px solid var(--line);padding:3px 8px;border-radius:6px}
.bar{height:6px;border-radius:99px;background:#1b2431;overflow:hidden;margin:11px 0 6px}
.bar > i{display:block;height:100%;width:0;background:linear-gradient(90deg,#1f6feb,#58a6ff);transition:width .3s}
.meta{display:flex;gap:14px;flex-wrap:wrap;font-family:var(--mono);font-size:11.5px;color:var(--muted)}
.film{display:flex;gap:7px;overflow-x:auto;padding:4px 0 2px}
.film img{height:70px;border-radius:6px;border:1px solid var(--line);cursor:pointer;image-rendering:pixelated}
.film img.finding{border-color:var(--bad)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
  border-bottom:1px solid var(--line);padding:6px 8px;font-weight:700}
td{border-bottom:1px solid #1a222d;padding:6px 8px;vertical-align:top}
tr:last-child td{border-bottom:none}
.mono{font-family:var(--mono);font-size:11.5px}
.muted{color:var(--muted)}
.badge{font-size:10px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;padding:3px 7px;
  border-radius:5px;white-space:nowrap}
.badge.pass{background:rgba(63,185,80,.15);color:#56d364;border:1px solid rgba(63,185,80,.35)}
.badge.fail{background:rgba(248,81,73,.14);color:#ff7b72;border:1px solid rgba(248,81,73,.4)}
.badge.warn{background:rgba(210,153,34,.14);color:#e3b341;border:1px solid rgba(210,153,34,.4)}
.kind{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;padding:2px 6px;
  border-radius:4px;background:#22303f;color:#c9d1d9;white-space:nowrap}
.kind.java_crash,.kind.native_crash,.kind.exception{background:#3a1a1e;color:#ffb3ad}
.kind.anr{background:#2b1f45;color:#c7b3ff}
.kind.process_death{background:#12302c;color:#8be0d4}
.tag{font-size:10px;font-weight:700;letter-spacing:.05em;padding:1px 5px;border-radius:4px;
  background:#1c2735;color:#9fb3c8;font-family:var(--mono)}
.tag.new{background:#12303f;color:#7dd3fc}
.tag.dead{background:#3a1a1e;color:#ffb3ad}
.log{max-height:360px;overflow:auto;border:1px solid var(--line);border-radius:9px}
.log table{font-size:12px}
.log tr.finding td{background:rgba(248,81,73,.07)}
.verdict{display:flex;gap:14px;align-items:center;padding:13px 16px;border-radius:12px;border:1px solid var(--line);
  background:var(--panel);flex-wrap:wrap}
.verdict .big{font-size:22px;font-weight:800;letter-spacing:.04em}
.verdict.pass{border-color:rgba(63,185,80,.4);background:rgba(63,185,80,.07)}
.verdict.pass .big{color:#56d364}
.verdict.fail{border-color:rgba(248,81,73,.45);background:rgba(248,81,73,.07)}
.verdict.fail .big{color:#ff7b72}
.verdict.warn{border-color:rgba(210,153,34,.45);background:rgba(210,153,34,.07)}
.verdict.warn .big{color:#e3b341}
.verdict .sub{font-size:12px;color:var(--muted)}
.artifacts{display:flex;gap:7px;flex-wrap:wrap;margin-left:auto}
.artifacts a{border:1px solid var(--line);background:var(--panel2);padding:6px 11px;border-radius:8px;
  font-size:12px;font-weight:600;color:var(--text)}
.artifacts a:hover{border-color:var(--accent);text-decoration:none}
details{border:1px solid var(--line);border-radius:10px;padding:9px 12px;background:#101720}
details summary{cursor:pointer;font-weight:600;font-size:12.5px}
details p,details li{font-size:12.5px;color:#b9c6d4}
code{font-family:var(--mono);font-size:11.5px;background:#0b1118;border:1px solid var(--line);
  border-radius:4px;padding:1px 5px}
.pipe{display:flex;gap:8px;align-items:center;flex-wrap:wrap;max-width:1620px;margin:14px auto 0;
  padding:10px 14px;background:var(--panel);border:1px solid var(--line);border-radius:12px}
.pipe .step{display:flex;gap:7px;align-items:center;font-size:12px;color:var(--muted);
  border:1px solid var(--line);border-radius:8px;padding:5px 10px;font-weight:600}
.pipe .step b{display:grid;place-items:center;width:18px;height:18px;border-radius:50%;
  background:#1c2735;color:#9fb3c8;font-size:10px}
.pipe .step span{font-family:var(--mono);font-weight:400;color:var(--muted);max-width:220px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pipe .step.active{border-color:var(--accent);color:var(--text);background:#16202c}
.pipe .step.active b{background:var(--accent);color:#04121f}
.pipe .step.ok{border-color:rgba(63,185,80,.4);color:#cfe9d4}
.pipe .step.ok b{background:rgba(63,185,80,.25);color:#56d364}
.pipe .step.err{border-color:rgba(248,81,73,.45);color:#ffb3ad}
.pipe .step.err b{background:rgba(248,81,73,.25);color:#ff7b72}
.pipe-note{margin-left:auto;font-size:11.5px;color:var(--muted)}
.toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%) translateY(80px);background:#2a1417;
  border:1px solid #5c2126;color:#ffb3ad;padding:10px 16px;border-radius:10px;font-size:13px;
  opacity:0;transition:.25s;z-index:50;max-width:80vw}
.toast.show{transform:translateX(-50%) translateY(0);opacity:1}
.empty{color:var(--muted);font-size:12.5px;padding:6px 2px}
table.rules td{padding:4px 4px;vertical-align:middle}
table.rules select,table.rules input,.small-select{font:12px inherit;color:var(--text);background:#0b1118;
  border:1px solid var(--line);border-radius:6px;padding:3px 5px;max-width:100%}
table.rules input.id{width:110px} table.rules input.val{width:90px}
.kinds{display:flex;flex-wrap:wrap;gap:3px 8px;font-size:11px;color:var(--muted)}
.kinds label{display:flex;align-items:center;gap:3px;white-space:nowrap}
.sev-blocker{color:var(--bad)} .sev-warning{color:var(--warn)}
[hidden]{display:none!important}
.kv{display:flex;gap:14px;flex-wrap:wrap}
.kv span{font-family:var(--mono);font-size:11.5px;color:var(--muted)}
.kv b{color:var(--text);font-weight:600}
</style>
</head>
<body>
<div class="top">
  <div class="brand">
    <div class="logo">A</div>
    <div>apkharness studio<small>APK test editor &amp; device runner</small></div>
  </div>
  <span class="pill" id="statusPill">idle</span>
  <span class="chip" id="deviceChip">checking adb…</span>
  <div class="spacer"></div>
  <a href="/" target="_blank" style="font-weight:600;padding:0 6px">← Simple tester</a>
  <a href="/?help=advanced" target="_blank" style="font-weight:600;padding:0 6px">❓ How to use</a>
  <button class="primary" id="runBtn" disabled>▶ Start test</button>
  <button class="danger" id="stopBtn" disabled>■ Stop</button>
  <button id="restartBtn" title="clear the last session, keep APK and plan">↻ Restart</button>
</div>

<div class="pipe" id="pipe">
  <div class="step" data-stage="apk"><b>1</b> APK <span id="pipeApk">—</span></div>
  <div class="step" data-stage="install"><b>2</b> Install</div>
  <div class="step" data-stage="launch"><b>3</b> Launch</div>
  <div class="step" data-stage="explore"><b>4</b> Explore &amp; record</div>
  <div class="step" data-stage="report"><b>5</b> Checks &amp; report</div>
  <div class="pipe-note" id="pipeNote">upload an APK and press Start test</div>
</div>

<main>
  <div class="stack">
    <section class="card">
      <h2>1 · APK</h2>
      <div class="drop" id="drop">
        <b>Drop an APK here</b>
        <span>or click to browse · manifest is read offline</span>
        <input type="file" id="file" accept=".apk" hidden>
      </div>
      <div id="apkBox"></div>
    </section>

    <section class="card">
      <h2>2 · Requirements <span class="count" id="reqCount"></span></h2>
      <div class="drop" id="docDrop">
        <b>Drop the game spec here</b>
        <span>.md · .txt · .docx · .pdf* &nbsp;(*needs pypdf)</span>
        <input type="file" id="docFile" accept=".md,.markdown,.txt,.docx,.pdf" hidden>
      </div>
      <div id="reqBox"></div>
    </section>

    <section class="card">
      <h2>3 · Device <span class="count" id="devCount"></span>
        <button class="tiny" id="refreshDev" style="margin-left:auto">Refresh</button></h2>
      <div class="dev" id="devList"><div class="empty">looking for devices…</div></div>
      <div id="devHint" class="empty"></div>
      <div id="readyList" class="ready"></div>
      <div id="readyBanner" class="banner" hidden></div>
      <div class="grid2" style="margin-top:8px">
        <div class="field"><span>Run on</span>
          <select id="optTarget" onchange="setTarget(this.value)">
            <option value="device">Connected phone (real game)</option>
            <option value="simulator">Simulator (no device)</option>
          </select>
        </div>
        <div class="field"><span>Capture</span>
          <select id="optCapture">
            <option value="screenrecord">Device video (screenrecord)</option>
            <option value="both">Video + frame GIF</option>
            <option value="frames">Frames only (GIF)</option>
          </select>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>4 · Run options</h2>
      <div class="grid2">
        <div class="field"><span>Policy</span>
          <select id="optPolicy">
            <option value="heuristic">heuristic explorer</option>
            <option value="llm">LLM policy</option>
            <option value="scripted">scripted actions</option>
            <option value="observe">observe only (no input)</option>
          </select>
        </div>
        <div class="field"><span>Seed</span><input type="number" id="optSeed" min="0" step="1"></div>
        <div class="field"><span>Max steps</span><input type="number" id="optSteps" min="1" step="10"></div>
        <div class="field"><span>Time budget (min)</span><input type="number" id="optMinutes" min="1" step="1"></div>
        <div class="field"><span>Video fps</span><input type="number" id="optFps" min="1" max="30" step="1"></div>
        <div class="field"><span>Install</span>
          <label style="display:flex;gap:7px;align-items:center;text-transform:none;font-size:13px;color:var(--text)">
            <input type="checkbox" id="optInstall"> reinstall APK
          </label>
        </div>
        <div class="field"><span>Record</span>
          <label style="display:flex;gap:7px;align-items:center;text-transform:none;font-size:13px;color:var(--text)">
            <input type="checkbox" id="optRecord"> build a recording
          </label>
        </div>
      </div>
      <div class="row" style="margin-top:10px">
        <button class="small primary" id="applyOpts">Apply options</button>
        <span class="muted" style="font-size:11.5px">writes into the plan below</span>
      </div>
    </section>

    <section class="card">
      <h2>5 · Test plan <span class="muted" style="font-weight:400;text-transform:none;letter-spacing:0">check logic</span></h2>
      <div class="row" style="margin-bottom:8px;gap:6px">
        <button class="small on" id="modeVisual">Visual rules</button>
        <button class="small" id="modeJson">JSON</button>
        <span class="muted" style="font-size:11.5px;margin-left:auto">both edit the same plan</span>
      </div>
      <div id="ruleBuilder">
        <div style="overflow-x:auto"><table class="rules">
          <thead><tr><th>ID</th><th>Rule</th><th>Finding kinds / metric</th><th>Value</th><th>Severity</th><th></th></tr></thead>
          <tbody id="rulesBody"></tbody>
        </table></div>
        <div class="row" style="margin-top:8px;gap:6px;flex-wrap:wrap">
          <button class="small" id="addRule">+ Add rule</button>
          <select id="presetRule" class="small-select">
            <option value="">+ Add preset…</option>
            <option value="nocrash">No crashes (blocker)</option>
            <option value="noanr">No ANR (blocker)</option>
            <option value="fps">Avg FPS ≥ 30 (warning)</option>
            <option value="mem">Peak memory ≤ 1.5 GB (warning)</option>
            <option value="screens">Explore ≥ 5 screens (warning)</option>
          </select>
        </div>
        <div style="margin-top:10px">
          <div class="muted" style="font-size:11px;margin-bottom:4px">IGNORE PATTERNS (regex, one per line — known-benign findings)</div>
          <textarea id="ignoreText" spellcheck="false" style="min-height:54px"></textarea>
        </div>
        <div style="margin-top:8px">
          <div class="muted" style="font-size:11px;margin-bottom:4px">QA NOTES</div>
          <textarea id="notesText" spellcheck="false" style="min-height:44px;font-family:inherit"></textarea>
        </div>
      </div>
      <textarea id="planText" spellcheck="false" hidden></textarea>
      <div class="row" style="margin-top:10px">
        <button class="small" id="validateBtn">Validate</button>
        <button class="small" id="formatBtn">Format</button>
        <button class="small" id="defaultBtn">Reset</button>
      </div>
      <div class="plan-errors" id="planErrors" hidden></div>
      <details style="margin-top:10px">
        <summary>What the checks mean</summary>
        <p style="margin:8px 0 4px">Each entry in <code>checks</code> is evaluated after the session; the run gets
        one verdict: <b>fail</b> if a <code>blocker</code> fails, <b>warn</b> if only warnings fail, else <b>pass</b>.</p>
        <ul style="margin:6px 0 0;padding-left:18px">
          <li><code>no_findings</code> — zero findings of <code>kinds</code> (java_crash, native_crash, anr,
            process_death, low_memory, exception).</li>
          <li><code>max_findings</code> — at most <code>value</code> of those kinds.</li>
          <li><code>min_metric</code> / <code>max_metric</code> — compare a metric: avg_fps, min_fps,
            peak_pss_kb, anr_count, screens_explored…</li>
          <li><code>require_metric</code>, <code>require_screens</code> — presence / minimum exploration.</li>
          <li><code>ignore</code> — regexes that drop known-benign findings before checks.</li>
        </ul>
      </details>
    </section>
  </div>

  <div class="stack">
    <section class="card">
      <h2>6 · Live screen <span class="count" id="stepLabel"></span>
        <span class="tag" id="captureBadge"></span>
        <span style="margin-left:auto;display:flex;gap:5px">
          <button class="tiny" data-zoom="fit">Fit</button>
          <button class="tiny" data-zoom="1">1×</button>
          <button class="tiny" data-zoom="2">2×</button>
        </span>
      </h2>
      <div class="stage" id="stage">
        <div class="placeholder" id="livePlaceholder">upload an APK, choose a device, press <b>Test</b><br>
          <span class="muted">real frames from the phone appear here while it runs</span></div>
        <img id="liveImg" alt="live game frame" hidden>
        <div class="overlay">
          <span class="badge-rec" id="rec"><span class="dot"></span>REC</span>
          <span class="res" id="resBadge"></span>
        </div>
      </div>
      <div class="bar"><i id="progress"></i></div>
      <div class="meta">
        <span id="progressText">0 / 0 steps</span>
        <span id="actionText">—</span>
        <span id="fpsText"></span>
        <span id="elapsedText"></span>
      </div>
      <div class="film" id="film"></div>
    </section>

    <section class="card">
      <h2>7 · Run logic <span class="count" id="logicCount"></span></h2>
      <div class="log">
        <table>
          <thead><tr><th style="width:52px">Step</th><th>Action</th><th style="width:96px">Why</th>
            <th style="width:74px">Screen</th><th style="width:58px">App</th><th style="width:56px">FPS</th></tr></thead>
          <tbody id="logicBody"><tr><td colspan="6" class="empty">decisions appear here as the test runs</td></tr></tbody>
        </table>
      </div>
      <div class="muted" style="font-size:11.5px;margin-top:8px">
        <span class="tag">ui:</span> tapped a labelled control ·
        <span class="tag">explore</span> novelty-driven input ·
        <span class="tag new">new</span> unseen screen (perceptual hash) ·
        <span class="tag dead">dead</span> process gone
      </div>
    </section>

    <section class="card" id="verdictCard" hidden>
      <div class="verdict" id="verdictBox">
        <div class="big" id="verdictText">—</div>
        <div>
          <div class="sub" id="verdictSub"></div>
          <div class="kv" id="verdictKv" style="margin-top:5px"></div>
        </div>
        <div class="artifacts" id="artifacts"></div>
      </div>
    </section>

    <section class="card">
      <h2>8 · Test cases <span class="count" id="caseCount"></span>
        <span style="margin-left:auto;display:flex;gap:6px;align-items:center">
          <select id="caseFilter" class="field" style="padding:3px 6px;font-size:11px">
            <option value="all">all</option>
            <option value="P0">mandatory</option>
            <option value="todo">not decided</option>
            <option value="fail">failed / blocked</option>
          </select>
          <button class="tiny" id="regenBtn">Regenerate</button>
          <button class="tiny" id="approveBtn">Approve plan</button>
        </span>
      </h2>
      <div class="log" style="max-height:440px">
        <table>
          <thead><tr><th style="width:62px">Case</th><th style="width:66px">Req</th><th>Title</th>
            <th style="width:58px">Pri</th><th style="width:60px">Mode</th>
            <th style="width:118px">Status</th><th style="width:190px">Actual</th></tr></thead>
          <tbody id="casesBody"><tr><td colspan="7" class="empty">upload a requirements document to generate test cases</td></tr></tbody>
        </table>
      </div>
      <div class="muted" style="font-size:11.5px;margin-top:8px">
        Generated from the document only · status is per case · overall verdict follows the
        mandatory rules (PASS needs every P0 case passed).
      </div>
    </section>

    <section class="card">
      <h2>Checks <span class="count" id="checkCount"></span></h2>
      <table>
        <thead><tr><th style="width:62px">Result</th><th>Rule</th><th>Expected</th><th>Actual</th>
          <th style="width:78px">Severity</th></tr></thead>
        <tbody id="checksBody"><tr><td colspan="5" class="empty">no checks evaluated yet</td></tr></tbody>
      </table>
    </section>

    <section class="card">
      <h2>Findings <span class="count" id="findingCount"></span></h2>
      <table>
        <thead><tr><th style="width:118px">Kind</th><th style="width:56px">Step</th><th>Message</th></tr></thead>
        <tbody id="findingsBody"><tr><td colspan="3" class="empty">nothing found yet</td></tr></tbody>
      </table>
    </section>
  </div>
</main>

<div class="toast" id="toast"></div>

<script>
const $ = (id) => document.getElementById(id);
let state = null;
let lastFrame = -1;
let planDirty = false;
let polling = false;
let zoom = "fit";
let lastSteps = 0;

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 4200);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { error: text }; }
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
};

function fmtBytes(n) {
  if (!n && n !== 0) return "—";
  return n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.round(n / 1024) + " KB";
}

// ---------- APK ----------
function renderApk(apk) {
  const box = $("apkBox");
  box.innerHTML = "";
  if (!apk) {
    box.appendChild(el("div", "empty", "no APK loaded — the simulator can run without one"));
    return;
  }
  const dl = el("dl", "apk-info");
  [["package", apk.package || "unknown"], ["version", apk.version || "—"],
   ["sdk", apk.min_sdk || apk.target_sdk ? ("min " + (apk.min_sdk || "?") + " / target " + (apk.target_sdk || "?")) : "—"],
   ["launcher", apk.activity || "—"], ["abi", (apk.abis || []).join(", ") || "—"],
   ["size", fmtBytes(apk.size)], ["permissions", apk.permissions ?? "—"],
   ["sha256", apk.sha256 || "—"]].forEach(([k, v]) => {
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, v));
  });
  box.appendChild(dl);
  if (apk.error) {
    const warn = el("div", "plan-errors", apk.error);
    warn.hidden = false;
    box.appendChild(warn);
  }
}

async function upload(file) {
  if (!file) return;
  if (!/\.apk$/i.test(file.name)) { toast("please pick an .apk file"); return; }
  $("statusPill").textContent = "uploading";
  $("statusPill").className = "pill running";
  try {
    const res = await fetch("/api/upload", {
      method: "POST",
      headers: { "X-Filename": file.name, "Content-Type": "application/octet-stream" },
      body: file,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "upload failed");
    toast("APK loaded: " + (data.apk.package || data.apk.name));
    await refresh();
  } catch (err) {
    toast("upload failed: " + err.message);
    $("statusPill").textContent = "idle";
    $("statusPill").className = "pill";
  }
}

// ---------- devices ----------
let devices = [];
let selectedSerial = "";

async function pollDevices(force) {
  try {
    const d = await api("/api/device" + (force ? "?refresh=1" : ""));
    devices = d.devices || [];
    selectedSerial = d.selected || "";
    renderDevices(d);
    if (d.auto_switched) {
      toast("phone detected — switched to the connected device");
      planDirty = false;
      await refresh();
    }
  } catch (err) {
    $("devHint").textContent = "adb error: " + err.message;
  }
}

function renderDevices(info) {
  const list = $("devList");
  list.innerHTML = "";
  $("devCount").textContent = devices.length ? "(" + devices.length + ")" : "";
  $("devHint").textContent = info.hint || "";
  if (!devices.length) {
    list.appendChild(el("div", "empty", "no phone detected"));
  }
  devices.forEach((d) => {
    const label = el("label", d.serial === selectedSerial ? "sel" : "");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "dev";
    radio.checked = d.serial === selectedSerial;
    radio.onchange = () => selectDevice(d.serial);
    label.appendChild(radio);
    label.appendChild(el("span", null, d.model || d.serial));
    const stateTag = el("span", "m", d.state);
    label.appendChild(stateTag);
    list.appendChild(label);
  });
  const online = devices.some((d) => d.state === "device");
  const readiness = (state && state.readiness) || null;
  if (readiness) {
    const box = $("readyList");
    box.innerHTML = "";
    (readiness.checks || []).forEach((c) => {
      const row = el("div", "r " + (c.ok ? "ok" : "bad"), (c.ok ? "✓ " : "✗ ") + c.label);
      row.title = c.hint || "";
      box.appendChild(row);
    });
    const banner = $("readyBanner");
    if (!readiness.ready) {
      banner.hidden = false;
      banner.textContent = readiness.hint || "device is not ready";
    } else {
      banner.hidden = true;
      banner.textContent = "";
    }
  }
  const chip = $("deviceChip");
  chip.textContent = online
    ? (devices.find((d) => d.state === "device").model || selectedSerial) + " · " + selectedSerial
    : (devices.length ? "device offline" : "no device · simulator only");
  if (!online && $("optTarget").value === "device" && !state?.apk) {
    // keep the choice, validation happens on Test
  }
}

async function selectDevice(serial) {
  try {
    await api("/api/device/select", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ serial }) });
    selectedSerial = serial;
    const plan = JSON.parse($("planText").value || "{}");
    plan.target = "device";
    $("planText").value = JSON.stringify(plan, null, 2);
    planDirty = true;
    $("optTarget").value = "device";
    await validatePlan(true);
    toast("device selected: " + serial);
    await pollDevices();
  } catch (err) { toast(err.message); }
}

// ---------- plan ----------
function syncPlanEditor(plan) {
  if (planDirty) return;
  $("planText").value = JSON.stringify(plan, null, 2);
  syncOptions(plan);
  if (typeof renderRules === "function") renderRules();
}

function syncOptions(plan) {
  $("optTarget").value = plan.target || "simulator";
  $("optPolicy").value = plan.policy || "heuristic";
  $("optSteps").value = plan.steps || 160;
  $("optMinutes").value = plan.minutes || 20;
  $("optSeed").value = plan.seed ?? 7;
  $("optFps").value = plan.video_fps || 6;
  $("optCapture").value = plan.capture || "frames";
  $("optRecord").checked = plan.record_video !== false;
  $("optInstall").checked = plan.install !== false;
}

async function validatePlan(quiet) {
  const text = $("planText").value;
  try { JSON.parse(text); } catch (err) {
    showPlanErrors(["invalid JSON: " + err.message]);
    if (!quiet) toast("invalid JSON");
    return false;
  }
  try {
    await api("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: text });
    showPlanErrors([]);
    planDirty = false;
    if (!quiet) toast("plan valid");
    return true;
  } catch (err) {
    showPlanErrors(String(err.message).split("; "));
    if (!quiet) toast("plan has errors");
    return false;
  }
}

function showPlanErrors(errors) {
  const box = $("planErrors");
  if (!errors || !errors.length) { box.hidden = true; box.textContent = ""; return; }
  box.hidden = false;
  box.textContent = errors.join("\n");
}

function applyOptions() {
  let plan;
  try { plan = JSON.parse($("planText").value); } catch (err) { toast("plan JSON is invalid"); return; }
  plan.target = $("optTarget").value;
  plan.policy = $("optPolicy").value;
  plan.steps = Number($("optSteps").value);
  plan.minutes = Number($("optMinutes").value);
  plan.seed = Number($("optSeed").value);
  plan.video_fps = Number($("optFps").value);
  plan.capture = $("optCapture").value;
  plan.record_video = $("optRecord").checked;
  plan.install = $("optInstall").checked;
  $("planText").value = JSON.stringify(plan, null, 2);
  planDirty = true;
  validatePlan(false).then((ok) => { if (ok) toast("options applied"); });
}

// ---------- live ----------
function applyZoom() {
  const img = $("liveImg");
  if (!img.naturalWidth) return;
  if (zoom === "fit") { img.style.width = "100%"; }
  else { img.style.width = (img.naturalWidth * Number(zoom)) + "px"; }
  img.classList.toggle("pixel", img.naturalWidth < 400);
}

function renderLive(s) {
  const frames = s.frames || {};
  if (frames.latest >= 0 && frames.latest !== lastFrame) {
    lastFrame = frames.latest;
    const img = $("liveImg");
    img.onload = () => { applyZoom(); $("resBadge").textContent = img.naturalWidth + "×" + img.naturalHeight; };
    img.src = "/api/frame?i=latest&t=" + Date.now();
    img.hidden = false;
    $("livePlaceholder").hidden = true;
  }
  const total = (s.progress && s.progress.total) || (s.plan && s.plan.steps) || 0;
  const step = (s.progress && s.progress.step) || 0;
  $("progress").style.width = total ? Math.min(100, (step / total) * 100) + "%" : "0%";
  $("stepLabel").textContent = total ? step + " / " + total : "";
  $("progressText").textContent = step + " / " + total + " steps";
  $("actionText").textContent = (s.progress && s.progress.action) || "—";
  $("elapsedText").textContent = s.progress && s.progress.elapsed ? s.progress.elapsed + "s" : "";
  $("fpsText").textContent = s.summary && s.summary.avg_fps ? "avg " + s.summary.avg_fps + " fps" : "";
  $("rec").classList.toggle("on", s.status === "running");

  const film = $("film");
  film.innerHTML = "";
  (frames.recent || []).forEach((f) => {
    const img = document.createElement("img");
    img.src = "/api/frame?i=" + f.index;
    img.title = "step " + f.step + " · " + f.action;
    if (f.finding) img.className = "finding";
    img.onclick = () => {
      const live = $("liveImg");
      live.src = "/api/frame?i=" + f.index + "&t=" + Date.now();
      live.hidden = false;
    };
    film.appendChild(img);
  });
}

// ---------- run logic ----------
function renderLogic(s) {
  const steps = s.steps || [];
  const body = $("logicBody");
  $("logicCount").textContent = s.steps_total ? "(" + s.steps_total + ")" : "";
  if (!steps.length) return;
  if (steps.length === lastSteps && body.childElementCount === steps.length) return;
  lastSteps = steps.length;
  body.innerHTML = "";
  steps.slice().reverse().forEach((st) => {
    const tr = el("tr", st.crashes && st.crashes.length ? "finding" : "");
    tr.appendChild(el("td", "mono", st.step));
    const action = el("td", "mono", st.action);
    if (st.note) action.title = st.note;
    tr.appendChild(action);
    const why = el("td");
    const note = (st.note || "").split(":")[0];
    const tag = el("span", "tag", note || st.kind || "");
    why.appendChild(tag);
    tr.appendChild(why);
    const scr = el("td");
    if (st.new_screen) scr.appendChild(el("span", "tag new", "new"));
    else scr.appendChild(el("span", "mono muted", (st.screen || "").slice(0, 6)));
    tr.appendChild(scr);
    const app = el("td");
    app.appendChild(el("span", "tag " + (st.alive ? "" : "dead"), st.alive ? "up" : "dead"));
    tr.appendChild(app);
    tr.appendChild(el("td", "mono", st.fps === null || st.fps === undefined ? "" : Math.round(st.fps)));
    body.appendChild(tr);
  });
}

// ---------- requirements / cases ----------
async function uploadDoc(file) {
  if (!file) return;
  if (!/\.(md|markdown|txt|docx|pdf)$/i.test(file.name)) { toast("use .md, .txt, .docx or .pdf"); return; }
  try {
    const res = await fetch("/api/requirements", {
      method: "POST",
      headers: { "X-Filename": file.name, "Content-Type": "application/octet-stream" },
      body: file,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "upload failed");
    toast("requirements parsed: " + (data.suite ? data.suite.coverage.total + " test cases" : ""));
    await refresh();
  } catch (err) { toast("document rejected: " + err.message); }
}

function renderRequirements(s) {
  const req = s.requirements;
  const box = $("reqBox");
  box.innerHTML = "";
  $("reqCount").textContent = req ? "(" + req.counts.total + ")" : "";
  if (!req) {
    box.appendChild(el("div", "empty", "no document yet — the suite is generated from it"));
    return;
  }
  const dl = el("dl", "apk-info");
  const counts = req.counts || {};
  [["document", req.name],
   ["requirements", counts.total || 0],
   ["ready", (counts.statuses && counts.statuses.READY) || 0],
   ["needs clarification", (counts.statuses && counts.statuses.NEEDS_CLARIFICATION) || 0],
   ["not testable", (counts.statuses && counts.statuses.NOT_TESTABLE) || 0]].forEach(([k, v]) => {
    dl.appendChild(el("dt", null, k));
    dl.appendChild(el("dd", null, String(v)));
  });
  box.appendChild(dl);
  const suite = s.suite;
  if (suite) {
    const line = el("div", "row", "");
    line.style.marginTop = "8px";
    const badge = el("span", "badge " + (suite.approved ? "pass" : "warn"),
                     suite.approved ? "plan approved" : "plan not approved");
    line.appendChild(badge);
    line.appendChild(el("span", "muted", "verdict " + suite.verdict +
      " · " + suite.coverage.decided + "/" + suite.coverage.total + " decided"));
    box.appendChild(line);
  }
  if (req.warnings && req.warnings.length) {
    const warn = el("div", "plan-errors", req.warnings.join("\n"));
    warn.hidden = false;
    box.appendChild(warn);
  }
}

function renderCases(s) {
  const cases = s.testcases || [];
  const body = $("casesBody");
  $("caseCount").textContent = cases.length ? "(" + cases.length + ")" : "";
  const filter = $("caseFilter").value;
  const filtered = cases.filter((c) => {
    if (filter === "P0") return c.priority === "P0";
    if (filter === "todo") return c.status === "NOT_RUN" || c.status === "NOT_VERIFIED";
    if (filter === "fail") return c.status === "FAIL" || c.status === "BLOCKED";
    return true;
  });
  body.innerHTML = "";
  if (!filtered.length) {
    const tr = el("tr"); const td = el("td", "empty",
      cases.length ? "no cases match this filter" : "upload a requirements document to generate test cases");
    td.colSpan = 7; tr.appendChild(td); body.appendChild(tr);
    return;
  }
  filtered.forEach((c) => {
    const tr = el("tr", c.status === "FAIL" ? "finding" : "");
    tr.appendChild(el("td", "mono", c.id));
    tr.appendChild(el("td", "mono muted", c.requirement_id));
    const title = el("td", null, c.title);
    title.title = (c.steps || []).map((step, i) => (i + 1) + ". " + step).join("\n") +
      "\n\nExpected: " + c.expected;
    tr.appendChild(title);
    tr.appendChild(el("td", "mono", c.priority));
    tr.appendChild(el("td", "mono muted", c.mode));
    const statusTd = el("td");
    const select = document.createElement("select");
    select.className = "field";
    select.style.padding = "2px 4px";
    select.style.fontSize = "11px";
    ["NOT_RUN", "PASS", "FAIL", "BLOCKED", "NOT_VERIFIED", "SKIPPED"].forEach((status) => {
      const option = document.createElement("option");
      option.value = status;
      option.textContent = status;
      option.selected = status === c.status;
      select.appendChild(option);
    });
    select.onchange = () => setCase(c.id, { status: select.value });
    statusTd.appendChild(select);
    tr.appendChild(statusTd);
    const actualTd = el("td");
    const input = document.createElement("input");
    input.type = "text";
    input.value = c.actual || "";
    input.placeholder = "observed result";
    input.style.width = "100%";
    input.style.background = "#0b1118";
    input.style.border = "1px solid var(--line)";
    input.style.borderRadius = "6px";
    input.style.color = "var(--text)";
    input.style.fontSize = "11px";
    input.style.padding = "3px 6px";
    input.onchange = () => setCase(c.id, { actual: input.value });
    actualTd.appendChild(input);
    tr.appendChild(actualTd);
    body.appendChild(tr);
  });
}

async function setCase(id, fields) {
  try {
    await api("/api/testcases/update", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, ...fields }) });
    await refresh();
  } catch (err) { toast(err.message); }
}

async function approvePlan() {
  try {
    await api("/api/requirements/approve", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved: true }) });
    toast("test plan approved");
    await refresh();
  } catch (err) { toast(err.message); }
}

async function regenerateCases() {
  try {
    await api("/api/requirements/regenerate", { method: "POST" });
    toast("cases regenerated (results kept)");
    await refresh();
  } catch (err) { toast(err.message); }
}

// ---------- results ----------
function renderChecks(checks) {
  const body = $("checksBody");
  body.innerHTML = "";
  $("checkCount").textContent = checks.length ? "(" + checks.length + ")" : "";
  if (!checks.length) {
    const tr = el("tr"); const td = el("td", "empty", "no checks evaluated yet"); td.colSpan = 5;
    tr.appendChild(td); body.appendChild(tr); return;
  }
  checks.forEach((c) => {
    const tr = el("tr");
    const td = el("td");
    td.appendChild(el("span", "badge " + (c.passed ? "pass" : (c.severity === "blocker" ? "fail" : "warn")),
      c.passed ? "pass" : "fail"));
    tr.appendChild(td);
    tr.appendChild(el("td", null, c.title || c.id));
    tr.appendChild(el("td", "mono", c.expected || ""));
    tr.appendChild(el("td", "mono", c.actual || ""));
    tr.appendChild(el("td", "mono muted", c.severity));
    if (c.detail) tr.title = c.detail;
    body.appendChild(tr);
  });
}

function renderFindings(findings) {
  const body = $("findingsBody");
  body.innerHTML = "";
  $("findingCount").textContent = findings.length ? "(" + findings.length + ")" : "";
  if (!findings.length) {
    const tr = el("tr"); const td = el("td", "empty", "nothing found yet"); td.colSpan = 3;
    tr.appendChild(td); body.appendChild(tr); return;
  }
  findings.forEach((f) => {
    const tr = el("tr");
    const kindTd = el("td");
    kindTd.appendChild(el("span", "kind " + (f.kind || ""), (f.kind || "?").replace(/_/g, " ")));
    tr.appendChild(kindTd);
    tr.appendChild(el("td", "mono", f.step));
    const msg = el("td");
    msg.appendChild(el("div", null, f.message || ""));
    msg.appendChild(el("div", "mono muted", (f.signature || "").slice(0, 150)));
    tr.appendChild(msg);
    if (f.stack && f.stack.length) tr.title = f.stack.slice(0, 6).join("\n");
    body.appendChild(tr);
  });
}

function renderVerdict(s) {
  const card = $("verdictCard");
  const checks = s.checks || [];
  if (!checks.length) { card.hidden = true; return; }
  card.hidden = false;
  const summary = s.summary || {};
  const partial = summary.verdict === "incomplete";
  const v = (summary.check_summary && summary.check_summary.verdict) || summary.verdict || "pass";
  $("verdictBox").className = "verdict " + (partial ? "warn" : v);
  $("verdictText").textContent = partial ? "RESULTS SO FAR" : v.toUpperCase();
  const cs = summary.check_summary || {};
  $("verdictSub").textContent = (cs.passed || 0) + " of " + (cs.total || 0) + " checks passed · " +
    (s.findings || []).length + " findings · " + (summary.steps_run || 0) + " steps · " +
    (summary.duration_s || 0) + "s";
  const kv = $("verdictKv");
  kv.innerHTML = "";
  [["fps", summary.avg_fps], ["min fps", summary.min_fps], ["jank", summary.avg_jank_percent],
   ["peak mem", summary.peak_pss_kb ? Math.round(summary.peak_pss_kb / 1024) + " MB" : null],
   ["screens", summary.screens_explored]].forEach(([k, val]) => {
    if (val === null || val === undefined) return;
    const span = el("span");
    span.appendChild(el("b", null, String(val)));
    span.appendChild(document.createTextNode(" " + k));
    kv.appendChild(span);
  });

  const box = $("artifacts");
  box.innerHTML = "";
  const artifacts = s.artifacts || {};
  const labels = { video: "video", gif: "gif", report: "report.html", junit: "junit.xml",
                   session: "session.json", checks: "checks.json", logcat: "logcat.txt" };
  Object.keys(labels).forEach((key) => {
    const name = artifacts[key];
    if (!name) return;
    const a = document.createElement("a");
    a.href = "/api/artifact?name=" + encodeURIComponent(name) + (key === "report" ? "" : "&download=1");
    a.target = "_blank";
    a.textContent = labels[key];
    box.appendChild(a);
  });
  if (s.video && s.video.error && !s.video.path) {
    box.appendChild(el("div", "muted", "video: " + s.video.error));
  }
}

function renderStatus(s) {
  const pill = $("statusPill");
  pill.textContent = s.status;
  pill.className = "pill " + s.status;
  $("runBtn").disabled = s.status === "running";
  $("stopBtn").disabled = s.status !== "running";
  if (s.error) toast(s.error);
}

function render(s) {
  state = s;
  renderStatus(s);
  renderPipeline(s);
  const cap = (s.plan && s.plan.capture) || "frames";
  $("captureBadge").textContent = cap === "screenrecord" ? "device video" :
    (cap === "both" ? "video + frames" : "frames only");
  renderApk(s.apk);
  renderLive(s);
  renderLogic(s);
  renderRequirements(s);
  renderCases(s);
  renderChecks(s.checks || []);
  renderFindings(s.findings || []);
  renderVerdict(s);
  if (s.plan) syncPlanEditor(s.plan);
}

async function refresh() {
  if (polling) return;
  polling = true;
  try { render(await api("/api/state")); } catch (err) { console.warn(err); }
  finally { polling = false; }
}

async function pollLoop() {
  await refresh();
  setTimeout(pollLoop, (state && state.poll_hint_ms) || 700);
}

// ---------- actions ----------
$("runBtn").onclick = async () => {
  const ok = await validatePlan(true);
  if (!ok) { toast("fix the plan before running"); return; }
  const target = $("optTarget").value;
  if (target === "device" && !devices.some((d) => d.state === "device")) {
    toast("no phone connected — enable USB debugging or switch Run on: Simulator");
    return;
  }
  try {
    await api("/api/run", { method: "POST" });
    $("verdictCard").hidden = true;
    $("liveImg").hidden = true;
    $("livePlaceholder").hidden = false;
    lastFrame = -1; lastSteps = 0;
    toast("test started");
    await refresh();
  } catch (err) { toast("cannot start: " + err.message); }
};

$("stopBtn").onclick = async () => {
  try { await api("/api/stop", { method: "POST" }); toast("stopping after the current step…"); }
  catch (err) { toast(err.message); }
};

$("restartBtn").onclick = async () => {
  try {
    await api("/api/restart", { method: "POST" });
    lastFrame = -1; lastSteps = 0;
    $("liveImg").hidden = true;
    $("livePlaceholder").hidden = false;
    $("verdictCard").hidden = true;
    $("film").innerHTML = "";
    toast("session cleared — press Start test");
    await refresh();
  } catch (err) { toast(err.message); }
};

async function setTarget(value) {
  try {
    const data = await api("/api/target", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target: value }) });
    planDirty = false;
    $("planText").value = JSON.stringify(data.plan, null, 2);
    syncOptions(data.plan);
    toast(value === "device" ? "target: connected phone" : "target: simulator");
    await refresh();
  } catch (err) { toast(err.message); }
}

function renderPipeline(s) {
  const stages = ["apk", "install", "launch", "explore", "report"];
  const phase = (s.progress && s.progress.phase) || "";
  const running = s.status === "running";
  const done = s.status === "done";
  const failed = s.status === "error";
  let current = "apk";
  if (s.apk) current = "install";
  if (running) current = phase === "launching" ? "launch" : (phase === "running" ? "explore" : "install");
  if (done) current = "report";
  if (failed) current = phase || "explore";
  const order = stages.indexOf(current);
  document.querySelectorAll("#pipe .step").forEach((node) => {
    const index = stages.indexOf(node.dataset.stage);
    node.classList.toggle("active", node.dataset.stage === current && (running || failed));
    node.classList.toggle("ok", index < order && !failed);
    node.classList.toggle("err", failed && node.dataset.stage === current);
  });
  $("pipeApk").textContent = s.apk ? (s.apk.package || "").split(".").slice(-2).join(".") : "—";
  const note = $("pipeNote");
  if (failed) note.textContent = s.error || "failed";
  else if (running) note.textContent = (s.progress && s.progress.action) || "running";
  else if (done) note.textContent = "session complete — " + ((s.summary && s.summary.steps_run) || 0) + " steps";
  else note.textContent = "upload an APK and press Start test";
}

$("applyOpts").onclick = applyOptions;
$("validateBtn").onclick = () => validatePlan(false);
$("defaultBtn").onclick = async () => {
  try {
    const data = await api("/api/plan/default", { method: "POST" });
    planDirty = false;
    $("planText").value = JSON.stringify(data.plan, null, 2);
    syncOptions(data.plan);
    showPlanErrors([]);
    toast("default plan restored");
  } catch (err) { toast(err.message); }
};
$("formatBtn").onclick = () => {
  try { $("planText").value = JSON.stringify(JSON.parse($("planText").value), null, 2); planDirty = true; }
  catch (err) { toast("invalid JSON: " + err.message); }
};
$("planText").addEventListener("input", () => { planDirty = true; renderRules(); });

// ---------- visual rule builder ----------
let schema = null, ruleTimer = null;
const NEEDS_VALUE = ["max_findings", "min_metric", "max_metric", "require_screens"];
const NEEDS_METRIC = ["min_metric", "max_metric", "require_metric"];
const NEEDS_KINDS = ["no_findings", "max_findings"];
const RULE_LABEL = {no_findings: "No findings of", max_findings: "At most N findings of", min_metric: "Metric ≥",
  max_metric: "Metric ≤", require_metric: "Metric is measured", require_screens: "Screens explored ≥"};
const PRESETS = {
  nocrash: {id: "no-crash", type: "no_findings", kinds: ["java_crash", "native_crash"], severity: "blocker"},
  noanr: {id: "no-anr", type: "no_findings", kinds: ["anr"], severity: "blocker"},
  fps: {id: "fps", type: "min_metric", metric: "avg_fps", value: 30, severity: "warning"},
  mem: {id: "memory", type: "max_metric", metric: "peak_pss_kb", value: 1500000, severity: "warning"},
  screens: {id: "coverage", type: "require_screens", value: 5, severity: "warning"},
};
function readPlan() { try { return JSON.parse($("planText").value || "{}"); } catch (e) { return null; } }
function writePlan(plan) {
  $("planText").value = JSON.stringify(plan, null, 2);
  planDirty = true;
  clearTimeout(ruleTimer);
  ruleTimer = setTimeout(() => validatePlan(true), 400);
}
function escA(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function renderRules() {
  if (!schema) return;
  const plan = readPlan();
  const body = $("rulesBody");
  if (!plan) { body.innerHTML = '<tr><td colspan="6" class="empty">plan JSON is invalid — fix it in JSON mode</td></tr>'; return; }
  if (document.activeElement && body.contains(document.activeElement)) return; // don't clobber while typing
  const checks = plan.checks || [];
  body.innerHTML = checks.map((c, i) => {
    const typeSel = Object.keys(schema.check_types).map((t) =>
      `<option value="${t}" ${t === c.type ? "selected" : ""} title="${escA(schema.check_types[t])}">${RULE_LABEL[t] || t}</option>`).join("");
    let middle = "";
    if (NEEDS_KINDS.includes(c.type)) {
      middle = '<div class="kinds">' + schema.kinds.map((k) =>
        `<label><input type="checkbox" data-i="${i}" data-kind="${k}" ${(c.kinds || []).includes(k) ? "checked" : ""}>${k}</label>`).join("") +
        '</div>';
    } else if (NEEDS_METRIC.includes(c.type)) {
      middle = `<select data-i="${i}" data-f="metric">` + Object.entries(schema.metrics).map(([m, d]) =>
        `<option value="${m}" ${m === c.metric ? "selected" : ""}>${escA(d.label)}${d.unit ? " (" + d.unit + ")" : ""}</option>`).join("") + "</select>";
    } else { middle = '<span class="muted">—</span>'; }
    const val = NEEDS_VALUE.includes(c.type) ? `<input class="val" type="number" data-i="${i}" data-f="value" value="${escA(c.value ?? 0)}">` : '<span class="muted">—</span>';
    const sev = `<select data-i="${i}" data-f="severity" class="sev-${c.severity || "blocker"}">` + schema.severities.map((s) =>
      `<option ${s === (c.severity || "blocker") ? "selected" : ""}>${s}</option>`).join("") + "</select>";
    return `<tr><td><input class="id" data-i="${i}" data-f="id" value="${escA(c.id)}"></td>
      <td><select data-i="${i}" data-f="type">${typeSel}</select></td><td>${middle}</td><td>${val}</td><td>${sev}</td>
      <td style="white-space:nowrap"><button class="tiny" data-up="${i}" title="move up">↑</button>
      <button class="tiny danger" data-del="${i}" title="delete">✕</button></td></tr>`;
  }).join("") || '<tr><td colspan="6" class="empty">no rules — every run will pass. Add one below.</td></tr>';
  if (document.activeElement !== $("ignoreText")) $("ignoreText").value = (plan.ignore || []).join("\n");
  if (document.activeElement !== $("notesText")) $("notesText").value = plan.notes || "";
}
function editRule(i, mutate) {
  const plan = readPlan(); if (!plan) return;
  plan.checks = plan.checks || [];
  mutate(plan.checks, i);
  writePlan(plan);
}
$("rulesBody").addEventListener("change", (ev) => {
  const el = ev.target, i = Number(el.dataset.i);
  if (Number.isNaN(i)) return;
  editRule(i, (checks) => {
    const c = checks[i];
    if (el.dataset.kind) {
      const set = new Set(c.kinds || []);
      el.checked ? set.add(el.dataset.kind) : set.delete(el.dataset.kind);
      c.kinds = schema.kinds.filter((k) => set.has(k));
      if (!c.kinds.length) delete c.kinds;
    } else if (el.dataset.f === "value") { c.value = Number(el.value); }
    else if (el.dataset.f === "type") {
      c.type = el.value;
      if (!NEEDS_METRIC.includes(c.type)) delete c.metric; else c.metric = c.metric || "avg_fps";
      if (!NEEDS_KINDS.includes(c.type)) delete c.kinds;
      if (!NEEDS_VALUE.includes(c.type)) delete c.value; else c.value = c.value ?? 0;
    } else { c[el.dataset.f] = el.value; }
  });
  el.blur(); renderRules();
});
$("rulesBody").addEventListener("click", (ev) => {
  const el = ev.target;
  if (el.dataset.del !== undefined) editRule(Number(el.dataset.del), (checks, i) => checks.splice(i, 1));
  else if (el.dataset.up !== undefined) editRule(Number(el.dataset.up), (checks, i) => {
    if (i > 0) [checks[i - 1], checks[i]] = [checks[i], checks[i - 1]];
  });
  else return;
  renderRules();
});
function uniqueId(checks, base) { let id = base, n = 2; while (checks.some((c) => c.id === id)) id = base + "-" + n++; return id; }
$("addRule").onclick = () => { editRule(0, (checks) => checks.push({id: uniqueId(checks, "rule"), type: "no_findings", severity: "blocker"})); renderRules(); };
$("presetRule").onchange = (ev) => {
  const p = PRESETS[ev.target.value]; ev.target.value = ""; if (!p) return;
  editRule(0, (checks) => checks.push({...p, id: uniqueId(checks, p.id)})); renderRules();
};
$("ignoreText").addEventListener("input", () => {
  const plan = readPlan(); if (!plan) return;
  plan.ignore = $("ignoreText").value.split("\n").map((s) => s.trim()).filter(Boolean); writePlan(plan);
});
$("notesText").addEventListener("input", () => {
  const plan = readPlan(); if (!plan) return; plan.notes = $("notesText").value; writePlan(plan);
});
function setMode(visual) {
  $("ruleBuilder").hidden = !visual; $("planText").hidden = visual;
  $("modeVisual").classList.toggle("on", visual); $("modeJson").classList.toggle("on", !visual);
  if (visual) renderRules();
}
$("modeVisual").onclick = () => setMode(true);
$("modeJson").onclick = () => setMode(false);
fetch("/api/schema").then((r) => r.json()).then((s) => { schema = s; renderRules(); }).catch(() => setMode(false));
$("refreshDev").onclick = () => pollDevices(true);

document.querySelectorAll("[data-zoom]").forEach((btn) => {
  btn.onclick = () => {
    zoom = btn.dataset.zoom;
    document.querySelectorAll("[data-zoom]").forEach((b) => b.classList.toggle("on", b === btn));
    applyZoom();
  };
});

const drop = $("drop");
drop.onclick = () => $("file").click();
$("file").onchange = (e) => upload(e.target.files[0]);
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
  e.preventDefault(); drop.classList.add("over");
}));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
  e.preventDefault(); drop.classList.remove("over");
}));
drop.addEventListener("drop", (e) => upload(e.dataTransfer.files && e.dataTransfer.files[0]));

$("docDrop").onclick = () => $("docFile").click();
$("docFile").onchange = (e) => uploadDoc(e.target.files[0]);
["dragenter", "dragover"].forEach((ev) => $("docDrop").addEventListener(ev, (e) => {
  e.preventDefault(); $("docDrop").classList.add("over");
}));
["dragleave", "drop"].forEach((ev) => $("docDrop").addEventListener(ev, (e) => {
  e.preventDefault(); $("docDrop").classList.remove("over");
}));
$("docDrop").addEventListener("drop", (e) => uploadDoc(e.dataTransfer.files && e.dataTransfer.files[0]));
$("caseFilter").onchange = () => renderCases(state || {});
$("approveBtn").onclick = approvePlan;
$("regenBtn").onclick = regenerateCases;

pollLoop();
pollDevices();
setInterval(() => pollDevices(), 4000);
setInterval(() => { if (document.querySelector("[data-zoom].on") === null) return; }, 60000);
</script>
</body>
</html>
"""
