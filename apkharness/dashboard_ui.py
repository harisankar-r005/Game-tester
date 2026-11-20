"""The simple, guided QA page (served at ``/`` and ``/dashboard``).

Written for someone who has never used a test tool: three numbered steps, one big
button, results in plain words, technical detail folded away. Plain HTML/JS, no CDN,
works offline.
"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Game Tester</title>
<style>
:root{
  --bg:#f4f6fa; --card:#ffffff; --soft:#f0f3f8; --line:#dfe4ec; --text:#18202b; --muted:#5d6b7e;
  --blue:#2563eb; --blue-soft:#e8f0ff; --green:#15803d; --green-soft:#e5f6ea; --red:#c62828; --red-soft:#fdeaea;
  --amber:#a15c00; --amber-soft:#fff3dc; --shadow:0 1px 2px rgba(16,24,40,.06),0 2px 8px rgba(16,24,40,.05);
  --mono:ui-monospace,SFMono-Regular,Consolas,monospace;
}
@media (prefers-color-scheme: dark){:root{
  --bg:#0e131a; --card:#161d27; --soft:#1c2430; --line:#2a3443; --text:#e8edf3; --muted:#9aa8b9;
  --blue:#5b9bff; --blue-soft:#17263d; --green:#4ccb72; --green-soft:#15291c; --red:#ff6b6b; --red-soft:#33191b;
  --amber:#f2b34b; --amber-soft:#30250f; --shadow:none;}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 "Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--blue)}
button{font:inherit;cursor:pointer;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--text);
  padding:9px 16px;font-weight:600}
button:hover:not(:disabled){border-color:var(--blue)}
button:disabled{opacity:.5;cursor:not-allowed}
.top{background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10;box-shadow:var(--shadow)}
.top-in{max-width:1100px;margin:0 auto;padding:10px 18px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px;text-decoration:none;color:inherit}
.logo{width:42px;height:42px;border-radius:12px;background:linear-gradient(135deg,#3b82f6,#7c3aed);color:#fff;display:grid;place-items:center;font-size:22px;box-shadow:0 2px 8px rgba(59,130,246,.35)}
.title b{display:block;font-size:18px;line-height:1.2} .title span{font-size:12.5px;color:var(--muted)}
.nav{display:flex;gap:4px;background:var(--soft);padding:4px;border-radius:12px}
.navbtn{display:flex;align-items:center;gap:6px;padding:7px 14px;border-radius:9px;font-size:14.5px;font-weight:600;color:var(--muted);text-decoration:none}
.navbtn:hover{color:var(--text)}
.navbtn.on{background:var(--card);color:var(--text);box-shadow:var(--shadow)}
.spacer{flex:1}
.status{display:inline-flex;align-items:center;gap:8px;font-size:14px;padding:7px 14px;border-radius:999px;background:var(--soft);color:var(--muted)}
.status .dot{width:9px;height:9px;border-radius:50%;background:currentColor;font-style:normal}
.status.running{background:var(--blue-soft);color:var(--blue)} .status.running .dot{animation:pulse 1.2s infinite}
.status.done{background:var(--green-soft);color:var(--green)} .status.error{background:var(--red-soft);color:var(--red)}
@keyframes pulse{50%{opacity:.25}}
.helpbtn{background:var(--blue);border-color:var(--blue);color:#fff;padding:8px 16px;border-radius:999px;font-size:14.5px}
.helpbtn:hover:not(:disabled){filter:brightness(1.1);border-color:var(--blue)}
@media (max-width:1000px){.title span{display:none}.top-in{gap:12px}}
@media (max-width:700px){.navbtn span,.status b{display:none}.status{padding:9px}}

/* guide */
.help-back{position:fixed;inset:0;background:rgba(10,15,25,.45);z-index:40}
.guide{position:fixed;top:0;right:0;bottom:0;width:min(620px,100vw);background:var(--card);z-index:41;display:flex;flex-direction:column;
  box-shadow:-8px 0 30px rgba(0,0,0,.25);border-left:1px solid var(--line)}
.help-head{display:flex;align-items:flex-start;justify-content:space-between;padding:18px 20px 6px}
.help-kicker{font-size:12px;font-weight:700;color:var(--blue);text-transform:uppercase;letter-spacing:.08em}
.guide h2{margin:2px 0 0;font-size:22px}
.help-x{border:0;background:var(--soft);width:36px;height:36px;padding:0;border-radius:50%;font-size:16px}
.help-tabs{display:flex;gap:6px;flex-wrap:wrap;padding:10px 20px;border-bottom:1px solid var(--line)}
.help-tabs button{font-size:13.5px;padding:6px 11px;border-radius:999px;background:var(--soft);border-color:transparent;color:var(--muted)}
.help-tabs button.on{background:var(--blue);color:#fff}
.help-body{flex:1;overflow:auto;padding:16px 20px}
.help-body section{display:none} .help-body section.on{display:block}
.guide .hl{background:var(--blue-soft);border-radius:12px;padding:12px 14px;margin:0 0 14px}
.big-steps{counter-reset:s;list-style:none;padding:0;margin:0}
.big-steps li{counter-increment:s;position:relative;padding:4px 0 14px 46px}
.big-steps li::before{content:counter(s);position:absolute;left:0;top:2px;width:32px;height:32px;border-radius:50%;background:var(--blue);color:#fff;
  display:grid;place-items:center;font-weight:800}
.big-steps small{color:var(--muted)}
.tip{background:var(--amber-soft);border-radius:12px;padding:11px 14px;font-size:14.5px}
.mdex{background:var(--soft);border-radius:10px;padding:10px 12px;font:12.5px/1.5 var(--mono);white-space:pre-wrap;margin:0 0 10px}
.parts{margin:0} .parts dt{font-weight:700;margin-top:14px} .parts dt span{font-weight:400;color:var(--muted);font-size:13.5px}
.parts dd{margin:3px 0 0;color:var(--text);font-size:14.5px}
.guide code{background:var(--soft);padding:1px 6px;border-radius:6px;font-size:13px}
.help-foot{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 20px;border-top:1px solid var(--line);font-size:14px;color:var(--muted);flex-wrap:wrap}
.help-foot label{display:flex;gap:8px;align-items:center}
.help-done{background:var(--blue);border-color:var(--blue);color:#fff}
.wrap{max-width:1100px;margin:0 auto;padding:20px 18px 60px}
h1{font-size:24px;margin:4px 0 4px} .lead{color:var(--muted);margin:0 0 18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:var(--shadow);margin-bottom:18px}
.card h2{font-size:18px;margin:0 0 4px} .card .sub{color:var(--muted);font-size:14px;margin:0 0 14px}

/* the three steps */
.steps{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:18px}
@media (max-width:860px){.steps{grid-template-columns:1fr}}
.step{background:var(--card);border:2px solid var(--line);border-radius:16px;padding:16px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:8px}
.step.ok{border-color:var(--green)} .step.todo{border-color:var(--amber)}
.step .num{display:flex;align-items:center;gap:10px;font-weight:700;font-size:16px}
.step .num i{font-style:normal;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;background:var(--soft);font-size:15px}
.step.ok .num i{background:var(--green);color:#fff} .step.todo .num i{background:var(--amber);color:#fff}
.step .state{font-size:15px} .step .hint{font-size:13.5px;color:var(--muted)}
.step .big{font-weight:700}
.drop{border:2px dashed var(--line);border-radius:12px;padding:12px;text-align:center;cursor:pointer;color:var(--muted);font-size:14px}
.drop:hover,.drop.over{border-color:var(--blue);color:var(--blue);background:var(--blue-soft)}
.tag{display:inline-block;font-size:12.5px;font-weight:700;padding:2px 9px;border-radius:999px;background:var(--soft);color:var(--muted)}
.tag.game{background:var(--amber-soft);color:var(--amber)} .tag.app{background:var(--blue-soft);color:var(--blue)}
details.help{font-size:13.5px;color:var(--muted)} details.help summary{cursor:pointer;color:var(--blue);font-weight:600}
details.help ol{margin:6px 0 0;padding-left:20px}

/* start bar */
.go{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.btn-go{font-size:20px;padding:14px 34px;border-radius:14px;background:var(--green);border-color:var(--green);color:#fff}
.btn-go:hover:not(:disabled){filter:brightness(1.08);border-color:var(--green)}
.btn-stop{font-size:16px;padding:12px 22px;background:var(--red-soft);color:var(--red);border-color:transparent}
.history-tools{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap}
.history-delete{color:var(--red);background:var(--red-soft);padding:6px 12px}
.history-select{width:2.5rem;text-align:center}
.go .why{color:var(--muted);font-size:14.5px;flex:1;min-width:220px}
.test-length{display:flex;align-items:center;gap:8px 12px;flex-wrap:wrap;margin:-4px 0 16px;font-size:14px}
.test-length label{font-weight:700}
.test-length span{color:var(--muted)}
.gameplay-objective{display:grid;gap:6px;margin:0 0 16px;font-size:14px}
.gameplay-objective label{font-weight:700}
.gameplay-objective input{width:100%;box-sizing:border-box;background:var(--card);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px 10px;font:inherit}
.gameplay-objective small,.live-objective{color:var(--muted)}
.gameplay-objective button{justify-self:start}
.live-objective{font-size:13px;overflow-wrap:anywhere;margin:6px 0}
.guide-plan{margin:-4px 0 16px;padding:10px 14px;border:1px solid var(--line);border-radius:10px;font-size:14px}
.guide-plan summary{cursor:pointer;font-weight:700}
.guide-plan ol{margin:8px 0 0;padding-left:20px}
.guide-plan li+li{margin-top:8px}
.guide-plan small{display:block;color:var(--muted);font-size:13px}
.btn-over{font-size:16px;padding:12px 20px}
.section-prompt{width:min(460px,calc(100% - 32px));box-sizing:border-box;padding:22px;border:1px solid var(--line);border-radius:16px;background:var(--card);color:var(--text);box-shadow:var(--shadow)}
.section-prompt::backdrop{background:rgba(0,0,0,.58)}
.section-prompt h2{margin:0 0 8px;font-size:21px}
.section-prompt p{margin:0 0 14px;color:var(--muted)}
.section-prompt [role="alert"]{color:var(--red)}
.section-prompt img{display:block;width:100%;max-height:34vh;object-fit:contain;background:#000;border-radius:8px}
.section-prompt ol{margin:6px 0 12px;padding-left:24px;font-size:13px;overflow-wrap:anywhere}
.section-prompt-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}
.section-prompt .btn-go{font-size:15px;padding:9px 14px;border-radius:10px}
.where{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:16px}
@media (max-width:640px){.where{grid-template-columns:1fr}}
.wopt{display:flex;gap:12px;align-items:center;border:2px solid var(--line);border-radius:14px;padding:12px 14px;cursor:pointer}
.wopt input{position:absolute;opacity:0;pointer-events:none}
.wopt .wi{font-size:28px}
.wopt b{display:block;font-size:16px} .wopt small{display:block;color:var(--muted);font-size:13px;line-height:1.35}
.wopt.on{border-color:var(--blue);background:var(--blue-soft)}
.wopt.off{opacity:.5;cursor:not-allowed}
.nowbtn{width:100%;background:var(--blue);border-color:var(--blue);color:#fff;padding:10px 12px}
.nowbtn:hover:not(:disabled){filter:brightness(1.08);border-color:var(--blue)}
.search{display:flex;align-items:center;gap:6px;border:1px solid var(--line);border-radius:10px;padding:2px 4px 2px 10px;background:var(--card)}
.search:focus-within{border-color:var(--blue)}
.search input{flex:1;min-width:0;border:0;background:transparent;color:var(--text);font:inherit;font-size:15px;padding:7px 2px;outline:none}
.search button{border:0;background:var(--soft);padding:5px 10px;font-size:14px}
.applist{max-height:230px;overflow:auto;border:1px solid var(--line);border-radius:10px;margin-top:6px}
.applist .grp{position:sticky;top:0;background:var(--soft);font-size:12px;font-weight:700;color:var(--muted);padding:5px 10px;text-transform:uppercase;letter-spacing:.05em}
.applist .app{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid var(--line);border-radius:0;background:var(--card);padding:8px 10px;font-weight:400}
.applist .app:hover{background:var(--blue-soft)}
.applist .app b{display:block;font-size:14.5px} .applist .app small{color:var(--muted);font-size:12px;word-break:break-all}
.applist mark{background:var(--amber-soft);color:inherit;border-radius:3px}
.opts{display:flex;gap:18px;flex-wrap:wrap;margin-top:12px;font-size:14.5px;color:var(--muted)}
.opts label{display:flex;align-items:center;gap:7px;cursor:pointer}
.opts input{width:18px;height:18px}

/* live */
.live{display:grid;grid-template-columns:220px 1fr;gap:18px;align-items:start}
.live.landscape{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}
@media (max-width:700px){.live,.live.landscape{grid-template-columns:1fr}}
.phone{background:#000;border-radius:18px;padding:8px;aspect-ratio:9/19;display:grid;place-items:center;overflow:hidden;max-width:220px}
.live.landscape .phone{max-width:none}
.phone img{width:100%;height:100%;object-fit:contain;border-radius:10px}
.phone span{color:#889;font-size:13px;text-align:center;padding:10px}
.bar{height:14px;background:var(--soft);border-radius:999px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--blue);width:0;transition:width .5s}
.now{font-size:17px;font-weight:600;margin:10px 0 4px}
.step-head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-top:12px}
.step-head h3{font-size:14px;margin:0}
.step-hint{color:var(--muted);font-size:13px;margin:4px 0 6px}
.step-list{max-height:14rem;overflow:auto;margin:6px 0 0;padding:0;list-style:none;border:1px solid var(--line);border-radius:8px;font-size:14px}
.step-list li{display:grid;grid-template-columns:minmax(4.25em,max-content) 1fr;gap:8px;padding:6px 10px;overflow-wrap:anywhere}
.step-number{color:var(--muted);font-variant-numeric:tabular-nums}
.step-check{display:block;margin-top:2px;color:var(--muted);font-size:13px}
.step-list li+li{border-top:1px solid var(--line)}
.step-list .pending{color:var(--muted)}
.step-list [aria-current="step"]{color:var(--text);background:var(--soft);font-weight:600}
.feed{max-height:230px;overflow:auto;font-size:14px;border-top:1px solid var(--line);margin-top:10px;padding-top:8px}
.lpane{display:none} .lpane.on{display:block}
/* AI player */
.aisum{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;cursor:pointer;list-style:none;font-size:16px}
.aisum::-webkit-details-marker{display:none}
.aihint{color:var(--muted);font-size:14px}
#aiTag.on{background:var(--green-soft);color:var(--green)}
.aibody{margin-top:12px;display:flex;flex-direction:column;gap:10px}
.aigrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.aigrid label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--muted)}
.aigrid select,.aigrid input{font:inherit;font-size:14.5px;padding:7px 10px;border-radius:9px;border:1px solid var(--line);background:var(--card);color:var(--text)}
.switch{display:flex;gap:8px;align-items:center;font-weight:600;cursor:pointer}
.switch input{width:18px;height:18px}
.aires{font-size:14px} .aires.ok{color:var(--green)} .aires.bad{color:var(--red)}
.aihelp{font-size:13.5px;background:var(--soft);border-radius:10px;padding:9px 12px}
.aihelp code{background:var(--card);padding:1px 6px;border-radius:6px}
/* test cases in step 3 */
.inp{display:flex;gap:6px;align-items:center;margin:4px 0;font-size:14px}
.inp span{min-width:90px;font-weight:600} .inp input{flex:1;min-width:0;font:inherit;font-size:14px;padding:5px 8px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--text)}
.inp.miss input{border-color:var(--amber)}
.caselist{font-size:14px;margin-top:6px} .caselist summary{cursor:pointer;color:var(--blue);font-weight:600}
.caselist ol{padding-left:20px;margin:6px 0} .caselist li{margin-bottom:4px} .caselist small{color:var(--muted)}
/* help-needed box */
.askcard{border:3px solid var(--amber);background:var(--amber-soft);position:sticky;top:76px;z-index:9;animation:askpulse 1.6s ease-in-out 3}
@keyframes askpulse{50%{box-shadow:0 0 0 6px rgba(234,179,8,.35)}}
.askhead{font-size:20px;font-weight:800;display:flex;justify-content:space-between;gap:10px}
.asktimer{font-size:13px;font-weight:600;color:var(--muted)}
.asktitle{font-weight:700;margin-top:4px;color:var(--muted)}
.asktext{font-size:17px;margin:8px 0 10px}
#askNote{width:100%;font:inherit;font-size:14px;padding:7px 10px;border-radius:9px;border:1px solid var(--line);background:var(--card);color:var(--text);margin-bottom:10px}
.askbtns{display:flex;gap:10px;flex-wrap:wrap}
.askbtns button{font-size:17px;padding:11px 22px;border-radius:12px}
.askbtns .b-Done,.askbtns .b-Passed{background:var(--green);border-color:var(--green);color:#fff}
.askbtns .b-Failed{background:var(--red);border-color:var(--red);color:#fff}
/* test cases live + result */
.caselive{margin-top:10px;display:flex;flex-direction:column;gap:4px;max-height:200px;overflow:auto}
.caselive div{display:flex;gap:8px;font-size:14px;padding:4px 8px;border-radius:8px;background:var(--soft)}
.caselive .cur{outline:2px solid var(--blue)}
.cres{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}
.cres div{border-radius:14px;padding:14px;text-align:center} .cres b{display:block;font-size:30px}
.cres .p{background:var(--green-soft);color:var(--green)} .cres .f{background:var(--red-soft);color:var(--red)} .cres .n{background:var(--amber-soft);color:var(--amber)}
.ctable td{vertical-align:top} .ctable img{max-width:90px;border-radius:8px;border:1px solid var(--line)}
.vst{font-weight:800;white-space:nowrap} .vst.PASSED{color:var(--green)} .vst.FAILED{color:var(--red)} .vst.NOT{color:var(--amber)}
.tabs .cnt{font-size:12px;color:var(--muted);font-weight:600}
.logbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
.logbar input[type=search]{flex:1;min-width:160px;font:inherit;font-size:14.5px;padding:7px 10px;border-radius:9px;border:1px solid var(--line);background:var(--card);color:var(--text)}
.logbar label{display:flex;align-items:center;gap:6px;font-size:14px;color:var(--muted);cursor:pointer}
.logbar button{padding:6px 12px;font-size:14px}
.loghelp{font-size:13px;color:var(--muted);margin-bottom:6px}
.log.big{height:420px}
.log .lt{color:#7d8896} .log mark{background:#5a4a00;color:#fff}
.feed div{padding:3px 0} .feed .bad{color:var(--red)} .feed .warn{color:var(--amber)} .feed .t{color:var(--muted);font-family:var(--mono);font-size:12px;margin-right:6px}

/* verdict */
.verdict{display:flex;gap:18px;align-items:center;border-radius:14px;padding:18px;flex-wrap:wrap}
.verdict.GO{background:var(--green-soft)} .verdict.CONDITIONAL,.verdict.INCOMPLETE{background:var(--amber-soft)} .verdict.NO-GO{background:var(--red-soft)}
.verdict .icon{font-size:44px;line-height:1}
.verdict .head{font-size:24px;font-weight:800}
.verdict.GO .head{color:var(--green)} .verdict.CONDITIONAL .head,.verdict.INCOMPLETE .head{color:var(--amber)} .verdict.NO-GO .head{color:var(--red)}
.verdict .why{color:var(--text);margin-top:2px}
/* how far the test got */
.endbar{border-radius:14px;padding:12px 16px;margin-bottom:12px;background:var(--soft)}
.endbar.early{background:var(--amber-soft)} .endbar.lost{background:var(--red-soft)}
.endbar .row1{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-weight:700}
.endbar .bar{margin-top:8px;height:10px}
.endbar .bar i{background:var(--green)} .endbar.early .bar i{background:var(--amber)} .endbar.lost .bar i{background:var(--red)}
.endbar small{display:block;color:var(--muted);margin-top:6px;font-size:13.5px}
/* checklist board */
.board{margin-top:18px;border-top:1px solid var(--line);padding-top:16px}
.board h3{margin:0 0 4px;font-size:17px} .board .sub{margin-bottom:10px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.chip{border:2px solid transparent;border-radius:999px;padding:6px 14px;font-weight:700;font-size:14.5px;cursor:pointer;background:var(--soft);color:var(--text)}
.chip.on{border-color:var(--blue)}
.chip.c-passed{background:var(--green-soft);color:var(--green)} .chip.c-failed{background:var(--red-soft);color:var(--red)}
.chip.c-not{background:var(--amber-soft);color:var(--amber)}
.cgroup{margin-bottom:12px} .cgroup h4{margin:0 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.citem{display:grid;grid-template-columns:28px minmax(0,1fr) auto;gap:10px;align-items:center;padding:8px 10px;border-radius:10px;background:var(--soft);margin-bottom:5px}
.citem .ic{font-size:18px;text-align:center} .citem .nm{font-weight:600} .citem .dt{font-size:13.5px;color:var(--muted)}
.citem .st{font-size:12.5px;font-weight:800;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}
.st.passed{color:var(--green)} .st.failed{color:var(--red)} .st.not_run,.st.partial{color:var(--amber)} .st.skipped,.st.manual{color:var(--muted)}
/* games */
.games{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.gcard{border:2px solid var(--line);border-radius:14px;padding:14px;cursor:pointer;background:var(--card);text-align:left;font-weight:400;display:flex;flex-direction:column;gap:6px}
.gcard:hover{border-color:var(--blue)} .gcard.on{border-color:var(--blue);background:var(--blue-soft)}
.gcard .gn{font-weight:800;font-size:16.5px;line-height:1.25} .gcard .gp{font-size:12px;color:var(--muted);word-break:break-all}
.gcard .gs{display:flex;gap:12px;flex-wrap:wrap;font-size:13.5px;color:var(--muted)} .gcard .gs b{color:var(--text)}
.trend{display:flex;gap:4px;align-items:center;font-size:12.5px;color:var(--muted)}
.trend i{width:14px;height:14px;border-radius:4px;display:inline-block}
.trend i.pass{background:var(--green)} .trend i.warn{background:var(--amber)} .trend i.fail{background:var(--red)} .trend i.unfinished{background:var(--line)}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:14px}
.fact{background:var(--soft);border-radius:12px;padding:10px 12px}
.fact b{display:block;font-size:20px} .fact span{font-size:13px;color:var(--muted)}
.fact.good b{color:var(--green)} .fact.bad b{color:var(--red)} .fact.warn b{color:var(--amber)}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
.actions a{text-decoration:none}

/* tabs */
.tabs{display:flex;gap:6px;flex-wrap:wrap;border-bottom:1px solid var(--line);margin:-4px 0 14px}
.tabs button{border:0;border-bottom:3px solid transparent;border-radius:0;background:none;padding:10px 12px;color:var(--muted)}
.tabs button.on{color:var(--blue);border-bottom-color:var(--blue)}
.pane{display:none} .pane.on{display:block}
.explain{font-size:14px;color:var(--muted);background:var(--soft);border-radius:10px;padding:9px 12px;margin-bottom:12px}

/* problems */
.prob{border:1px solid var(--line);border-left:6px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:10px}
.prob.serious{border-left-color:var(--red)} .prob.medium{border-left-color:var(--amber)} .prob.small{border-left-color:#9aa8b9}
.prob .lvl{font-size:12.5px;font-weight:800;text-transform:uppercase;letter-spacing:.04em}
.prob.serious .lvl{color:var(--red)} .prob.medium .lvl{color:var(--amber)} .prob.small .lvl{color:var(--muted)}
.prob .what{font-weight:700;font-size:16px;margin:2px 0}
.prob .plain{color:var(--muted);font-size:14.5px}
.prob details{margin-top:8px;font-size:14px} .prob summary{cursor:pointer;color:var(--blue);font-weight:600}
.prob ol{margin:6px 0;padding-left:20px} .prob pre{font:12px var(--mono);white-space:pre-wrap;background:var(--soft);padding:8px;border-radius:8px;margin:6px 0 0;max-height:220px;overflow:auto}

table{width:100%;border-collapse:collapse;font-size:14.5px}
th{text-align:left;font-size:13px;color:var(--muted);font-weight:600;border-bottom:1px solid var(--line);padding:8px}
td{border-bottom:1px solid var(--line);padding:9px 8px;vertical-align:top}
tr.click{cursor:pointer} tr.click:hover td{background:var(--soft)} tr.sel td{background:var(--blue-soft)}
.pill{font-size:12.5px;font-weight:700;padding:2px 10px;border-radius:999px;white-space:nowrap}
.pill.good{background:var(--green-soft);color:var(--green)} .pill.bad{background:var(--red-soft);color:var(--red)}
.pill.warn{background:var(--amber-soft);color:var(--amber)} .pill.none{background:var(--soft);color:var(--muted)}
.chart{background:var(--soft);border-radius:12px;padding:10px 12px}
.chart b{font-size:14px} .chart small{color:var(--muted)}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-top:12px}
.log{background:#0b0f14;color:#cfd8e3;border-radius:10px;height:320px;overflow:auto;font:12px/1.45 var(--mono);padding:10px;white-space:pre-wrap;word-break:break-word}
.log .E,.log .F{color:#ff7b72} .log .W{color:#f2cc60} .log .D,.log .V{color:#7d8896}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
select,input[type=text]{font:inherit;font-size:14.5px;padding:7px 10px;border-radius:9px;border:1px solid var(--line);background:var(--card);color:var(--text)}
.empty{color:var(--muted);padding:14px 4px}
.toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:#18202b;color:#fff;padding:12px 18px;border-radius:12px;
  font-size:15px;opacity:0;transition:opacity .25s;pointer-events:none;z-index:50;max-width:90vw}
.toast.on{opacity:1}
[hidden]{display:none!important}
</style>
</head>
<body>
<div class="top"><div class="top-in">
  <a class="brand" href="/" title="Game Tester home">
    <div class="logo">🎮</div>
    <div class="title"><b>Game Tester</b><span>Automatic quality check for Android games &amp; apps</span></div>
  </a>
  <nav class="nav" aria-label="Pages">
    <a class="navbtn on" href="/" title="The simple tester – start here">🏠 <span>Tester</span></a>
    <a class="navbtn" href="/studio" target="_blank" title="For QA engineers: edit every rule and setting by hand">🛠 <span>Advanced editor</span></a>
  </nav>
  <div class="spacer"></div>
  <span class="status" id="status"><i class="dot"></i><b>Getting ready…</b></span>
  <button class="helpbtn" id="helpBtn" title="Step-by-step guide">❓ How to use</button>
</div></div>

<div class="help-back" id="helpBack" hidden></div>
<aside class="guide" id="help" hidden role="dialog" aria-labelledby="helpTitle">
  <div class="help-head">
    <div><div class="help-kicker">Guide</div><h2 id="helpTitle">How to use Game Tester</h2></div>
    <button class="help-x" id="helpClose" aria-label="Close guide">✕</button>
  </div>
  <div class="help-tabs" id="helpTabs">
    <button data-h="quick" class="on">Quick start</button>
    <button data-h="screen">Every part of the screen</button>
    <button data-h="results">Reading results</button>
    <button data-h="advanced">Advanced editor</button>
    <button data-h="problems">Problems &amp; fixes</button>
    <button data-h="cases">Test-case files</button>
    <button data-h="words">Words explained</button>
  </div>
  <div class="help-body">

    <section data-h="quick" class="on">
      <p class="hl">Game Tester plays your game by itself – tapping, swiping, leaving and coming back, rotating, losing internet – and then tells you in plain words if the game is ready to release.</p>
      <ol class="big-steps">
        <li><b>Open the tester.</b> Double-click <code>Start Game Tester.bat</code> in the project folder. A black window opens (keep it open) and this page opens in your browser.</li>
        <li><b>Connect your phone</b> with a USB cable. First time only: turn on <i>USB debugging</i> (see “Problems &amp; fixes”) and tap <b>Allow</b> on the phone. Step 1 turns green.<br><small>No phone? Skip this and choose <b>Practice phone</b> later.</small></li>
        <li><b>Choose the game</b> (step 2). Easiest: open the game on your phone and press <b>📲 Use the game that is open on my phone</b>. Or type its name in the <b>🔍 search box</b> and click it. Or drag in a game <code>.apk</code> file.</li>
        <li><i>Optional:</i> <b>Add what to check</b> (step 3): a document describing the game (levels, coins, ads…). The tester uses it to decide what matters most.</li>
        <li><b>Choose where to test:</b> <b>📱 My phone</b> (the real game) or <b>🧪 Practice phone</b> (a pretend game, to learn how it works).</li>
        <li>Press the green <b>▶ Start testing</b>. Watch the phone screen and the live list. A normal test takes about 10–15 minutes.</li>
        <li><b>Read the result:</b> ✅ <i>Ready to release</i>, ⚠️ <i>Release with care</i> or ❌ <i>Not ready</i>. Open the tabs below it for details. Use <b>📝 Bug list for developers</b> to send problems to your team.</li>
      </ol>
      <div class="tip">💡 You can press <b>■ Stop now</b> at any time – you still get the result for what ran. <b>↻ Start over</b> clears the screen for a new test.</div>
    </section>

    <section data-h="screen">
      <dl class="parts">
        <dt>🏠 Tester / 🛠 Advanced editor <span>(top bar)</span></dt>
        <dd><b>Tester</b> is this simple page. <b>Advanced editor</b> opens the full editor for QA engineers in a new tab – you never need it for normal testing.</dd>
        <dt>Status <span>(top right)</span></dt>
        <dd><i>Ready</i> – waiting for you. <i>Testing…</i> – a test runs. <i>Test finished</i> – result is below. <i>Last test could not run</i> – a red box explains why and what to do.</dd>
        <dt>Step 1 · Connect your phone</dt>
        <dd>Shows your phone's name when it is connected (green). Orange means it is plugged in but you still need to tap <b>Allow</b> on the phone. <b>↻ Check again</b> looks for the phone right now.</dd>
        <dt>Step 2 · Choose the game</dt>
        <dd>When a phone is connected: open the game on the phone and press <b>📲 Use the game that is open on my phone</b>, or type part of the name in the <b>🔍 search box</b> (press Enter to take the first match) – pick one (the game is tested exactly as installed; your saved progress is not touched). Or drag a <code>.apk</code> file into the box. The card then shows the name, version, <i>Game/App</i> and where it comes from. <b>✕ Remove this game</b> clears it.</dd>
        <dt>Step 3 · Add what to check <span>(optional)</span></dt>
        <dd>Drag a <code>.md</code>, <code>.txt</code> or <code>.docx</code> file that describes the game. It becomes a list of checks. <b>✕ Remove this file</b> clears it.</dd>
        <dt>Where should the game be tested?</dt>
        <dd><b>📱 My phone</b> – the real game on your phone (greyed out when no phone is connected). <b>🧪 Practice phone</b> – a built-in pretend game; nothing on your phone is touched.</dd>
        <dt>▶ Start testing · ■ Stop now · ↻ Start over</dt>
        <dd><b>Start</b> begins the test (the sentence next to it says exactly what will happen, or what is still missing). <b>Stop now</b> ends the test within a second and keeps the result so far. <b>Start over</b> stops any test and clears the screen.</dd>
        <dt>The three tick boxes</dt>
        <dd><b>Start by itself when a phone is plugged in</b> – plug in a phone and testing starts automatically (a game must be chosen). <b>Install my game file on the phone first</b> – only shown for <code>.apk</code> files; untick to test the version already on the phone. <b>Use my requirements file</b> – let step 3 shape the test.</dd>
        <dt>Testing now…</dt>
        <dd>The live phone screen, a progress bar with time left, and a list of what just happened (✔ passed, 💥 crash, 🧊 freeze, 📵 phone disconnected).</dd>
        <dt>Your games</dt>
        <dd>One card per game you tested: its latest result, a row of coloured squares for its history (green passed, orange care, red not ready, grey unfinished), number of tests, crash types and smoothness. Click a card to see only that game's tests and its latest result; click it again (or “Show all games”) to see everything.</dd>
        <dt>Past tests</dt>
        <dd>Every test you ran. Click one to see its result again.</dd>
      </dl>
    </section>

    <section data-h="results">
      <dl class="parts">
        <dt>The big answer</dt>
        <dd>✅ <b>Ready to release</b> – no serious or medium problems. ⚠️ <b>Release with care</b> – medium problems; a person should decide. ❌ <b>Not ready</b> – serious problems (crash, freeze, game did not survive a real-life event). Fix them first.</dd>
        <dt>How far the test got <span>(bar above the answer)</span></dt>
        <dd>🏁 <i>Finished</i>, ■ <i>Stopped by you</i>, 📵 <i>Phone disconnected</i> or ⏱ <i>Ended early</i>, with “88 of 400 steps · 22% done”. If it ended early, only part of the game was tested.</dd>
        <dt>Test checklist <span>(under the result)</span></dt>
        <dd>Every single check, grouped: opening the game, playing, real-life events, speed &amp; battery, and your requirements. Each one is ✅ <b>Passed</b>, ❌ <b>Failed</b>, ⏳ <b>Not tested</b> (the test ended before it was reached), ◐ <b>Partly done</b>, ⏭ <b>Skipped</b> (the phone does not allow it) or 👤 <b>A person must check</b>. Click the coloured boxes to show only failed, only not tested, and so on.</dd>
        <dt>The number boxes</dt>
        <dd>Serious problems · smoothness (fps, 60 is perfect, under 30 feels laggy) · time to open the game · real-life tests passed · screens visited · testing time. Green is good, orange needs work, red is bad.</dd>
        <dt>Buttons under the result</dt>
        <dd><b>📄 Open full report</b> – everything, with screenshots. <b>📝 Bug list for developers</b> – ready to paste into Jira/Trello/email. <b>🎬 Watch the recording</b> – when a video was made.</dd>
        <dt>Tab · Problems found</dt>
        <dd>Each problem has a level (Serious / Medium / Small), one simple sentence, and <i>Details for the developer</i>: likely cause, how to repeat it, and the technical message.</dd>
        <dt>Tab · Real-life tests</dt>
        <dd>Did the game survive: leaving and coming back, turning the phone, lock/unlock, losing internet, low memory, Android closing it in the background? Passed / Failed per event.</dd>
        <dt>Tab · Speed &amp; battery</dt>
        <dd>Opening time, smoothness, worst moment, memory, memory leak, phone work (CPU) and temperature – each with <i>Good</i> or <i>Needs work</i> and a one-line explanation, plus small charts over time.</dd>
        <dt>Tab · Compared to last version</dt>
        <dd>New crashes, fixed crashes, and what got better or worse than the previous version you tested on the same kind of phone.</dd>
        <dt>Tab · Requirements</dt>
        <dd>Checks made from your step-3 document: <i>Passed</i>, <i>Failed</i>, <i>Not sure</i>, or <i>A person must check</i> (things like prices and rewards).</dd>
        <dt>Tab · Technical log</dt>
        <dd>The phone's own log for developers. Choose “Only errors” to see red lines only.</dd>
      </dl>
    </section>

    <section data-h="advanced">
      <p class="hl">The <b>Advanced editor</b> is for QA engineers who want to change every setting by hand. Everything there is optional – the simple Tester already picks good settings.</p>
      <dl class="parts">
        <dt>1 · APK</dt><dd>Drop a game file; its details are read without a phone.</dd>
        <dt>2 · Requirements</dt><dd>Drop the game document; it is split into requirements.</dd>
        <dt>3 · Device</dt><dd>Pick which connected phone to use, and run on the phone or the practice phone. The checklist shows what is missing (adb, phone, Allow, taps).</dd>
        <dt>4 · Run options</dt><dd>How the tester plays (policy), how many steps, time limit, video speed, reinstall, recording. Press <b>Apply options</b>.</dd>
        <dt>5 · Test plan (check logic)</dt><dd>The pass/fail rules. <b>Visual rules</b>: add, change or delete rules with drop-downs, or use <b>+ Add preset</b>. <b>JSON</b>: the same rules as text. Also <i>ignore patterns</i> (known harmless errors) and notes.</dd>
        <dt>6 · Live screen</dt><dd>The phone screen during the test, with a film strip.</dd>
        <dt>7 · Run logic</dt><dd>Every input the tester sent and why it chose it.</dd>
        <dt>8 · Test cases</dt><dd>Test cases made from the document; you can mark them, approve the plan, or regenerate.</dd>
        <dt>Checks · Findings</dt><dd>Each rule with expected vs. actual, and every crash/freeze found.</dd>
        <dt>Top buttons</dt><dd><b>▶ Start test</b> runs with exactly your settings · <b>■ Stop</b> · <b>↻ Restart</b> clears the last result · <b>← Simple tester</b> comes back here.</dd>
      </dl>
    </section>

    <section data-h="problems">
      <dl class="parts">
        <dt>“No phone found”</dt>
        <dd>On the phone: <b>Settings → About phone</b> → tap <b>Build number</b> 7 times. Then <b>Settings → Developer options → USB debugging</b> ON. Plug in the cable and press <b>↻ Check again</b>.</dd>
        <dt>“Not allowed yet”</dt>
        <dd>Look at the phone screen and tap <b>Allow</b> (tick “Always allow from this computer”).</dd>
        <dt>“The phone stopped answering” / 📵</dt>
        <dd>The USB connection dropped. Use a different cable or USB port (cables made only for charging do not work), keep the phone unlocked, and test again.</dd>
        <dt>“Phone has a newer version”</dt>
        <dd>Nothing to do – the tester automatically tests the newer version already on the phone. To test your file instead, add the newer <code>.apk</code>.</dd>
        <dt>Taps do nothing (Xiaomi, Realme, Oppo, Vivo)</dt>
        <dd>In Developer options also turn on <b>USB debugging (Security settings)</b> or turn off <b>Disable permission monitoring</b>, then replug.</dd>
        <dt>The page does not open</dt>
        <dd>The tester is not running. Double-click <code>Start Game Tester.bat</code> and keep its black window open.</dd>
        <dt>A test seems stuck</dt>
        <dd>Press <b>■ Stop now</b>, then <b>↻ Start over</b>. If the phone shows a pop-up (update, login, permission), close it on the phone and test again.</dd>
      </dl>
    </section>

    <section data-h="cases">
      <p class="hl">Write your test cases in a simple <code>.md</code> (or .txt / .docx) file and drop it in <b>step 3</b>. Then choose <b>📋 Run my test cases</b> and press <b>▶ Run my test cases</b>.</p>
      <pre class="mdex">## Inputs
- username: player1
- level: 3

## TC-01: Turn the music off
Steps:
1. Tap the Settings button
2. Turn Music off
Expected: The music switch shows OFF

## TC-02: Win level {level}  [human]
- Open level {level}
- Finish the level
Expected: A win screen with stars appears</pre>
      <dl class="parts">
        <dt>Test case title</dt><dd>A heading like <code>## TC-01: …</code>, <code>## Test 2 - …</code> or <code>### Case 3: …</code>.</dd>
        <dt>Steps</dt><dd>A numbered or bulleted list. Put <code>[human]</code> after a step (or the title) when a person must do it, e.g. a real payment or a captcha.</dd>
        <dt>Expected</dt><dd><code>Expected:</code> what should be on the screen at the end. Without it, you will be asked to judge.</dd>
        <dt>Inputs</dt><dd>Write <code>{username}</code> in a step and give the value in an <code>## Inputs</code> list – or type it in the boxes that appear in step 3.</dd>
        <dt>How each case is decided</dt><dd>✅ <b>Passed</b> – every step done and the expected result confirmed (by the AI or by you). ❌ <b>Failed</b> – a step could not be done because the game is wrong, the expected result was not there, or the game crashed/froze (always Failed). ⚠️ <b>Not passed</b> – the case could not be completed: skipped, you were not sure, nobody answered in time, you stopped the run or the phone disconnected.</dd>
        <dt>When the tester needs you</dt><dd>A yellow <b>🙋 Your help is needed</b> box appears at the top: do what it says on the phone and press <b>Done</b>, or answer <b>Passed / Failed / Not sure</b>. You can add a note for the report.</dd>
        <dt>With or without AI</dt><dd>With the <b>🤖 AI player</b> on, the tester does the steps and checks results itself and only asks you when it cannot. With it off, you do each step and judge; the tester shows the steps, watches for crashes and writes the report.</dd>
      </dl>
    </section>

    <section data-h="words">
      <dl class="parts">
        <dt>APK</dt><dd>The install file of an Android game – the same file you upload to Google Play.</dd>
        <dt>Crash</dt><dd>The game closes suddenly.</dd>
        <dt>Freeze (ANR)</dt><dd>The game stops responding; Android shows “App isn't responding”.</dd>
        <dt>fps (smoothness)</dt><dd>Pictures per second. 60 is perfect, 30 is OK, below 30 feels laggy.</dd>
        <dt>Cold start / warm start</dt><dd>Time to open the game from nothing / when it was already open in the background.</dd>
        <dt>Memory leak</dt><dd>Memory that keeps growing during play – the game gets slower and is eventually closed by Android.</dd>
        <dt>Real-life tests</dt><dd>Things real users do: press Home, rotate, lock, lose internet, run low on memory, come back after Android closed the game.</dd>
        <dt>Practice phone</dt><dd>A pretend phone with a pretend game inside the tester, with some bugs on purpose so you can see what results look like.</dd>
        <dt>Regression</dt><dd>Something that got worse compared to the previous version.</dd>
        <dt>Requirements file</dt><dd>A document that describes how the game should work.</dd>
      </dl>
    </section>
  </div>
  <div class="help-foot"><label><input type="checkbox" id="helpAgain"> Show this guide when I open the tester</label>
    <button class="help-done" id="helpDone">Got it</button></div>
</aside>

<div class="wrap">
  <h1>Test your game in 3 steps</h1>
  <p class="lead">Do steps 1 and 2, then press the green <b>Start testing</b> button. The tester plays your game by itself and tells you if it is ready to release.</p>

  <div class="steps">
    <div class="step" id="s1">
      <div class="num"><i>1</i> Connect your phone</div>
      <div class="state" id="s1State">Looking for a phone…</div>
      <details class="help"><summary>How do I connect my phone?</summary>
        <ol><li>On the phone open <b>Settings → About phone</b> and tap <b>Build number</b> 7 times.</li>
          <li>Go back to <b>Settings → Developer options</b> and turn on <b>USB debugging</b>.</li>
          <li>Plug the phone into this computer with a USB cable and tap <b>Allow</b> on the phone.</li></ol>
        No phone? You can still try the tester – it will use a <b>practice phone</b> (simulator).
      </details>
      <button id="refreshPhone" style="align-self:flex-start;font-size:14px;padding:6px 12px">↻ Check again</button>
    </div>

    <div class="step" id="s2">
      <div class="num"><i>2</i> Choose the game</div>
      <div class="state" id="s2State">No game chosen yet.</div>
      <button id="removeGame" hidden style="align-self:flex-start;font-size:14px;padding:5px 12px;color:var(--red)">✕ Remove this game</button>
      <div id="phonePick" hidden>
        <button class="nowbtn" id="useOpen" title="Open the game on your phone, then press this">📲 Use the game that is open on my phone</button>
        <div style="font-size:13px;color:var(--muted);margin:8px 0 6px;text-align:center">— or search the games on your phone —</div>
        <div class="search"><span>🔍</span><input type="search" id="appSearch" placeholder="Type a game name…" autocomplete="off">
          <button id="appRefresh" title="Reload the list from the phone">↻</button></div>
        <div class="applist" id="appList"><div class="empty">Loading the phone's games…</div></div>
        <div style="font-size:13px;color:var(--muted);margin:8px 0 2px;text-align:center">— or —</div>
      </div>
      <div class="drop" id="apkDrop">📦 Click here or drag a game <b>.apk</b> file</div>
      <input type="file" id="apkFile" accept=".apk" hidden>
      <div class="hint">The .apk is the install file of your game, the same file you upload to Google Play.</div>
    </div>

    <div class="step" id="s3">
      <div class="num"><i>3</i> Add test cases <span class="tag" style="margin-left:4px">optional</span></div>
      <div class="state" id="s3State">No requirements file.</div>
      <div id="casesBox" hidden>
        <div id="inputsBox"></div>
        <details class="caselist"><summary id="caseSum">Show the test cases</summary><ol id="caseList"></ol></details>
      </div>
      <button id="removeDoc" hidden style="align-self:flex-start;font-size:14px;padding:5px 12px;color:var(--red)">✕ Remove this file</button>
      <div class="drop" id="docDrop">📝 Click here or drag a <b>.md / .txt / .docx</b> file</div>
      <input type="file" id="docFile" accept=".md,.markdown,.txt,.docx,.pdf" hidden>
      <div class="hint">Your <b>test cases</b> (steps + expected result) to run one by one – <a href="#" id="mdHelp">see the format</a>. Or a document describing the game, to guide automatic testing.</div>
    </div>
  </div>

  <div class="card" id="aiCard">
    <details id="aiDetails">
      <summary class="aisum"><span>🤖 <b>AI player</b> <span class="tag" id="aiTag">off</span></span>
        <span class="aihint" id="aiHint">Optional – lets the tester read the screen, do test steps and judge results by itself.</span></summary>
      <div class="aibody">
        <label class="switch"><input type="checkbox" id="aiOn"> Use the AI player</label>
        <div class="aigrid">
          <label>Which AI<select id="aiProvider"></select></label>
          <label>Model<input type="text" id="aiModel" placeholder="model name"></label>
          <label id="aiKeyBox">API key<input type="password" id="aiKey" placeholder="paste your key (kept only in memory)" autocomplete="off"></label>
          <label id="aiUrlBox">Server address<input type="text" id="aiUrl" placeholder="default"></label>
        </div>
        <div class="row"><button id="aiSave">Save</button><button id="aiTest">🔌 Test connection</button><span id="aiResult" class="aires"></span></div>
        <div class="aihelp" id="aiLocalHelp"><b>Free &amp; offline (recommended):</b> 1) install <b>Ollama</b> from ollama.com · 2) in a terminal run <code>ollama pull qwen2.5vl:7b</code> (≈6 GB, once) · 3) press <b>Test connection</b>. Your RTX graphics card makes it fast enough.</div>
        <div class="aihelp" id="aiCloudHelp" hidden><b>Cloud AI</b> is smarter but needs internet and costs money per move. The key is kept only while the tester is open – never saved to disk or reports.</div>
      </div>
    </details>
  </div>

  <div class="card">
    <div style="font-weight:700;margin-bottom:8px">What should the tester do?</div>
    <div class="where" id="what">
      <label class="wopt" id="wExplore"><input type="radio" name="what" value="explore">
        <span class="wi">🧭</span><span><b>Explore the game by itself</b><small>Plays freely, does real-life tests, finds crashes, freezes and slowness.</small></span></label>
      <label class="wopt" id="wCases"><input type="radio" name="what" value="cases">
        <span class="wi">📋</span><span><b>Run my test cases</b><small id="wCasesSub">Upload a test-case file in step 3 first.</small></span></label>
      <label class="wopt" id="wGuided" hidden><input type="radio" name="what" value="guided">
        <span class="wi">🎮</span><span><b>Guide me through the first-customer tutorial</b><small>You play on the phone and verify each result.</small></span></label>
    </div>
    <div class="test-length" id="testLengthPicker" hidden>
      <label for="testLength">Test length</label>
      <select id="testLength" aria-describedby="testLengthHint"></select>
      <span id="testLengthHint"></span>
    </div>
    <div class="gameplay-objective" id="gameplayObjective" hidden>
      <label for="objectiveInput">Gameplay objective <small>(optional)</small></label>
      <input type="text" id="objectiveInput" maxlength="300" aria-describedby="objectiveHint" placeholder="Example: Open settings and change the sound volume">
      <small id="objectiveHint">Directs the AI during exploration. Use a written test case for a pass/fail check.</small>
      <button type="button" id="firstCustomerObjective" hidden>Use first-customer objective</button>
    </div>
    <details class="guide-plan" id="guidePlan" open hidden>
      <summary>First-customer walkthrough</summary>
      <ol id="guidePlanSteps"></ol>
    </details>
    <div style="font-weight:700;margin-bottom:8px">Where should the game be tested?</div>
    <div class="where" id="where">
      <label class="wopt" id="wPhone"><input type="radio" name="where" value="phone">
        <span class="wi">📱</span><span><b>My phone</b><small id="wPhoneSub">The real game on your connected phone</small></span></label>
      <label class="wopt" id="wPractice"><input type="radio" name="where" value="practice">
        <span class="wi">🧪</span><span><b>Practice phone</b><small>A built-in pretend game – no phone needed. Good for learning.</small></span></label>
    </div>
    <div class="go">
      <button class="btn-go" id="startBtn">▶ Start testing</button>
      <button class="btn-stop" id="stopBtn" hidden>■ Stop now</button>
      <button class="btn-over" id="overBtn" hidden title="Stop any test and clear the screen">↻ Start over</button>
      <div class="why" id="goWhy"></div>
    </div>
    <div class="opts">
      <label title="As soon as a phone is plugged in, testing starts by itself."><input type="checkbox" id="optAuto"> Start by itself when a phone is plugged in</label>
      <label id="optInstallBox" title="Untick this to test the version that is already installed on the phone."><input type="checkbox" id="optInstall"> Install my game file on the phone first</label>
      <label title="Use the requirements document to decide what to check."><input type="checkbox" id="optSpec"> Use my requirements file</label>
    </div>
  </div>

  <div class="card" id="errCard" hidden style="border:2px solid var(--red)">
    <h2 style="color:var(--red)">⚠️ The last test could not run</h2>
    <p id="errPlain" style="font-size:16px;margin:6px 0 8px"></p>
    <p id="errFix" style="margin:0 0 8px"></p>
    <details class="help"><summary>Technical message</summary><pre id="errRaw" style="white-space:pre-wrap;font-size:12px"></pre></details>
  </div>

  <div class="card askcard" id="askCard" hidden>
    <div class="askhead">🙋 Your help is needed <span class="asktimer" id="askTimer"></span></div>
    <div class="asktitle" id="askTitle"></div>
    <div class="asktext" id="askText"></div>
    <input type="text" id="askNote" placeholder="Optional note for the report (what you saw)…">
    <div class="askbtns" id="askBtns"></div>
  </div>

  <dialog class="section-prompt" id="sectionPrompt" aria-labelledby="sectionPromptTitle" aria-describedby="sectionPromptText">
    <h2 id="sectionPromptTitle"></h2>
    <p id="sectionPromptText"></p>
    <div id="stuckEvidence" hidden>
      <img id="stuckShot" alt="Last screen before the tester paused" hidden>
      <details open><summary>Recent actions</summary><ol id="stuckActions"></ol></details>
    </div>
    <p id="sectionPromptError" role="alert" hidden></p>
    <div class="section-prompt-actions">
      <button type="button" id="sectionLater" autofocus>Not now</button>
      <button type="button" class="btn-go" id="sectionContinue">Continue</button>
    </div>
  </dialog>

  <div class="card" id="liveCard">
    <h2 id="liveTitle">Live view</h2>
    <p class="sub" id="liveSub">Watch the test while it runs, or look at the phone's log at any time.</p>
    <div class="tabs" id="liveTabs">
      <button data-l="watch" class="on">▶ What's happening</button>
      <button data-l="logcat">📜 Phone log (logcat) <span class="cnt" id="logCnt"></span></button>
    </div>
    <div class="lpane on" id="l-watch">
      <div class="live" id="liveRun" hidden>
        <div class="phone" id="phone"><span>The phone screen will appear here</span></div>
        <div>
          <div class="bar"><i id="bar"></i></div>
          <div class="now" id="nowText">Starting…</div>
          <div style="color:var(--muted);font-size:14px" id="nowSub"></div>
          <p class="live-objective" id="liveObjective" hidden></p>
          <div id="runSteps" hidden>
            <div class="step-head">
              <h3 id="runStepsTitle">Exploration steps</h3>
              <select id="runStepRange" aria-label="Step range" hidden></select>
            </div>
            <p class="step-hint" id="runStepHint"></p>
            <ol class="step-list" id="runStepList" role="list" aria-labelledby="runStepsTitle" tabindex="0"></ol>
          </div>
          <div class="caselive" id="caseLive" hidden></div>
          <div class="feed" id="feed"></div>
        </div>
      </div>
      <div class="empty" id="liveIdle">No test is running. Press <b>▶ Start testing</b> above and the phone screen and live steps appear here. The <b>📜 Phone log</b> tab works any time a phone is connected.</div>
    </div>
    <div class="lpane" id="l-logcat">
      <div class="logbar">
        <select id="lcLevel" title="Which lines to show">
          <option value="">All lines</option><option value="W">Warnings + errors</option><option value="E">Errors only</option></select>
        <input type="search" id="lcSearch" placeholder="🔍 Search the log…">
        <label title="Show only lines from the game you chose in step 2"><input type="checkbox" id="lcGame"> Only this game</label>
        <label title="Keep jumping to the newest line"><input type="checkbox" id="lcFollow" checked> Auto-scroll</label>
        <button id="lcPause" title="Freeze the log so you can read it">⏸ Pause</button>
        <button id="lcCopy" title="Copy the visible lines">📋 Copy</button>
        <button id="lcSave" title="Download the visible lines as a text file">💾 Save</button>
      </div>
      <div class="loghelp" id="lcHint">Red = error · orange = warning · grey = details. Developers use this to find out why something went wrong.</div>
      <div class="log big" id="lcBox"><div>Loading…</div></div>
    </div>
  </div>

  <div class="card" id="resultCard" hidden>
    <h2 id="resultTitle">Result</h2>
    <p class="sub" id="resultSub"></p>
    <div class="endbar" id="endbar"></div>
    <div class="verdict" id="verdict"></div>
    <div class="facts" id="facts"></div>
    <div class="actions" id="actions"></div>
    <div class="board" id="board"></div>
  </div>

  <div class="card" id="detailCard" hidden>
    <div class="tabs" id="tabs">
      <button data-p="problems" class="on">Problems found</button>
      <button data-p="life">Real-life tests</button>
      <button data-p="speed">Speed &amp; battery</button>
      <button data-p="compare">Compared to last version</button>
      <button data-p="checks">Requirements</button>
      <button data-p="log">Technical log</button>
    </div>
    <div class="pane on" id="p-problems"></div>
    <div class="pane" id="p-life"></div>
    <div class="pane" id="p-speed"></div>
    <div class="pane" id="p-compare"></div>
    <div class="pane" id="p-checks"></div>
    <div class="pane" id="p-log">
      <div class="explain">This is the phone's own log, for developers. Red lines are errors.</div>
      <div class="row"><select id="logLvl"><option value="">Show everything</option><option value="E">Only errors</option><option value="W">Errors and warnings</option></select>
        <input type="text" id="logQ" placeholder="Search the log…"></div>
      <div class="log" id="log"></div>
    </div>
  </div>

  <div class="card">
    <h2>Your games</h2>
    <p class="sub">Every game you have tested, with its latest result and how it went over time. Click a game to see only its tests.</p>
    <div class="games" id="games"><div class="empty">No games tested yet.</div></div>
  </div>

  <div class="card">
    <div class="history-tools">
      <h2 id="histTitle">Past tests</h2>
      <button type="button" class="history-delete" id="deleteRuns" disabled>Delete selected tests</button>
    </div>
    <p class="sub" id="histSub">Every test you ran. Click one to see its result above.</p>
    <div style="overflow-x:auto"><table>
      <thead><tr><th class="history-select"><input type="checkbox" id="selectAllRuns" aria-label="Select all visible saved tests" disabled></th><th>When</th><th>Result</th><th>Game</th><th>Problems</th><th>Ran on</th></tr></thead>
      <tbody id="history"></tbody></table></div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const num = (v) => v === null || v === undefined ? "–" : Number(v).toLocaleString();
let A = null, plan = null, devices = [], runs = [], shown = null, shownRun = "", lastStatus = "", lastSeq = 0, feed = [], logLines = [];
let resumingTest = false;
let savingPreset = false;
let objectivePackage = null;

function toast(msg) { const t = $("toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), 3800); }
async function J(url, opts) { const r = await fetch(url, opts); const j = await r.json().catch(() => ({})); if (!r.ok) throw new Error(j.error || ("error " + r.status)); return j; }

// ---------- plain-language helpers ----------
const VERDICT = {
  "GO": {icon: "✅", head: "Ready to release", tip: "No serious problems were found."},
  "CONDITIONAL": {icon: "⚠️", head: "Release with care", tip: "Some problems were found. A person should decide."},
  "NO-GO": {icon: "❌", head: "Not ready to release", tip: "Serious problems were found. Fix them first."},
  "INCOMPLETE": {icon: "⏸", head: "Results so far"},
};
const LEVEL = (sev) => sev.startsWith("S1") ? ["serious", "Serious problem"] : sev.startsWith("S2") ? ["medium", "Medium problem"] : ["small", "Small problem"];
const KIND_PLAIN = {
  java_crash: "The game crashed (closed suddenly).",
  native_crash: "The game crashed inside its engine (closed suddenly).",
  anr: "The game froze and stopped responding.",
  process_death: "The game disappeared without an error message.",
  low_memory: "The phone ran out of memory.",
  lifecycle: "The game did not survive something real users do.",
  performance: "The game is slower or heavier than it should be.",
  coverage: "The tester could not reach enough screens of the game.",
  regression: "This got worse compared to the last version.",
  log_signal: "Warning signs in the phone log (not a crash yet).",
};
const INT_PLAIN = {
  background: ["Leave the game and come back", "Press Home, wait, open the game again"],
  rotate: ["Turn the phone sideways", "Rotate to landscape and back"],
  lock: ["Lock and unlock the phone", "Screen off, then on again"],
  airplane: ["Lose internet", "Airplane mode on for 4 seconds"],
  memory: ["Phone low on memory", "Android asks the game to free memory"],
  kill_restore: ["Phone closes the game in the background", "Like when many apps are open, then the user returns"],
};
function plainTitle(i) {
  let t = i.title.replace(/^budget missed: /, "Target missed: ").replace(/^log warning: /, "").replace(/^regression vs [^:]+: /, "");
  t = t.replace(/^java crash: |^native crash: |^anr: |^process death: /, "");
  return t.length > 140 ? t.slice(0, 140) + "…" : t;
}
function whereRan(serial, backend) { return (backend === "simulator" || String(serial || "").startsWith("simulator")) ? "Practice phone" : "Real phone"; }

// ---------- steps ----------
async function loadDevices(force) {
  try { const d = await J("/api/device" + (force ? "?refresh=1" : "")); devices = d.devices || []; renderSteps(d.hint || ""); }
  catch (e) { renderSteps(e.message); }
}
function renderSteps(hint) {
  const online = devices.filter((d) => d.state === "device");
  const unauth = devices.filter((d) => d.state === "unauthorized");
  const s1 = $("s1");
  if (online.length) { s1.className = "step ok"; $("s1State").innerHTML = `<span class="big">📱 ${esc(online[0].model || "Phone")}</span> is connected.`; }
  else if (unauth.length) { s1.className = "step todo"; $("s1State").innerHTML = "A phone is plugged in but <b>not allowed yet</b>. Look at the phone and tap <b>Allow</b>."; }
  else { s1.className = "step"; $("s1State").innerHTML = "No phone found. You can still test on the <b>practice phone</b>."; }
  const apk = A && A.apk, p = A && A.product;
  const phoneOn = online.length > 0;
  const chosen = !!(apk && apk.package);
  if (chosen) {
    $("s2").className = "step ok";
    const engine = p && p.engine && p.engine !== "unknown" ? " · " + esc(p.engine) : "";
    $("s2State").innerHTML = `<span class="big">${esc(apk.installed_only ? prettyName(apk.package) : (apk.name || apk.package))}</span>
      <div style="font-size:12.5px;color:var(--muted)">${esc(apk.package)}</div>
      <span class="tag ${p && p.kind === "game" ? "game" : "app"}">${p ? (p.kind === "game" ? "Game" : "App") : ""}${engine}</span>
      <span class="tag">version ${esc(apk.version || "?")}</span>
      <span class="tag">${apk.installed_only ? "📱 already on the phone" : "📦 from a file"}</span>`;
  } else {
    $("s2").className = "step todo";
    $("s2State").textContent = phoneOn ? "Pick a game from your phone, or add an .apk file." : "Add a game .apk file – or connect a phone to pick a game that is on it.";
  }
  $("removeGame").hidden = !chosen;
  $("phonePick").hidden = chosen || !phoneOn;
  $("apkDrop").hidden = chosen;
  $("optInstallBox").hidden = !(chosen && !apk.installed_only && phoneOn);
  if (phoneOn && !chosen && !appsLoaded) loadApps();
  if (!phoneOn) appsLoaded = false;
  if (A && A.doc) { $("s3").className = "step ok"; $("s3State").innerHTML = `<span class="big">${esc(A.doc)}</span> – ${caseCount()} checks made from it.`; }
  else { $("s3").className = "step"; $("s3State").textContent = "No requirements file (that's OK)."; }
  $("removeDoc").hidden = !(A && A.doc);
  $("docDrop").hidden = !!(A && A.doc);
  renderCasesStep();
  renderGo();
}
function caseCount() { const s = (A && A.suite && A.suite.statuses) || {}; return Object.values(s).reduce((a, b) => a + b, 0); }
let whereChoice = null;  // null = follow the phone; otherwise what the tester clicked
function currentWhere(online) { return whereChoice || (online ? "phone" : "practice"); }
function renderGo() {
  const online = devices.some((d) => d.state === "device");
  const hasApk = !!(A && A.apk && A.apk.package);
  const running = A && A.status === "running";
  const paused = A && A.paused;
  const what = currentWhat(), c = A && A.cases, guide = A && A.guide;
  const guided = what === "guided", where = guided ? "phone" : currentWhere(online);
  document.querySelectorAll('input[name="where"]').forEach((r) => { r.checked = r.value === where; r.disabled = running || !!paused || guided; });
  $("wPhone").classList.toggle("on", where === "phone"); $("wPractice").classList.toggle("on", where === "practice");
  $("wPhone").classList.toggle("off", !online || running); $("wPractice").classList.toggle("off", running || guided);
  $("wPhoneSub").textContent = online ? `The real game on your ${(devices.find((d) => d.state === "device") || {}).model || "phone"}` : "No phone connected right now";
  $("startBtn").hidden = running; $("stopBtn").hidden = !running;
  if (!running) { $("stopBtn").disabled = false; $("stopBtn").textContent = "■ Stop now"; }
  $("overBtn").hidden = !(running || (A && (A.status === "done" || A.status === "error" || A.review)));
  let why = "", can = true;
  document.querySelectorAll('input[name="what"]').forEach((r) => { r.checked = r.value === what; r.disabled = running || !!paused; });
  $("wExplore").classList.toggle("on", what === "explore"); $("wCases").classList.toggle("on", what === "cases");
  $("wCases").classList.toggle("off", !hasCases() || running); $("wExplore").classList.toggle("off", running);
  $("wCasesSub").textContent = hasCases() ? `${c.cases.length} test case(s) from ${c.name}` + (A.ai && A.ai.enabled ? " – the AI player does the steps, you help when asked." : " – you do the steps, the tester watches and records.") : "Upload a test-case file in step 3 first.";
  $("wGuided").hidden = !guide;
  $("wGuided").classList.toggle("on", guided);
  $("wGuided").classList.toggle("off", running);
  $("guidePlan").hidden = !guided;
  if (guided) {
    const steps = guide.cases.map((item) => `<li><b>${esc(item.title)}</b><small>${item.steps.map(esc).join(" ")}</small><small>Expected result · ${esc(item.expected)}</small></li>`).join("");
    if ($("guidePlanSteps").dataset.content !== steps) {
      $("guidePlanSteps").innerHTML = steps;
      $("guidePlanSteps").dataset.content = steps;
    }
  }
  const length = $("testLength"), presets = (A && A.presets) || {};
  $("testLengthPicker").hidden = what !== "explore" || !A || !A.presets;
  if (!length.options.length && A && A.presets) {
    length.innerHTML = Object.entries(presets).map(([id, steps]) => `<option value="${esc(id)}">${esc(id[0].toUpperCase() + id.slice(1))} · ${steps} steps</option>`).join("");
  }
  if (!savingPreset && A && A.autoqa.preset) length.value = A.autoqa.preset;
  length.disabled = running || !!paused || savingPreset;
  $("testLengthHint").textContent = {
    quick: "Quick build check with the first two phone checks.",
    standard: "Covers a full cycle of the six scheduled phone checks.",
    extended: "Longer stability testing with repeated phone checks.",
  }[length.value] || "";
  const aiEnabled = aiInfo ? aiInfo.enabled : !!(A && A.ai && A.ai.enabled);
  $("gameplayObjective").hidden = what !== "explore" || !aiEnabled;
  $("objectiveInput").disabled = running || !!paused;
  if (A) {
    const packageName = (A.apk && A.apk.package) || "";
    if (objectivePackage !== null && packageName !== objectivePackage) $("objectiveInput").value = "";
    objectivePackage = packageName;
  }
  $("firstCustomerObjective").hidden = !(guide && guide.objective);
  $("firstCustomerObjective").disabled = running || !!paused;
  const nextSection = paused && paused.next_section ? (A.progress.section || 1) + 1 : 0;
  const finishing = paused && paused.step >= A.progress.total;
  $("startBtn").textContent = nextSection ? `▶ Start section ${nextSection}` : finishing ? "Finish report" : paused ? "▶ Resume testing" : guided ? "▶ Start walkthrough" : what === "cases" ? "▶ Run my test cases" : "▶ Start testing";
  if (running) why = A.mode === "cases" ? "“Stop now” ends the case run and keeps the result so far." : "“Stop now” pauses exploration after the current action. “Start over” clears the current run from this view.";
  else if (paused) {
    can = canResume(paused);
    const nextStep = paused.step + 1;
    if (!can) why = `Reconnect the same phone to continue at step ${nextStep}.`;
    else if (finishing) why = "The saved run has reached its last step. Finish the report from the recorded results.";
    else if (paused.stuck) why = `Move past the blocked screen, then resume at step ${nextStep}.`;
    else if (nextSection) why = `Section complete. The next section starts at step ${nextStep}.`;
    else if (paused.restored) why = `Saved run restored. ${paused.serial ? "Open the game on the same phone, then resume" : "Resume"} at step ${nextStep}.`;
    else if (paused.reason === "section_time_limit") why = `This section reached its time limit. Resume at step ${nextStep}.`;
    else why = `Ready to resume at step ${nextStep}.`;
  }
  else if (guided) {
    can = online;
    why = can ? "Keep this page open for instructions and confirm the expected result after each step." : "Connect the phone with the Unity game to start the walkthrough.";
  }
  else if (what === "cases" && where === "practice") why = `Will run your ${c.cases.length} test case(s) on the practice game – good to see how it works.`;
  else if (what === "cases" && online && hasApk) why = `Will run your ${c.cases.length} test case(s) on ${prettyName(A.apk.package)}. Keep this page open – it will ask you when it needs help.`;
  else if (where === "practice") why = "Will test the built-in practice game. Nothing on your phone is touched.";
  else if (!online) { why = "👉 Connect your phone (step 1), or choose Practice phone."; can = false; }
  else if (!hasApk) { why = "👉 Choose which game to test (step 2)."; can = false; }
  else if (A.apk.installed_only) why = `Will test ${prettyName(A.apk.package)} on your phone, exactly as it is installed.`;
  else why = `Will test on your phone. ${plan && plan.install === false ? "Uses the version already on the phone." : "Installs your game file first."}`;
  if (!running && !paused && can && what === "explore" && presets[length.value] > 100) why += " The tester pauses after each 100-step section.";
  $("startBtn").disabled = running || !can || resumingTest || savingPreset;
  $("goWhy").textContent = why;
  renderSectionPrompt(paused);
}
function canResume(paused) {
  return paused.step >= A.progress.total || !paused.serial || devices.some((d) => d.serial === paused.serial && d.state === "device");
}
function renderSectionPrompt(paused) {
  const dialog = $("sectionPrompt");
  if (!paused || (!paused.next_section && !paused.stuck)) {
    if (dialog.open) dialog.close();
    return;
  }
  const section = A.progress.section || 1, next = section + 1;
  const ready = canResume(paused);
  const stuck = paused.stuck;
  $("sectionPromptTitle").textContent = stuck ? "Exploration needs help" : `Section ${section} complete`;
  if (!ready) $("sectionPromptText").textContent = `Reconnect the same phone to continue at step ${paused.step + 1}.`;
  else if (stuck) {
    const help = paused.serial ? "Move past this screen on your phone, then resume." : "Resume to try another set of moves on the practice game.";
    $("sectionPromptText").textContent = `The game stayed on the same screen after ${stuck.attempts} inputs. ${help}`;
  } else $("sectionPromptText").textContent = `Continue to section ${next} at step ${paused.step + 1}?`;
  $("stuckEvidence").hidden = !stuck;
  $("sectionContinue").textContent = resumingTest ? "Continuing…" : stuck ? "Resume exploration" : `Continue to section ${next}`;
  $("sectionContinue").disabled = resumingTest || !ready;
  const key = `${paused.run}:${paused.step}:${paused.reason}`;
  if (dialog.dataset.key !== key) {
    dialog.dataset.key = key;
    $("sectionPromptError").hidden = true;
    if (stuck) {
      $("stuckActions").innerHTML = stuck.actions.map((action) => `<li>${esc(action)}</li>`).join("");
      const shot = $("stuckShot");
      shot.hidden = !stuck.screenshot;
      if (stuck.screenshot) shot.src = `/api/frame?i=latest&t=${encodeURIComponent(key)}`;
    }
    if (!dialog.open) dialog.showModal();
  }
}
async function resumePausedTest(paused) {
  if (!paused || resumingTest || !canResume(paused)) return;
  const dialog = $("sectionPrompt"), error = $("sectionPromptError");
  resumingTest = true;
  error.hidden = true;
  renderGo();
  try {
    await J("/api/run/resume", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({run: paused.run, step: paused.step})});
    if (dialog.open) dialog.close();
    toast(paused.next_section ? "Started the next section" : "Resumed the paused test");
    await pollAll();
  } catch (e) {
    if (dialog.open) { error.textContent = e.message; error.hidden = false; }
    else toast(e.message);
  } finally { resumingTest = false; renderGo(); }
}
$("sectionLater").onclick = () => $("sectionPrompt").close();
$("sectionContinue").onclick = () => resumePausedTest(A && A.paused);
$("firstCustomerObjective").onclick = () => {
  if (!A || !A.guide || !A.guide.objective) return;
  $("objectiveInput").value = A.guide.objective;
  $("objectiveInput").focus();
};
$("testLength").onchange = async () => {
  const preset = $("testLength").value;
  savingPreset = true;
  renderGo();
  try {
    const settings = await J("/api/autoqa", {method: "POST", body: JSON.stringify({preset})});
    if (A) A.autoqa.preset = settings.preset;
  } catch (e) { toast(e.message); }
  finally { savingPreset = false; renderGo(); }
};
document.querySelectorAll('input[name="where"]').forEach((r) => r.onchange = () => {
  const online = devices.some((d) => d.state === "device");
  if (r.value === "phone" && !online) { toast("No phone connected – plug in your phone first"); renderGo(); return; }
  whereChoice = r.value; renderGo();
});
function pick(dropId, fileId, handler) {
  const drop = $(dropId), file = $(fileId);
  drop.onclick = () => file.click();
  file.onchange = () => file.files[0] && handler(file.files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); e.dataTransfer.files[0] && handler(e.dataTransfer.files[0]); };
}
async function send(url, file, what) {
  toast(`Uploading ${what}…`);
  const r = await fetch(url, {method: "POST", headers: {"X-Filename": file.name, "Content-Type": "application/octet-stream"}, body: file});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || "upload failed");
  return j;
}
pick("apkDrop", "apkFile", async (f) => {
  if (!f.name.toLowerCase().endsWith(".apk")) { toast("That is not an .apk file. Please choose the game's .apk file."); return; }
  try { await send("/api/upload", f, "game file"); toast("Game file added ✔"); await pollAll(); } catch (e) { toast("Could not add the file: " + e.message); }
});
pick("docDrop", "docFile", async (f) => {
  try { await send("/api/requirements", f, "requirements"); toast("Requirements added ✔"); await pollAll(); } catch (e) { toast("Could not read the file: " + e.message); }
});
$("refreshPhone").onclick = () => { loadDevices(true); toast("Looking for phones…"); };

// ---------- pick a game that is already on the phone ----------
let appsLoaded = false;
function prettyName(pkg) {
  const words = String(pkg || "").split(".").slice(1).filter((w) => !["com", "game", "games", "app", "android", "mobile"].includes(w));
  return words.slice(-3).map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ") || pkg;
}
let allApps = [];
async function loadApps() {
  appsLoaded = true;
  $("appList").innerHTML = "<div class=\"empty\">Loading the phone's games…</div>";
  try {
    const r = await J("/api/phone/apps");
    allApps = r.apps;
    if (!allApps.length) { $("appList").innerHTML = `<div class="empty">${esc(r.hint || "No downloaded games found")}</div>`; return; }
    drawApps();
  } catch (e) { appsLoaded = false; $("appList").innerHTML = `<div class="empty">Could not read the phone: ${esc(e.message)}</div>`; }
}
function hi(text, q) {
  const t = esc(text); if (!q) return t;
  const i = text.toLowerCase().indexOf(q); if (i < 0) return t;
  return esc(text.slice(0, i)) + "<mark>" + esc(text.slice(i, i + q.length)) + "</mark>" + esc(text.slice(i + q.length));
}
function drawApps() {
  const q = $("appSearch").value.trim().toLowerCase();
  const words = q.split(/\s+/).filter(Boolean);
  const match = (a) => words.every((w) => (a.label + " " + a.package).toLowerCase().includes(w));
  const list = allApps.filter(match);
  const games = list.filter((a) => a.kind === "game"), apps = list.filter((a) => a.kind !== "game");
  const row = (a) => `<button class="app" data-pkg="${esc(a.package)}"><b>${hi(a.label, words[0])}</b><small>${hi(a.package, words[0])}</small></button>`;
  $("appList").innerHTML = (games.length ? `<div class="grp">🎮 Games (${games.length})</div>${games.map(row).join("")}` : "") +
    (apps.length ? `<div class="grp">📱 Other apps (${apps.length})</div>${apps.map(row).join("")}` : "") ||
    `<div class="empty">No game matches “${esc(q)}”. Check the spelling, or press ↻ to reload.</div>`;
}
async function chooseGame(pkg) {
  try { toast("Checking " + prettyName(pkg) + " on the phone…"); await J("/api/phone/choose", {method: "POST", body: JSON.stringify({package: pkg})});
    toast(prettyName(pkg) + " chosen ✔ – press Start testing"); $("appSearch").value = ""; await loadPlan(); await pollAll(); }
  catch (e) { toast(e.message); }
}
$("appSearch").oninput = drawApps;
$("appSearch").onkeydown = (e) => { if (e.key === "Enter") { const first = $("appList").querySelector(".app"); if (first) chooseGame(first.dataset.pkg); } };
$("appList").onclick = (e) => { const b = e.target.closest(".app"); if (b) chooseGame(b.dataset.pkg); };
$("appRefresh").onclick = () => loadApps();
$("useOpen").onclick = async () => {
  const btn = $("useOpen"); btn.disabled = true; btn.textContent = "Looking at the phone screen…";
  try {
    const r = await J("/api/phone/current");
    if (!r.package) toast("📲 " + (r.hint || "Open the game on the phone first"));
    else await chooseGame(r.package);
  } catch (e) { toast(e.message); }
  finally { btn.disabled = false; btn.textContent = "📲 Use the game that is open on my phone"; }
};
$("removeGame").onclick = async () => {
  try { await J("/api/apk/clear", {method: "POST"}); toast("Game removed"); appsLoaded = false; await pollAll(); } catch (e) { toast(e.message); }
};

// ---------- options ----------
async function loadPlan() { try { plan = (await J("/api/state")).plan; $("optInstall").checked = plan.install !== false; } catch (e) {} }
$("optInstall").onchange = async () => {
  try { const s = await J("/api/state"); const p = s.plan; p.install = $("optInstall").checked;
    await J("/api/plan", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(p)}); plan = p; renderGo();
    toast(p.install ? "Will install your game file first" : "Will test the version already on the phone");
  } catch (e) { toast(e.message); }
};
$("optAuto").onchange = () => J("/api/autoqa", {method: "POST", body: JSON.stringify({enabled: $("optAuto").checked})})
  .then(() => toast($("optAuto").checked ? "Testing will start by itself when you plug in a phone" : "Automatic start is off"));
$("optSpec").onchange = () => J("/api/autoqa", {method: "POST", body: JSON.stringify({use_spec: $("optSpec").checked})});

$("startBtn").onclick = async () => {
  if (A && A.paused) return resumePausedTest(A.paused);
  try {
    $("startBtn").disabled = true;
    const what = currentWhat(), guided = what === "guided";
    const where = guided ? "phone" : currentWhere(devices.some((d) => d.state === "device"));
    if (what === "cases" || guided) await J("/api/cases/run", {method: "POST", body: JSON.stringify({where, guided})});
    else {
      const objective = $("gameplayObjective").hidden ? "" : $("objectiveInput").value.trim();
      await J("/api/autoqa/run", {method: "POST", body: JSON.stringify({where, preset: $("testLength").value, objective})});
    }
    shownRun = ""; feed = []; renderResult(null);
    toast(guided ? "Walkthrough started on your phone" : where === "practice" ? "Testing started on the practice phone" : "Testing started on your phone");
    await pollAll();
  } catch (e) { toast(e.message.length > 200 ? e.message.slice(0, 200) + "…" : e.message); renderGo(); }
};
$("stopBtn").onclick = async () => {
  try { $("stopBtn").disabled = true; $("stopBtn").textContent = "Stopping…";
    await J("/api/stop", {method: "POST"}); toast("Stopping – the result so far will be shown");
  } catch (e) { toast(e.message); }
};
$("overBtn").onclick = async () => {
  if (A && A.status === "running" && !confirm("Stop the running test and clear the screen?")) return;
  try { $("overBtn").disabled = true; $("overBtn").textContent = "Starting over…";
    await J("/api/start-over", {method: "POST"});
    shownRun = ""; shown = null; feed = []; lastSeq = 0; renderResult(null); $("feed").innerHTML = "";
    toast("Ready for a new test"); await pollAll(); loadRuns();
  } catch (e) { toast(e.message); }
  finally { $("overBtn").disabled = false; $("overBtn").textContent = "↻ Start over"; }
};
$("removeDoc").onclick = async () => {
  try { await J("/api/requirements/clear", {method: "POST"}); await J("/api/cases/clear", {method: "POST"}); whatChoice = null;
    toast("File removed"); await pollAll(); } catch (e) { toast(e.message); }
};

// ---------- live ----------
const PHASE = {preparing: "Getting ready", installing: "Installing the game on the phone", launching: "Opening the game",
  startup: "Measuring how fast the game opens", "phone-lost": "📵 The phone stopped answering – check the USB cable", "using-installed": "Using the newer version already on the phone", running: "Playing the game", reporting: "Writing the report", done: "Finished"};
const STEP_PAGE_SIZE = 400;
const STEP_ACTION_NAMES = {tap: "Tap", long_press: "Press and hold", swipe: "Swipe", wait: "Wait", key: "Press key", back: "Go back", home: "Go to Home", text: "Enter text"};
let renderedStepList = "";
function renderRunSteps(total, step, running) {
  const range = $("runStepRange"), list = $("runStepList");
  const progress = A.progress || {}, schedule = progress.schedule || {};
  const size = progress.section_size || STEP_PAGE_SIZE, section = progress.section || 1;
  const rangeKey = `${total}/${size}/${section}`;
  if (range.dataset.key !== rangeKey) {
    range.dataset.key = rangeKey;
    range.innerHTML = Array.from({length: Math.ceil(total / size)}, (_, page) => {
      const first = page * size + 1, last = Math.min(first + size - 1, total);
      const title = progress.section_size ? `Section ${page + 1} · ` : "";
      return `<option value="${first}">${title}Steps ${first}–${last}</option>`;
    }).join("");
    range.value = String((section - 1) * size + 1);
    range.hidden = total <= size;
    list.scrollTop = 0;
  }
  const first = Number(range.value) || 1, last = Math.min(first + size - 1, total);
  const every = schedule.interrupt_every, checks = schedule.interruptions || [];
  const actions = A.step_actions || {}, results = A.step_interruptions || {};
  const observing = progress.policy === "observe", pending = running || A.paused;
  $("runStepHint").textContent = observing ? "The tester watches while you play." : "The tester chooses each move from the game screen and monitors crashes, freezes and performance as it plays.";
  const checkpoint = (number) => every > 0 && checks.length && number % every === 0;
  const rows = [];
  if (first === 1 && schedule.startup_runs > 0) {
    rows.push(`<li><span class="step-number">Before 1</span><span>Measure cold and warm launch times (${esc(schedule.startup_runs)} runs)</span></li>`);
  }
  for (let number = first; number <= last;) {
    const action = actions[number], scheduled = checkpoint(number);
    const unreached = number > step;
    let end = number, check = "";
    if (!action && !scheduled) {
      while (end < last && (end + 1 > step) === unreached && !actions[end + 1] && !checkpoint(end + 1)) end++;
    }
    if (scheduled) {
      const kind = checks[(number / every - 1) % checks.length], result = results[number];
      const status = result ? (result.skipped ? "Skipped" : result.alive ? "Passed" : "Game closed")
        : number < step || (!pending && number === step) ? "No result recorded" : pending ? "Scheduled" : "Not reached";
      check = `<span class="step-check">After step ${number} · ${esc((INT_PLAIN[kind] || [kind])[0])} · ${status}</span>`;
    }
    const label = action ? action.replace(/^\w+/, (name) => STEP_ACTION_NAMES[name] || name)
      : !unreached ? "No action recorded" : !pending ? "Not reached" : observing ? "Watch gameplay" : "Explore the game and choose moves live";
    const current = running && number === step && action ? ' aria-current="step"' : "";
    rows.push(`<li${action ? "" : ' class="pending"'}${current}><span class="step-number">${number === end ? number : `${number}–${end}`}</span><span>${esc(label)}${check}</span></li>`);
    number = end + 1;
  }
  const html = rows.join("");
  if (renderedStepList === html) return;
  list.innerHTML = html;
  renderedStepList = html;
}
$("runStepRange").onchange = () => {
  const progress = A.progress || {};
  renderRunSteps(progress.total || 1, progress.step || 0, A.status === "running");
  $("runStepList").scrollTop = 0;
};
function renderLive() {
  const running = A.status === "running";
  const pr = A.progress || {}, total = pr.total || 1, step = pr.step || 0;
  const section = pr.section || 1, size = pr.section_size && total > pr.section_size ? pr.section_size : 0;
  const exploration = A.mode !== "cases";
  const objective = exploration ? pr.gameplay_objective : "";
  $("liveObjective").hidden = !objective;
  $("liveObjective").textContent = objective ? `Objective · ${objective}` : "";
  const showLastRun = exploration && (A.status === "done" || A.status === "error" && step > 0);
  $("liveRun").hidden = !(running || showLastRun); $("liveIdle").hidden = running || showLastRun;
  $("runSteps").hidden = !exploration;
  $("liveTitle").textContent = running ? "Testing now…" : "Live view";
  $("liveSub").textContent = running
    ? "The tester is playing your game. It also presses Home, rotates the screen, turns off the internet and more – just like real users do."
    : "Watch the test while it runs, or look at the phone's log at any time.";
  const st = $("status");
  st.className = "status " + (running ? "running" : A.status === "error" ? "error" : A.status === "done" ? "done" : "");
  st.querySelector("b").textContent = running ? "Testing…" : A.paused ? "Test paused" : A.status === "error" ? "Last test could not run – see below" : A.status === "done" ? "Test finished" : "Ready";
  renderError();
  if (!running && !showLastRun) return;
  const sectionStart = size ? (section - 1) * size : 0;
  const sectionTotal = size ? Math.min(size, total - sectionStart) : total;
  const sectionStep = Math.max(0, step - sectionStart);
  $("bar").style.width = Math.min(100, 100 * sectionStep / sectionTotal) + "%";
  const phase = String(pr.phase || "");
  $("nowText").textContent = A.paused && A.paused.next_section ? `Section ${section} complete` : A.paused ? "Exploration paused" : !running ? "Exploration ended" : phase.startsWith("interrupt:") ? "Real-life test: " + (INT_PLAIN[phase.slice(10)] || [phase])[0] : (PHASE[phase] || "Playing the game");
  const left = running && step > 3 && pr.elapsed ? Math.max(0, Math.round((pr.elapsed / step) * (total - step) / 60)) : null;
  $("nowSub").textContent = size ? `Section ${section} of ${Math.ceil(total / size)} · ${sectionStep} of ${sectionTotal} steps · ${step} of ${total} overall`
    : running ? `Step ${step} of ${total}` + (left !== null ? ` · about ${left} min left (or less)` : "") : `${step} of ${total} steps reached`;
  if (exploration) {
    if (running && lastStatus !== "running" && step === 0) {
      $("runStepRange").selectedIndex = 0;
      $("runStepList").scrollTop = 0;
    }
    renderRunSteps(total, step, running);
  }
  const phone = $("phone"), live = $("liveRun");
  const img = phone.querySelector("img") || Object.assign(document.createElement("img"), {alt: "phone screen"});
  if (!running && img.getAttribute("src") && lastStatus !== "running") return;
  if (!img.parentNode) { phone.innerHTML = ""; phone.appendChild(img); }
  img.onload = () => {
    const {naturalWidth: width, naturalHeight: height} = img;
    phone.style.aspectRatio = `${width} / ${height}`;
    live.classList.toggle("landscape", width > height);
  };
  img.onerror = () => {
    phone.innerHTML = "<span>Waiting for the first picture…</span>";
    phone.style.aspectRatio = "";
    live.classList.remove("landscape");
  };
  img.src = "/api/frame?i=latest&t=" + Date.now();
}
function explainError(raw) {
  const t = String(raw || "");
  if (/VERSION_DOWNGRADE/.test(t)) return ["Your phone already has a newer version of this game than the file you added.",
    "Nothing to do – the tester now uses the newer version on the phone automatically. Press Start testing again. To test your file instead, add the newer .apk."];
  if (/UPDATE_INCOMPATIBLE/.test(t)) return ["The game on the phone was made with a different signing key than your file.",
    "Press Start testing again – the tester will use the version already on the phone. To test your file, uninstall the game from the phone first (this deletes its saved progress)."];
  if (/not found|offline|no devices|device .* not found/i.test(t)) return ["The phone was disconnected during the test.",
    "Check the USB cable (try another cable or port), keep the phone unlocked and plugged in, then press Start testing again."];
  if (/unauthorized/i.test(t)) return ["The phone has not allowed this computer yet.", "Look at the phone, tap Allow, then press Start testing again."];
  if (/INSUFFICIENT_STORAGE/.test(t)) return ["The phone is full.", "Free some space on the phone, then press Start testing again."];
  if (/input|INJECT_EVENTS|SecurityException/i.test(t)) return ["The phone is blocking taps from the computer.",
    "On Xiaomi/Realme/Oppo phones also turn on “USB debugging (Security settings)” or “Disable permission monitoring” in Developer options."];
  return ["The test stopped because of an unexpected problem.", "Press Start testing to try again. If it happens again, send the technical message below to the developer."];
}
function renderError() {
  const show = A.status === "error" && A.error;
  $("errCard").hidden = !show;
  if (!show) return;
  const [plain, fix] = explainError(A.error);
  $("errPlain").textContent = plain; $("errFix").innerHTML = "<b>What to do:</b> " + esc(fix); $("errRaw").textContent = A.error;
}
function friendlyEvent(e) {
  let m = e.msg;
  if (/^phase:/.test(m)) return null;
  if (/FINDING java_crash|FINDING native_crash/.test(m)) return ["bad", "💥 The game crashed – recorded, reopening it."];
  if (/FINDING anr/.test(m)) return ["bad", "🧊 The game froze – recorded."];
  if (/not alive - relaunching/.test(m)) return null;
  let r = /step (\d+): interrupt:(\w+) → (.*)/.exec(m);
  if (r) { const p = INT_PLAIN[r[2]] || [r[2]]; return [/APP DIED/.test(m) ? "bad" : "", `${/APP DIED/.test(m) ? "❌" : "✔"} ${p[0]}${/APP DIED/.test(m) ? " – the game did NOT survive" : " – OK"}`]; }
  if (/^QA REVIEW/.test(m)) return [e.level === "error" ? "bad" : e.level === "warn" ? "warn" : "", "📋 Test finished – see the result below."];
  if (/^\s+(plan|\[S|lifecycle|spec cases|start-up)/.test(m)) return null;
  if (/^AUTO QA/.test(m)) return ["", "▶ Test started."];
  if (/^section complete at step /.test(m)) return ["", "✔ " + m.replace(/^section/, "Section") + ". Waiting for you to start the next one."];
  if (/^test resumed at step /.test(m)) return ["", "▶ " + m.replace(/^test/, "Test") + "."];
  if (/^phone .*: device/.test(m)) return ["", "📱 Phone connected."];
  if (/phone disconnected/.test(m)) return ["warn", "📱 Phone was unplugged."];
  if (/unauthorized/.test(m)) return ["warn", "📱 Tap “Allow” on the phone screen."];
  if (/newer version|NEWER version/.test(m)) return ["warn", "ℹ️ The phone has a newer version of this game. Untick “Install my game file” to test that one."];
  if (/run failed/.test(m)) return ["bad", "⚠️ " + m.replace(/^run failed: \w+: /, "").slice(0, 200)];
  if (/^COMPARE/.test(m)) return ["", "🔁 Compared with the last version."];
  if (/stopped answering/.test(m)) return ["bad", "📵 The phone stopped answering – check the USB cable. Waiting 20 seconds…"];
  if (/PHONE DISCONNECTED/.test(m)) return ["warn", "📵 The phone disconnected. Reconnect the same phone to continue."];
  if (/STOP pressed/.test(m)) return ["warn", "■ Stopping…"];
  if (/test stopped by you/.test(m)) return ["warn", /resume testing/.test(m) ? "■ Test paused. Press Resume testing to continue." : "■ Test stopped. The result covers what ran."];
  if (/^started over/.test(m)) return ["", "↻ Ready for a new test."];
  return null;
}
async function pollEvents() {
  try {
    const r = await J("/api/events?since=" + lastSeq);
    lastSeq = r.last;
    r.events.forEach((e) => { const f = friendlyEvent(e); if (f) feed.push([e.ts, f[0], f[1]]); });
    feed = feed.slice(-200);
    $("feed").innerHTML = feed.slice().reverse().map((f) => `<div class="${f[1]}"><span class="t">${f[0]}</span>${esc(f[2])}</div>`).join("") || '<div class="empty">Nothing yet.</div>';
  } catch (e) {}
}

// ---------- result ----------
function renderResult(r, label) {
  if (!r) { $("resultCard").hidden = true; $("detailCard").hidden = true; return; }
  shown = r;
  $("resultCard").hidden = false; $("detailCard").hidden = false;
  if (r.kind === "test_cases") { renderCaseResult(r, label); return; }
  $("facts").style.display = "";
  const decision = r.checklist && r.checklist.ended_early ? "INCOMPLETE" : r.decision;
  $("resultTitle").textContent = decision === "INCOMPLETE" ? "Results so far" : label.title;
  $("resultSub").textContent = label.sub;
  const v = VERDICT[decision] || VERDICT["CONDITIONAL"];
  const counts = {serious: 0, medium: 0, small: 0};
  (r.issues || []).forEach((i) => counts[LEVEL(i.severity)[0]]++);
  $("verdict").className = "verdict " + decision;
  $("verdict").innerHTML = `<div class="icon">${v.icon}</div><div><div class="head">${v.head}</div>
    <div class="why">${esc(v.tip || r.decision_reason)} Found <b>${counts.serious}</b> serious, <b>${counts.medium}</b> medium and <b>${counts.small}</b> small problem(s).</div></div>`;
  const m = r.metrics || {};
  const fact = (cls, big, small) => `<div class="fact ${cls}"><b>${big}</b><span>${small}</span></div>`;
  const life = (r.interruptions || []).filter((e) => !e.skipped);
  const lifeBad = life.filter((e) => !e.survived).length;
  $("facts").innerHTML = [
    fact(counts.serious ? "bad" : "good", counts.serious ? counts.serious : "0", "serious problems"),
    fact(m.avg_fps >= 45 ? "good" : m.avg_fps >= 30 ? "warn" : m.avg_fps ? "bad" : "", m.avg_fps ? Math.round(m.avg_fps) + " fps" : "–", "smoothness (higher is better, 60 is perfect)"),
    fact(m.cold_start_ms && m.cold_start_ms < 3000 ? "good" : m.cold_start_ms ? "warn" : "", m.cold_start_ms ? (m.cold_start_ms / 1000).toFixed(1) + " s" : "–", "time to open the game"),
    fact(life.length ? (lifeBad ? "bad" : "good") : "", life.length ? `${life.length - lifeBad} / ${life.length}` : "–", "real-life tests passed"),
    fact("", m.screens_explored ?? "–", "different screens visited"),
    fact("", m.duration_s ? Math.round(m.duration_s / 60) + " min" : "–", "testing time"),
  ].join("");
  const runId = label.run || "";
  const recordings = (label.artifacts || []).filter((name) => /^session(?:-part-\d+)?\.mp4$/.test(name));
  if (!recordings.length && (label.artifacts || []).includes("session.gif")) recordings.push("session.gif");
  $("actions").innerHTML = runId ? `
    <a href="/api/runs/artifact?run=${encodeURIComponent(runId)}&name=report.html" target="_blank"><button>📄 Open full report</button></a>
    <a href="/api/runs/artifact?run=${encodeURIComponent(runId)}&name=qa_review.md" target="_blank"><button>📝 Bug list for developers</button></a>
    ${recordings.map((name, index) => `<a href="/api/runs/artifact?run=${encodeURIComponent(runId)}&name=${name}" target="_blank"><button>🎬 ${recordings.length > 1 ? `Recording part ${index + 1}` : "Watch the recording"}</button></a>`).join("")}` : "";
  renderEnd(r); renderBoard(r);
  renderProblems(r); renderLife(r); renderSpeed(r); renderChecks(r); renderCompare(r, runId);
}
function renderProblems(r) {
  const list = r.issues || [];
  $("p-problems").innerHTML = `<div class="explain">Each problem has a simple explanation. Developers can open <b>“Details for the developer”</b> to see how to repeat it and the likely cause.</div>` +
    (list.map((i) => { const [cls, name] = LEVEL(i.severity); return `<div class="prob ${cls}">
      <div class="lvl">${name}</div>
      <div class="what">${esc(KIND_PLAIN[i.kind] || "Problem found.")}</div>
      <div class="plain">${esc(plainTitle(i))}${i.step ? ` · happened at step ${i.step}` : ""}</div>
      <details><summary>Details for the developer</summary>
        <div style="margin-top:6px"><b>Likely cause:</b> ${esc(i.cause)} – ${esc(i.advice)}</div>
        ${i.repro && i.repro.length ? `<div style="margin-top:6px"><b>How to repeat it:</b><ol>${i.repro.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>` : ""}
        ${i.stack && i.stack.length ? `<pre>${esc(i.stack.join("\n"))}</pre>` : ""}
      </details></div>`; }).join("") || '<div class="empty">🎉 No problems found.</div>');
}
function renderLife(r) {
  const by = {};
  (r.interruptions || []).forEach((e) => { const k = by[e.kind] = by[e.kind] || {ok: 0, bad: 0, skip: 0, note: ""};
    if (e.skipped) k.skip++; else if (e.survived) k.ok++; else { k.bad++; k.note = e.finding || e.detail; } });
  const rows = Object.keys(INT_PLAIN).filter((k) => by[k]).map((k) => { const b = by[k], p = INT_PLAIN[k];
    const res = b.bad ? '<span class="pill bad">Failed</span>' : b.ok ? '<span class="pill good">Passed</span>' : '<span class="pill none">Not possible on this phone</span>';
    return `<tr><td><b>${p[0]}</b><br><span style="color:var(--muted);font-size:13px">${p[1]}</span></td><td>${res}</td>
      <td>${b.ok + b.bad ? `${b.ok} of ${b.ok + b.bad} times OK` : ""}${b.note ? `<br><span style="color:var(--red);font-size:13px">${esc(b.note)}</span>` : ""}</td></tr>`; }).join("");
  const notRun = Object.keys(INT_PLAIN).filter((k) => !by[k]).map((k) => INT_PLAIN[k][0]);
  $("p-life").innerHTML = `<div class="explain">Real people get phone calls, rotate the phone, lose internet and switch apps. These tests check the game survives all of that.</div>` +
    (rows ? `<table><thead><tr><th>What happened</th><th>Result</th><th>Details</th></tr></thead><tbody>${rows}</tbody></table>` : '<div class="empty">These tests did not run in this session.</div>') +
    (rows && notRun.length ? `<p style="color:var(--muted);font-size:14px">Not reached in this session (it ended first): ${notRun.join(", ")}. Run a longer test to include them.</p>` : "");
}
function spark(series, color) {
  if (!series || series.length < 2) return '<div class="empty">Not measured</div>';
  const xs = series.map((p) => p[0]), ys = series.map((p) => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys), W = 300, H = 70;
  const sx = (x) => (x1 > x0 ? (x - x0) / (x1 - x0) : 0) * (W - 4) + 2, sy = (y) => H - 4 - (y1 > y0 ? (y - y0) / (y1 - y0) : .5) * (H - 8);
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="width:100%;height:${H}px;display:block"><path d="${series.map((p, i) => (i ? "L" : "M") + sx(p[0]).toFixed(1) + " " + sy(p[1]).toFixed(1)).join(" ")}" fill="none" stroke="${color}" stroke-width="2"/></svg>
    <small>lowest ${Math.round(y0).toLocaleString()} · highest ${Math.round(y1).toLocaleString()}</small>`;
}
function renderSpeed(r) {
  const m = r.metrics || {}, p = r.perf || {};
  const row = (name, value, good, plain) => `<tr><td><b>${name}</b><br><span style="color:var(--muted);font-size:13px">${plain}</span></td><td style="white-space:nowrap">${value}</td><td>${good === null ? '<span class="pill none">–</span>' : good ? '<span class="pill good">Good</span>' : '<span class="pill warn">Needs work</span>'}</td></tr>`;
  const kb = (v) => v ? (v / 1024).toFixed(0) + " MB" : "–";
  const grow = m.mem_growth_kb_per_min;
  $("p-speed").innerHTML = `<div class="explain">How fast and smooth the game is, and how hard it works the phone.</div>
    <table><thead><tr><th>What</th><th>Measured</th><th>Verdict</th></tr></thead><tbody>
    ${row("Time to open (first time)", m.cold_start_ms ? (m.cold_start_ms / 1000).toFixed(2) + " s" : "–", m.cold_start_ms ? m.cold_start_ms < 5000 : null, "From tapping the icon until the game shows. Under 5 s is good for games.")}
    ${row("Time to open (again)", m.warm_start_ms ? (m.warm_start_ms / 1000).toFixed(2) + " s" : "–", m.warm_start_ms ? m.warm_start_ms < 1500 : null, "Coming back when the game was already open.")}
    ${row("Smoothness", m.avg_fps ? Math.round(m.avg_fps) + " fps" : "–", m.avg_fps ? m.avg_fps >= 30 : null, "Pictures per second. 60 is perfect, under 30 feels laggy.")}
    ${row("Worst moment", m.min_fps ? Math.round(m.min_fps) + " fps" : "–", m.min_fps ? m.min_fps >= 15 : null, "The slowest point during the test – a short stutter.")}
    ${row("Memory used", kb(m.peak_pss_kb), m.peak_pss_kb ? m.peak_pss_kb < 1500000 : null, "Too much memory makes cheap phones close the game.")}
    ${row("Memory leak", grow === null || grow === undefined ? "Test too short to tell" : (grow > 0 ? "+" : "") + Math.round(grow / 1024) + " MB per minute", grow === null || grow === undefined ? null : grow < 20000, "Memory that keeps growing means the game will slow down and close after a while.")}
    ${row("Phone work (CPU)", m.avg_cpu_percent ? Math.round(m.avg_cpu_percent) + "% average" : "–", m.avg_cpu_percent ? m.avg_cpu_percent < 60 : null, "High numbers drain the battery faster.")}
    ${row("Phone temperature", m.max_battery_temp_c ? m.max_battery_temp_c + " °C" : "–", m.max_battery_temp_c ? m.max_battery_temp_c < 43 : null, "Above 43 °C the phone gets hot in the hand.")}
    </tbody></table>
    <div class="grid2"><div class="chart"><b>Smoothness over time</b>${spark(p.fps_series, "#2563eb")}</div>
      <div class="chart"><b>Memory over time</b>${spark(p.pss_series, "#a15c00")}</div>
      <div class="chart"><b>Phone work over time</b>${spark(p.cpu_series, "#15803d")}</div></div>`;
}
function renderChecks(r) {
  const cases = r.cases || [];
  const label = {PASS: '<span class="pill good">Passed</span>', FAIL: '<span class="pill bad">Failed</span>', NOT_VERIFIED: '<span class="pill warn">Not sure</span>', MANUAL: '<span class="pill none">A person must check</span>'};
  $("p-checks").innerHTML = cases.length ? `<div class="explain">Checks made from your requirements file. Some things (prices, rewards, story) need a person to check by hand.</div>
    <table><thead><tr><th>Check</th><th>Result</th><th>Why</th></tr></thead><tbody>${cases.map((c) => `<tr><td>${esc(c.title)}</td><td>${label[c.auto_status] || esc(c.auto_status)}</td><td style="color:var(--muted);font-size:14px">${esc(c.reason)}</td></tr>`).join("")}</tbody></table>`
    : '<div class="empty">Add a requirements file (step 3) to get checks made from it.</div>';
}
async function renderCompare(r, runId) {
  const box = $("p-compare");
  if (r.checklist && r.checklist.ended_early) {
    box.innerHTML = '<div class="empty">Build comparisons are available for completed runs with matching coverage.</div>';
    return;
  }
  box.innerHTML = '<div class="explain">Is this version better or worse than the one you tested before?</div><div class="empty">Loading…</div>';
  if (!runId) { box.lastChild.textContent = "Open a past test to compare it."; return; }
  try {
    const c = await J(`/api/runs/compare?new=${encodeURIComponent(runId)}`);
    const st = {worse: '<span class="pill bad">Worse</span>', better: '<span class="pill good">Better</span>', same: '<span class="pill none">Same</span>'};
    const rows = c.rows.filter((x) => x.base !== null && x.new !== null).map((x) => `<tr><td>${esc(x.label)}</td><td>${num(x.base)}</td><td>${num(x.new)}</td><td>${st[x.status]}</td></tr>`).join("");
    box.innerHTML = `<div class="explain">Comparing with the earlier test of version <b>${esc(c.base.version || "?")}</b> (${esc(c.base.id.slice(0, 8))}).</div>
      <div style="font-size:17px;margin-bottom:10px">${c.new_crashes.length ? `❌ <b>${c.new_crashes.length} new crash type(s)</b>` : "✅ No new crashes"}
        · ${c.fixed_crashes.length ? `✅ <b>${c.fixed_crashes.length} fixed</b>` : "nothing fixed"}
        · ${c.regressions.filter((x) => x.metric !== "crash").length} thing(s) got worse · ${c.improvements.length} got better</div>
      <table><thead><tr><th>What</th><th>Before</th><th>Now</th><th>Change</th></tr></thead><tbody>${rows}</tbody></table>`;
  } catch (e) { box.innerHTML = `<div class="explain">Is this version better or worse than the one you tested before?</div><div class="empty">${esc(e.message === "no earlier run of this package to compare with" ? "This is the first test of this game on this kind of phone – nothing to compare with yet." : e.message)}</div>`; }
}
document.querySelectorAll("#tabs button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("on", p.id === "p-" + b.dataset.p));
  if (b.dataset.p === "log") loadLog();
});

// ---------- technical log ----------
async function loadLog() {
  try { const r = shownRun ? await J(`/api/runs/log?run=${encodeURIComponent(shownRun)}&tail=2000`) : await J("/api/live-log?tail=1500"); logLines = r.lines || []; drawLog(); } catch (e) {}
}
function lv(l) { const m = /\s([VDIWEF])[\/ ]/.exec(l); return m ? m[1] : "I"; }
function drawLog() {
  const f = $("logLvl").value, q = $("logQ").value.toLowerCase();
  const keep = (x) => !f || (f === "E" ? "EF".includes(x) : "EFW".includes(x));
  $("log").innerHTML = logLines.filter((l) => keep(lv(l)) && (!q || l.toLowerCase().includes(q))).map((l) => `<div class="${lv(l)}">${esc(l)}</div>`).join("") || "No log lines.";
}
$("logLvl").onchange = drawLog; $("logQ").oninput = drawLog;

// ---------- history ----------
// ---------- how far the test got + checklist board ----------
const ST = {passed: ["✅", "Passed"], failed: ["❌", "Failed"], not_run: ["⏳", "Not tested"], partial: ["◐", "Partly done"],
  skipped: ["⏭", "Skipped"], manual: ["👤", "A person must check"]};
let boardFilter = "all";
function renderEnd(r) {
  const c = r.checklist; if (!c) { $("endbar").innerHTML = ""; $("endbar").className = "endbar"; return; }
  const lost = c.end_reason === "phone_lost", early = c.ended_early;
  const pending = c.resumable;
  const icon = lost ? "📵" : c.end_reason === "stopped" ? "■" : early ? "⏱" : "🏁";
  $("endbar").className = "endbar" + (lost ? " lost" : early ? " early" : "");
  $("endbar").innerHTML = `<div class="row1"><span>${icon} ${esc(c.end_text)}</span><span>${c.steps_run} of ${c.steps_planned} steps · ${c.percent}% done</span></div>
    <div class="bar"><i style="width:${Math.min(100, c.percent)}%"></i></div>
    ${pending ? `<small>The remaining steps and checks stay pending until you continue.</small>` : early ? `<small>See the checklist for checks that were unfinished or outside this run’s coverage.</small>` : ""}`;
}
function renderBoard(r) {
  const c = r.checklist; if (!c) { $("board").innerHTML = ""; return; }
  const n = c.counts;
  const chip = (key, cls, label, count) => `<button class="chip ${cls} ${boardFilter === key ? "on" : ""}" data-f="${key}">${label} ${count}</button>`;
  const keep = (it) => boardFilter === "all" || (boardFilter === "not" ? ["not_run", "partial"].includes(it.status) : boardFilter === "manual" ? ["manual", "skipped"].includes(it.status) : it.status === boardFilter);
  const groups = {};
  c.items.filter(keep).forEach((it) => (groups[it.group] = groups[it.group] || []).push(it));
  const body = Object.entries(groups).map(([g, list]) => `<div class="cgroup"><h4>${esc(g)}</h4>${list.map((it) => {
    const s = c.resumable && it.status === "not_run" ? ["⏳", "Pending"] : ST[it.status] || ["•", it.status];
    return `<div class="citem"><span class="ic">${s[0]}</span><span><div class="nm">${esc(it.name)}</div><div class="dt">${esc(it.detail)}</div></span><span class="st ${it.status}">${s[1]}</span></div>`; }).join("")}</div>`).join("")
    || '<div class="empty">Nothing in this group.</div>';
  $("board").innerHTML = `<h3>Test checklist</h3><p class="sub">Everything this test was meant to check. Click a box to show only those items.</p>
    <div class="chips">${chip("all", "", "All", c.items.length)}${chip("passed", "c-passed", "✅ Passed", n.passed)}${chip("failed", "c-failed", "❌ Failed", n.failed)}
    ${chip("not", "c-not", c.resumable ? "⏳ Pending / partly done" : "⏳ Not tested / partly done", n.not_tested)}${n.manual + n.skipped ? chip("manual", "", "👤 Needs a person / skipped", n.manual + n.skipped) : ""}</div>${body}`;
}
$("board").onclick = (e) => { const b = e.target.closest(".chip"); if (!b || !shown) return; boardFilter = b.dataset.f; renderBoard(shown); };

// ---------- games ----------
let gameFilter = "";
const selectedRuns = new Set();
let deletingRuns = false;
function visibleRuns() { return runs.filter((run) => !gameFilter || run.package === gameFilter); }
function renderRunSelection() {
  const available = visibleRuns().filter((run) => run.deletable);
  const count = available.filter((run) => selectedRuns.has(run.id)).length;
  const selectAll = $("selectAllRuns"), button = $("deleteRuns");
  selectAll.disabled = deletingRuns || available.length === 0;
  selectAll.checked = count > 0 && count === available.length;
  selectAll.indeterminate = count > 0 && count < available.length;
  button.disabled = deletingRuns || count === 0;
  button.textContent = deletingRuns ? "Deleting…" : count ? `Delete ${count} selected ${count === 1 ? "test" : "tests"}` : "Delete selected tests";
  $("history").querySelectorAll("input[data-select-run]").forEach((box) => {
    box.checked = selectedRuns.has(box.dataset.selectRun);
    box.disabled = deletingRuns || box.dataset.deletable !== "true";
  });
}
async function loadGames() {
  let data; try { data = await J("/api/games"); } catch (e) { return; }
  const word = {pass: "Passed", warn: "Release with care", fail: "Not ready", unfinished: "Not finished"};
  const pill = {pass: "good", warn: "warn", fail: "bad", unfinished: "none"};
  $("games").innerHTML = data.games.map((g) => { const last = g.last || {};
    return `<button class="gcard ${gameFilter === g.package ? "on" : ""}" data-pkg="${esc(g.package)}">
      <div><div class="gn">${g.practice ? "🧪 Practice game" : "🎮 " + esc(prettyName(g.package))}</div><div class="gp">${esc(g.package)}</div></div>
      <div><span class="pill ${pill[last.verdict] || "none"}">Last: ${word[last.verdict] || "–"}</span></div>
      <div class="trend">History: ${g.trend.map((t) => `<i class="${t}" title="${word[t]}"></i>`).join("")}</div>
      <div class="gs"><span><b>${g.tests}</b> test${g.tests === 1 ? "" : "s"}</span><span><b>${g.crash_types}</b> crash type${g.crash_types === 1 ? "" : "s"}</span>${g.avg_fps ? `<span><b>${Math.round(g.avg_fps)}</b> fps</span>` : ""}</div>
      <div class="gs">Last test ${esc(last.when || "")} · ${esc(last.on || "")}${last.version ? " · v" + esc(last.version) : ""}</div>
    </button>`; }).join("") || '<div class="empty">No games tested yet. Run your first test above.</div>';
}
$("games").onclick = async (e) => {
  const b = e.target.closest(".gcard"); if (!b) return;
  gameFilter = gameFilter === b.dataset.pkg ? "" : b.dataset.pkg;
  selectedRuns.clear();
  loadGames(); await loadRuns();
  if (gameFilter) {
    $("histTitle").scrollIntoView({behavior: "smooth", block: "start"});
    const first = runs.find((r) => r.package === gameFilter);
    if (first) openRunById(first.id);
  }
};

async function loadRuns() {
  try { runs = (await J("/api/runs")).runs; } catch (e) { return; }
  const visible = visibleRuns();
  const available = new Set(visible.filter((run) => run.deletable).map((run) => run.id));
  for (const id of selectedRuns) if (!available.has(id)) selectedRuns.delete(id);
  const vmap = {pass: ['good', "Passed"], warn: ['warn', "Warnings"], fail: ['bad', "Failed"], incomplete: ['none', "Results so far"]};
  $("histTitle").textContent = gameFilter ? "Tests of " + prettyName(gameFilter) : "Past tests";
  $("histSub").innerHTML = gameFilter ? `Only this game. <a href="#" id="showAll">Show all games</a>` : "Every test you ran. Click one to see its result above.";
  if ($("showAll")) $("showAll").onclick = (e) => { e.preventDefault(); gameFilter = ""; selectedRuns.clear(); loadGames(); loadRuns(); };
  $("history").innerHTML = visible.map((r) => { const v = vmap[r.verdict] || ['none', "Not finished"];
    const selectLabel = `Select ${r.package} test from ${r.when || r.id}`;
    return `<tr class="click ${r.id === shownRun ? "sel" : ""}" data-run="${esc(r.id)}"><td class="history-select"><input type="checkbox" data-select-run="${esc(r.id)}" data-deletable="${r.deletable === true}" aria-label="${esc(selectLabel)}"></td><td>${esc(r.when || r.id)}</td>
      <td><span class="pill ${v[0]}">${v[1]}</span></td><td>${esc(r.package)}</td>
      <td>${r.unique_crashes ? `${r.unique_crashes} crash/freeze` : "–"}</td><td>${r.target === "simulator" ? "Practice phone" : "Real phone"}</td></tr>`; }).join("")
    || '<tr><td colspan="6" class="empty">No saved tests here.</td></tr>';
  renderRunSelection();
}
$("history").onclick = (ev) => {
  if (ev.target.closest(".history-select")) return;
  const tr = ev.target.closest("tr[data-run]"); if (tr) openRunById(tr.dataset.run, true);
};
$("history").onchange = (ev) => {
  const box = ev.target.closest("input[data-select-run]");
  if (!box) return;
  if (box.checked) selectedRuns.add(box.dataset.selectRun);
  else selectedRuns.delete(box.dataset.selectRun);
  renderRunSelection();
};
$("selectAllRuns").onchange = (ev) => {
  selectedRuns.clear();
  if (ev.target.checked) visibleRuns().filter((run) => run.deletable).forEach((run) => selectedRuns.add(run.id));
  renderRunSelection();
};
$("deleteRuns").onclick = async () => {
  const selection = visibleRuns().filter((run) => run.deletable && selectedRuns.has(run.id));
  if (!selection.length || deletingRuns) return;
  const name = selection.length === 1 ? `the ${prettyName(selection[0].package)} test from ${selection[0].when || selection[0].id}`
    : `${selection.length} selected tests${gameFilter ? ` for ${prettyName(gameFilter)}` : ""}`;
  if (!confirm(`Permanently delete ${name}? This removes the saved screenshots, recordings, logs, and reports.`)) return;
  deletingRuns = true;
  renderRunSelection();
  try {
    const result = await J("/api/runs/delete", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({runs: selection.map((run) => run.id)})});
    result.deleted.forEach((id) => selectedRuns.delete(id));
    if (result.deleted.includes(shownRun) || (!shownRun && result.deleted.length)) {
      shownRun = ""; shown = null; renderResult(null);
    }
    const deleted = result.deleted.length;
    toast(result.errors.length ? `Deleted ${deleted}. ${result.errors[0].error}` : deleted ? `Deleted ${deleted} saved ${deleted === 1 ? "test" : "tests"}.` : "The selected tests are already gone.");
  } catch (e) { toast(e.message); }
  finally {
    deletingRuns = false;
    await Promise.all([loadRuns(), loadGames(), pollAll()]);
    renderRunSelection();
  }
};
async function openRunById(id, scroll) {
  shownRun = id; boardFilter = "all"; loadRuns();
  try {
    const r = await J(`/api/runs/review?run=${encodeURIComponent(shownRun)}`);
    const run = runs.find((x) => x.id === shownRun) || {};
    renderResult(r, {title: "Result of test " + (run.when || shownRun), sub: `${run.package || ""} · ${run.target === "simulator" ? "practice phone" : "real phone"}`, run: shownRun, artifacts: run.artifacts});
    if (scroll) $("resultCard").scrollIntoView({behavior: "smooth"});
  } catch (e) { toast(e.message); }
}

// ---------- test cases (step 3) ----------
let whatChoice = null, inputTimer = null;
function hasCases() { return !!(A && A.cases && A.cases.cases && A.cases.cases.length); }
function currentWhat() {
  if (whatChoice && (whatChoice !== "guided" || (A && A.guide))) return whatChoice;
  return hasCases() ? "cases" : "explore";
}
function renderCasesStep() {
  const c = A && A.cases;
  $("casesBox").hidden = !hasCases();
  if (!hasCases()) return;
  $("s3").className = "step ok";
  $("s3State").innerHTML = `<span class="big">📋 ${esc(c.name)}</span> – <b>${c.cases.length}</b> test case${c.cases.length === 1 ? "" : "s"}` +
    (c.missing_inputs.length ? `<br><span style="color:var(--muted);font-size:13.5px">Optional inputs left empty: ${c.missing_inputs.map(esc).join(", ")}</span>` : "");
  $("removeDoc").hidden = false; $("docDrop").hidden = true;
  const box = $("inputsBox");
  if (!box.contains(document.activeElement)) {
    box.innerHTML = c.required_inputs.length ? `<div style="font-size:13px;font-weight:700;color:var(--muted);margin:6px 0 2px">TEST INPUTS</div>` +
      c.required_inputs.map((n) => `<label class="inp"><span>${esc(n)}</span><input data-in="${esc(n)}" value="${esc(c.inputs[n] || "")}" placeholder="optional"></label>`).join("") : "";
  }
  $("caseSum").textContent = `Show the ${c.cases.length} test cases`;
  $("caseList").innerHTML = c.cases.map((k) => `<li><b>${esc(k.id)}</b> ${esc(k.title)} ${k.mode === "human" ? '<span class="tag">👤 person</span>' : ""}
    <br><small>${k.steps.length} step(s) · expected: ${esc(k.expected || "– (you will judge)")}</small></li>`).join("");
}
$("inputsBox").oninput = (e) => {
  const el = e.target.closest("input[data-in]"); if (!el) return;
  clearTimeout(inputTimer);
  inputTimer = setTimeout(async () => {
    const vals = {}; $("inputsBox").querySelectorAll("input[data-in]").forEach((i) => vals[i.dataset.in] = i.value);
    try { await J("/api/cases/inputs", {method: "POST", body: JSON.stringify(vals)}); pollAll(); } catch (err) { toast(err.message); }
  }, 500);
};
$("mdHelp").onclick = (e) => { e.preventDefault(); openHelp("cases"); };
document.querySelectorAll('input[name="what"]').forEach((r) => r.onchange = () => {
  if (r.value === "cases" && !hasCases()) { toast("Upload a test-case file in step 3 first"); renderGo(); return; }
  whatChoice = r.value; renderGo();
});

// ---------- AI player settings ----------
let aiInfo = null;
async function loadAI() {
  try { aiInfo = await J("/api/ai"); } catch (e) { return; }
  const sel = $("aiProvider");
  if (!sel.options.length) sel.innerHTML = Object.entries(aiInfo.providers).map(([k, v]) => `<option value="${k}">${esc(v.label)}</option>`).join("");
  sel.value = aiInfo.provider; $("aiOn").checked = aiInfo.enabled;
  if (document.activeElement !== $("aiModel")) $("aiModel").value = aiInfo.model;
  if (document.activeElement !== $("aiUrl")) $("aiUrl").value = aiInfo.base_url;
  $("aiKey").placeholder = aiInfo.has_key ? "•••••• key saved for this session" : "paste your key (kept only in memory)";
  drawAI();
}
function drawAI() {
  const p = aiInfo && aiInfo.providers[$("aiProvider").value] || {};
  $("aiKeyBox").hidden = !p.needs_key;
  $("aiLocalHelp").hidden = $("aiProvider").value !== "ollama"; $("aiCloudHelp").hidden = !p.needs_key;
  const on = aiInfo && aiInfo.enabled;
  $("aiTag").textContent = on ? "on · " + aiInfo.model : "off"; $("aiTag").classList.toggle("on", !!on);
  $("aiHint").textContent = on ? "The tester reads the screen and does test steps by itself; it asks you only when it cannot."
    : "Optional – lets the tester read the screen, do test steps and judge results by itself.";
}
async function saveAI(extra) {
  const body = Object.assign({provider: $("aiProvider").value, model: $("aiModel").value, base_url: $("aiUrl").value, enabled: $("aiOn").checked}, extra || {});
  if ($("aiKey").value) body.api_key = $("aiKey").value;
  aiInfo = await J("/api/ai", {method: "POST", body: JSON.stringify(body)}); $("aiKey").value = "";
  await loadAI(); renderGo();
}
$("aiProvider").onchange = () => { $("aiModel").value = ""; $("aiUrl").value = ""; saveAI(); };
$("aiOn").onchange = () => saveAI().then(() => toast($("aiOn").checked ? "AI player on" : "AI player off – you will do the steps, the tester watches"));
$("aiSave").onclick = () => saveAI().then(() => toast("AI settings saved"));
$("aiTest").onclick = async () => {
  $("aiResult").className = "aires"; $("aiResult").textContent = "Testing…";
  try { await saveAI(); const r = await J("/api/ai/test", {method: "POST"});
    $("aiResult").className = "aires " + (r.ok ? "ok" : "bad"); $("aiResult").textContent = (r.ok ? "✅ " : "❌ ") + r.message;
  } catch (e) { $("aiResult").className = "aires bad"; $("aiResult").textContent = "❌ " + e.message; }
};

// ---------- "your help is needed" ----------
let askShown = "", baseTitle = document.title;
function renderAsk() {
  const q = A && A.question;
  $("askCard").hidden = !q;
  if (!q) { askShown = ""; document.title = baseTitle; return; }
  const secs = Math.max(0, Math.round(Date.now() / 1000 - q.asked_at));
  $("askTimer").textContent = `waiting ${secs < 60 ? secs + " s" : Math.floor(secs / 60) + " min"}`;
  document.title = (secs % 2 ? "🙋 " : "") + "Help needed – " + baseTitle;
  if (askShown === q.id) return;
  askShown = q.id; $("askNote").value = "";
  $("askTitle").textContent = q.title;
  $("askText").textContent = q.text;
  const label = {Done: "✔ Done", Failed: "✖ Failed", Skip: "⏭ Skip this step", Passed: "✔ Passed", "Not sure": "? Not sure"};
  $("askBtns").innerHTML = q.options.map((o) => `<button class="b-${o.replace(/\s/g, "")}" data-a="${esc(o)}">${label[o] || esc(o)}</button>`).join("");
  $("askCard").scrollIntoView({behavior: "smooth", block: "center"});
  toast("🙋 The tester needs your help");
}
$("askBtns").onclick = async (e) => {
  const b = e.target.closest("button[data-a]"); if (!b || !A.question) return;
  try { await J("/api/question/answer", {method: "POST", body: JSON.stringify({id: A.question.id, answer: b.dataset.a, note: $("askNote").value})});
    $("askCard").hidden = true; askShown = ""; toast("Thanks – continuing"); pollAll();
  } catch (err) { toast(err.message); }
};

// ---------- test cases while running + result ----------
const VIC = {PASSED: "✅", FAILED: "❌", "NOT PASSED": "⚠️"};
function renderCaseLive() {
  const live = A.status === "running" && A.mode === "cases";
  $("caseLive").hidden = !live;
  if (!live) return;
  const cr = A.case_run || {}, done = {};
  (cr.results || []).forEach((r) => done[r.id] = r);
  const doc = cr.guided ? A.guide : A.cases;
  const all = (doc && doc.cases) || [];
  $("caseLive").innerHTML = all.map((k) => { const r = done[k.id];
    const icon = r ? VIC[r.status] : (k.id === cr.current ? "▶" : "⏳");
    return `<div class="${k.id === cr.current ? "cur" : ""}"><span>${icon}</span><span><b>${esc(k.id)}</b> ${esc(k.title)}${r ? ` – <span class="vst ${r.status.split(" ")[0]}">${r.status}</span>` : ""}</span></div>`; }).join("");
  $("nowText").textContent = cr.current ? `Test case ${cr.current} · step ${cr.step || 1}` : "Running your test cases";
  $("nowSub").textContent = `${cr.done || 0} of ${cr.total || all.length} done · ${cr.phase || ""}` + (cr.ai ? " · AI player on" : " · you do the steps");
  $("bar").style.width = (cr.total ? 100 * (cr.done || 0) / cr.total : 0) + "%";
}
function renderCaseResult(r, label) {
  const s = r.summary || {}, runId = label.run || r.run || "";
  $("resultTitle").textContent = label.title; $("resultSub").textContent = label.sub || "";
  $("detailCard").hidden = true; $("board").innerHTML = ""; $("endbar").className = "endbar";
  $("endbar").innerHTML = s.stopped_by_user ? "■ Stopped by you – cases not reached are marked Not passed" :
    s.device_lost ? "📵 The phone disconnected – the remaining cases are marked Not passed" : `🏁 All ${s.cases_total} test cases were run` +
    (s.ai ? ` · AI player: ${esc(s.ai.model)}` : " · steps done by you");
  const verdict = s.failed ? "NO-GO" : s.not_passed ? "CONDITIONAL" : "GO";
  const head = {GO: ["✅", "All test cases passed"], CONDITIONAL: ["⚠️", "Some test cases could not be completed"], "NO-GO": ["❌", "Some test cases failed"]}[verdict];
  $("verdict").className = "verdict " + verdict;
  $("verdict").innerHTML = `<div class="icon">${head[0]}</div><div><div class="head">${head[1]}</div><div class="why">${s.passed} passed, ${s.failed} failed, ${s.not_passed} not passed – out of ${s.cases_total}.</div></div>`;
  $("facts").innerHTML = `<div class="cres" style="grid-column:1/-1"><div class="p"><b>${s.passed}</b>✅ Passed</div><div class="f"><b>${s.failed}</b>❌ Failed</div><div class="n"><b>${s.not_passed}</b>⚠️ Not passed</div></div>`;
  $("facts").style.display = "block";
  const art = (n) => `/api/runs/artifact?run=${encodeURIComponent(runId)}&name=${n}`;
  $("actions").innerHTML = runId ? `<a href="${art("report.html")}" target="_blank"><button>📄 Open the report</button></a>` : "";
  $("board").innerHTML = `<h3>Every test case</h3><p class="sub">The result, why, and who decided (AI, you, or the crash detector).</p>
    <div style="overflow-x:auto"><table class="ctable"><thead><tr><th>Test case</th><th>Result</th><th>Why</th><th>Screen</th></tr></thead><tbody>` +
    (r.results || []).map((c) => `<tr><td><b>${esc(c.id)}</b><br>${esc(c.title)}<br><small style="color:var(--muted)">expected: ${esc(c.expected || "–")}</small></td>
      <td><span class="vst ${c.status.split(" ")[0]}">${VIC[c.status] || ""} ${c.status}</span></td>
      <td>${esc(c.reason)}<br><small style="color:var(--muted)">decided by ${esc(c.decided_by || "–")}${c.note ? " · note: " + esc(c.note) : ""}${c.seconds ? " · " + c.seconds + " s" : ""}</small>
        ${(c.steps || []).length ? `<details><summary style="cursor:pointer;color:var(--blue)">steps</summary><ol style="margin:4px 0;padding-left:18px">${c.steps.map((st) => `<li>${esc(st.text)} – <i>${esc(st.outcome || "")}</i>${st.by ? " (" + esc(st.by) + ")" : ""}</li>`).join("")}</ol></details>` : ""}</td>
      <td>${c.screenshot && runId ? `<a href="${art(encodeURIComponent(c.screenshot))}" target="_blank"><img src="${art(encodeURIComponent(c.screenshot))}" alt="screen"></a>` : ""}</td></tr>`).join("") + "</tbody></table></div>";
}

// ---------- live tabs + phone log (logcat) ----------
let lcLines = [], lcPaused = false, lcBusy = false, lcLastText = "";
document.querySelectorAll("#liveTabs button").forEach((b) => b.onclick = () => {
  document.querySelectorAll("#liveTabs button").forEach((x) => x.classList.toggle("on", x === b));
  document.querySelectorAll(".lpane").forEach((p) => p.classList.toggle("on", p.id === "l-" + b.dataset.l));
  if (b.dataset.l === "logcat") loadLogcat(true);
});
function lcLevelOf(line) { const m = /^\S+\s+\S+\s+\d+\s+\d+\s+([VDIWEF])\s/.exec(line) || /\s([VDIWEF])[\/ ]/.exec(line); return m ? m[1] : "I"; }
async function loadLogcat(force) {
  if (lcBusy || (lcPaused && !force)) return;
  if (!force && !$("l-logcat").classList.contains("on")) return;
  lcBusy = true;
  try {
    const r = await J(`/api/live-log?tail=1500&game=${$("lcGame").checked ? 1 : 0}`);
    lcLines = r.lines || [];
    const src = r.source === "test" ? "from the running test" : r.source === "phone" ? "live from your phone" : "";
    $("lcHint").textContent = r.hint ? "ℹ️ " + r.hint : `Showing the newest ${lcLines.length} lines ${src}. Red = error · orange = warning · grey = details.`;
    drawLogcat();
  } catch (e) { $("lcHint").textContent = "Could not read the log: " + e.message; }
  finally { lcBusy = false; }
}
function visibleLogcat() {
  const lvl = $("lcLevel").value, q = $("lcSearch").value.trim().toLowerCase();
  return lcLines.filter((l) => { const v = lcLevelOf(l);
    if (lvl === "E" && !"EF".includes(v)) return false;
    if (lvl === "W" && !"EFW".includes(v)) return false;
    return !q || l.toLowerCase().includes(q); });
}
function drawLogcat() {
  const q = $("lcSearch").value.trim(), list = visibleLogcat();
  $("logCnt").textContent = lcLines.length ? `(${list.length})` : "";
  const html = list.map((l) => { let t = esc(l);
    if (q) t = t.split(esc(q)).join(`<mark>${esc(q)}</mark>`);
    return `<div class="${lcLevelOf(l)}">${t}</div>`; }).join("") || `<div class="lt">${lcLines.length ? "No line matches this filter." : "No log lines yet."}</div>`;
  if (html === lcLastText) return;
  lcLastText = html;
  const box = $("lcBox"), atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  box.innerHTML = html;
  if ($("lcFollow").checked && (atEnd || !lcPaused)) box.scrollTop = box.scrollHeight;
}
$("lcLevel").onchange = drawLogcat; $("lcSearch").oninput = drawLogcat;
$("lcGame").onchange = () => loadLogcat(true);
$("lcPause").onclick = () => { lcPaused = !lcPaused; $("lcPause").textContent = lcPaused ? "▶ Resume" : "⏸ Pause"; if (!lcPaused) loadLogcat(true); };
$("lcCopy").onclick = async () => {
  const text = visibleLogcat().join("\n");
  try { await navigator.clipboard.writeText(text); toast(`Copied ${visibleLogcat().length} lines`); }
  catch (e) { toast("Copy is blocked by the browser – use Save instead"); }
};
$("lcSave").onclick = () => {
  const blob = new Blob([visibleLogcat().join("\n")], {type: "text/plain"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = "phone-log-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + ".txt"; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
};
setInterval(() => loadLogcat(false), 2000);

// ---------- guide ----------
function openHelp(tab) {
  $("help").hidden = false; $("helpBack").hidden = false;
  if (tab) showHelpTab(tab);
}
function closeHelp() {
  $("help").hidden = true; $("helpBack").hidden = true;
  try { localStorage.setItem("gt-help-seen", "1"); localStorage.setItem("gt-help-auto", $("helpAgain").checked ? "1" : "0"); } catch (e) {}
}
function showHelpTab(name) {
  document.querySelectorAll("#helpTabs button").forEach((b) => b.classList.toggle("on", b.dataset.h === name));
  document.querySelectorAll(".help-body section").forEach((sec) => sec.classList.toggle("on", sec.dataset.h === name));
  document.querySelector(".help-body").scrollTop = 0;
}
$("helpBtn").onclick = () => openHelp();
$("helpClose").onclick = closeHelp; $("helpDone").onclick = closeHelp; $("helpBack").onclick = closeHelp;
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("help").hidden) closeHelp(); });
document.querySelectorAll("#helpTabs button").forEach((b) => b.onclick = () => showHelpTab(b.dataset.h));
(() => {
  let seen = null, auto = null;
  try { seen = localStorage.getItem("gt-help-seen"); auto = localStorage.getItem("gt-help-auto"); } catch (e) {}
  $("helpAgain").checked = auto === "1";
  const want = new URLSearchParams(location.search).get("help");
  if (want) openHelp(want === "1" ? "quick" : want);
  else if (!seen || auto === "1") openHelp("quick");  // first visit: show the guide once
})();

// ---------- main loop ----------
async function pollAll() {
  try {
    A = await J("/api/autoqa");
    $("optAuto").checked = !!A.autoqa.enabled; $("optSpec").checked = !!A.autoqa.use_spec;
    renderSteps(""); renderLive(); renderCaseLive(); renderAsk();
    if (!shownRun && A.mode === "cases" && A.case_result && shown !== A.case_result) {
      renderResult(Object.assign(A.case_result, {kind: "test_cases"}), {title: A.case_result.guided ? "First-customer walkthrough results" : "Result of your test cases",
        sub: `${(A.apk && A.apk.package) || "practice game"}`, run: A.case_result.run});
    }
    if (lastStatus === "running" && A.status !== "running") { loadRuns(); loadGames(); shownRun = ""; boardFilter = "all"; }
    if (!shownRun && A.review && A.mode !== "cases") {
      const latest = runs[0] || {};
      if (shown !== A.review) renderResult(A.review, {title: "Result of your last test", sub: `${(A.apk && A.apk.package) || ""} · ${A.device && A.device.selected && !String(A.device.selected).startsWith("sim") ? "real phone" : "practice phone"}`, run: latest.id, artifacts: latest.artifacts});
    }
    lastStatus = A.status;
  } catch (e) { $("status").className = "status error"; $("status").querySelector("b").textContent = "Tester is not running – double-click Start Game Tester.bat"; }
}
(async () => {
  await loadPlan(); await loadRuns(); loadGames(); loadAI(); await loadDevices(true); await pollAll(); await pollEvents();
  setInterval(pollAll, 1500); setInterval(pollEvents, 1500); setInterval(() => loadDevices(false), 4000); setInterval(loadRuns, 20000); setInterval(loadGames, 30000);
  setInterval(() => { if (document.querySelector('#tabs button.on')?.dataset.p === "log" && A && A.status === "running") loadLog(); }, 3000);
})();
</script>
</body>
</html>
"""
