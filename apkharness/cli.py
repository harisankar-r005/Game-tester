"""Command line interface: ``python -m apkharness <command>``."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Optional, Sequence

from . import __version__
from .adb import Adb, AdbError, AdbNotFound
from .actions import ActionError
from .apk import ApkError, inspect_apk
from .plan import PlanError, evaluate, parse_plan, summarize
from .policies import POLICIES, load_script
from .report import load_session, write_html, write_junit
from .run import RunConfig, Session

log = logging.getLogger("apkharness")


# -- parsers ---------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apkharness",
        description="Black-box crash, ANR and performance testing for Android game APKs.",
        epilog="Start with `apkharness demo` to see a full report without a device.",
    )
    parser.add_argument("--version", action="version", version=f"apkharness {__version__}")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="more logging (-vv for debug)")
    parser.add_argument("-q", "--quiet", action="store_true", help="only warnings and errors")
    sub = parser.add_subparsers(dest="command", required=True)

    dev = sub.add_parser("devices", help="list connected Android devices")
    dev.add_argument("--adb", default="adb", help="path to the adb executable")
    dev.add_argument("--json", action="store_true", help="machine readable output")

    inspect = sub.add_parser("inspect", help="read package/version/activity from an APK offline")
    inspect.add_argument("apk", help="path to the .apk")
    inspect.add_argument("--json", action="store_true", help="machine readable output")

    run = sub.add_parser("run", help="test an APK on a device")
    run.add_argument("--apk", default="", help="path to the .apk to install and test")
    run.add_argument("--package", default="", help="application id (auto-detected after install)")
    run.add_argument("--activity", default="", help="launch activity, e.g. com.game/.MainActivity")
    run.add_argument("--serial", default="", help="adb device serial (default: first online device)")
    run.add_argument("--adb", default="adb", help="path to the adb executable")
    run.add_argument("--policy", choices=list(POLICIES), default="heuristic", help="exploration policy")
    run.add_argument("--steps", type=int, default=200, help="maximum number of inputs (default 200)")
    run.add_argument("--minutes", type=float, default=0, help="time budget in minutes (overrides --steps when hit)")
    run.add_argument("--out", default="runs", help="output directory root (default ./runs)")
    run.add_argument("--seed", type=int, default=7, help="RNG seed for reproducible exploration")
    run.add_argument("--delay", type=float, default=0.4, help="seconds to wait between inputs")
    run.add_argument("--metrics-every", type=int, default=5, help="sample dumpsys every N steps")
    run.add_argument("--screenshot-every", type=int, default=1, help="save a screenshot every N steps")
    run.add_argument("--ui-every", type=int, default=1, help="dump the accessibility tree every N steps")
    run.add_argument("--novelty-threshold", type=int, default=10, help="perceptual-hash distance for 'new screen'")
    run.add_argument("--no-install", action="store_true", help="the APK is already installed")
    run.add_argument("--no-relaunch", action="store_true", help="stop instead of relaunching after a crash")
    run.add_argument("--max-relaunches", type=int, default=3)
    run.add_argument("--stop-after-crashes", type=int, default=0, help="stop after N distinct crashes")
    run.add_argument("--actions", default="", help="JSON action script (for --policy scripted)")
    run.add_argument("--llm-model", default="", help="model id for --policy llm")
    run.add_argument("--llm-base-url", default="", help="OpenAI-compatible base URL")
    run.add_argument("--llm-vision", action="store_true", help="also send screenshots to the model")
    run.add_argument("--simulate", action="store_true", help="use the built-in simulator instead of adb")
    run.add_argument("--plan", default="", help="JSON test plan: steps, checks, ignore rules")
    run.add_argument("--fail-on-crash", action="store_true", help="exit with status 2 when crashes were found")

    demo = sub.add_parser("demo", help="run the built-in simulator and produce a sample report")
    demo.add_argument("--steps", type=int, default=160)
    demo.add_argument("--out", default="runs", help="output directory root")
    demo.add_argument("--seed", type=int, default=7)
    demo.add_argument("--policy", choices=list(POLICIES), default="heuristic")
    demo.add_argument("--fail-on-crash", action="store_true")

    report = sub.add_parser("report", help="re-render the HTML/JUnit report from a session directory")
    report.add_argument("session", help="run directory containing session.json")
    report.add_argument("--junit", action="store_true", help="also write junit.xml")

    script = sub.add_parser("check-script", help="validate a JSON action script")
    script.add_argument("actions", help="path to the action script")

    serve = sub.add_parser("serve", help="start the QA studio (upload APK, press Test, watch)")
    serve.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    serve.add_argument("--port", type=int, default=8765, help="port (default 8765)")
    serve.add_argument("--workdir", default="studio", help="where uploads, runs and frames are stored")
    serve.add_argument("--adb", default="", help="adb path (auto-detected by default)")
    serve.add_argument("--open", action="store_true", help="open the browser once the server is up")
    return parser


# -- commands --------------------------------------------------------------
def cmd_devices(args: argparse.Namespace) -> int:
    try:
        devices = Adb.list_devices(args.adb)
    except AdbNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except AdbError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([d.to_dict() for d in devices], indent=2))
        return 0
    if not devices:
        print("no devices found - start an emulator or enable USB debugging")
        return 1
    for device in devices:
        marker = "online" if device.online else device.state
        print(f"{device.serial:<24} {marker:<10} {device.model}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .studio import serve

    return serve(
        workdir=args.workdir,
        host=args.host,
        port=args.port,
        adb_path=args.adb,
        open_browser=args.open,
    )


def _config_from_args(args: argparse.Namespace) -> RunConfig:
    time_budget = args.minutes * 60 if getattr(args, "minutes", 0) else 1800.0
    return RunConfig(
        apk=os.path.abspath(args.apk) if args.apk else "",
        package=args.package,
        activity=args.activity,
        serial=args.serial,
        adb_path=args.adb,
        policy=args.policy,
        steps=args.steps,
        time_budget_s=time_budget,
        step_delay_s=args.delay,
        metrics_every=args.metrics_every,
        screenshot_every=args.screenshot_every,
        ui_every=args.ui_every,
        out_root=args.out,
        seed=args.seed,
        novelty_threshold=args.novelty_threshold,
        relaunch_on_crash=not args.no_relaunch,
        max_relaunches=args.max_relaunches,
        stop_after_crashes=args.stop_after_crashes,
        simulate=args.simulate,
        no_install=args.no_install,
        llm_model=args.llm_model,
        llm_base_url=args.llm_base_url,
        llm_vision=args.llm_vision,
        actions_file=args.actions,
    )


def cmd_inspect(args: argparse.Namespace) -> int:
    try:
        info = inspect_apk(args.apk)
    except (ApkError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(info.to_dict(), indent=2))
        return 0
    print(f"package      : {info.package or 'unknown'}")
    print(f"version      : {info.version_name or '?'} ({info.version_code or '?'})")
    print(f"launcher     : {info.launch_activity or 'no launcher activity declared'}")
    print(f"sdk          : min {info.min_sdk or '?'} / target {info.target_sdk or '?'}")
    print(f"abis         : {', '.join(info.abis) or 'none'}")
    print(f"size         : {info.size_bytes / (1024 * 1024):.1f} MB")
    print(f"sha256       : {info.sha256[:32]}...")
    print(f"permissions  : {len(info.permissions)}")
    for permission in info.permissions[:8]:
        print(f"  - {permission}")
    if len(info.permissions) > 8:
        print(f"  ... {len(info.permissions) - 8} more")
    return 0


def _print_summary(result, out_dir: str) -> None:
    summary = result.summary
    print()
    print(f"session   : {out_dir}")
    apk = result.meta.get("apk") or {}
    if apk:
        print(f"app       : {result.meta.get('package', '?')} {apk.get('version_name', '')}".rstrip())
    print(f"policy    : {result.meta.get('policy', '?')}   steps: {summary.get('steps_run')}"
          f"   duration: {summary.get('duration_s')}s")
    print(f"screens   : {summary.get('screens_explored')}   crashes: {summary.get('unique_crashes')}"
          f"   ANRs: {summary.get('anr_count')}")
    fps = summary.get("avg_fps")
    print(f"framerate : avg {fps if fps is not None else 'n/a'} fps"
          f"   min {summary.get('min_fps') if summary.get('min_fps') is not None else 'n/a'}"
          f"   peak mem {summary.get('peak_pss_kb') and round(summary['peak_pss_kb'] / 1024)} MB")
    if result.crashes:
        print("\nfindings:")
        for crash in result.crashes:
            print(f"  - [{crash['kind']}] step {crash['step']}: {crash['message'][:110]}")
    print(f"\nreport    : {os.path.join(out_dir, 'report.html')}")
    print(f"junit     : {os.path.join(out_dir, 'junit.xml')}")


def cmd_run(args: argparse.Namespace) -> int:
    plan = None
    if args.plan:
        try:
            with open(args.plan, "r", encoding="utf-8") as handle:
                plan = parse_plan(handle.read())
        except (OSError, PlanError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        args.policy = plan.policy
        args.steps = plan.steps
        args.minutes = plan.minutes
        args.seed = plan.seed
        args.simulate = args.simulate or plan.target == "simulator"
    if not args.apk and not args.simulate and not (args.no_install and args.package):
        print(
            "error: --apk is required unless the app is already installed "
            "(--no-install --package com.example.game) or the plan targets the simulator",
            file=sys.stderr,
        )
        return 1
    config = _config_from_args(args)
    if plan is not None:
        config.ignore_patterns = list(plan.ignore)
        config.plan = plan.to_dict()
    if config.policy == "scripted" and not config.actions_file:
        print("error: --policy scripted requires --actions <file.json>", file=sys.stderr)
        return 1
    session = Session(config)
    result = session.run()
    _print_summary(result, session.out_dir)

    if plan is not None:
        checks = evaluate(plan, result.summary, result.crashes)
        verdict_name = summarize(checks)["verdict"]
        payload = result.to_dict()
        payload["checks"] = [check.to_dict() for check in checks]
        payload["summary"]["verdict"] = verdict_name
        payload["summary"]["check_summary"] = summarize(checks)
        write_html(payload, session.out_dir)
        write_junit(payload, os.path.join(session.out_dir, "junit.xml"))
        print("\nchecks:")
        for check in checks:
            mark = "PASS" if check.passed else "FAIL"
            print(f"  [{mark}] {check.id}: {check.title} (expected {check.expected}, actual {check.actual})")
        print(f"verdict   : {verdict_name.upper()}")
        if verdict_name == "fail":
            return 2
        return 0

    if args.fail_on_crash and result.crashes:
        return 2
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    config = RunConfig(
        simulate=True,
        package="com.example.neondrift",
        policy=args.policy,
        steps=args.steps,
        out_root=args.out,
        seed=args.seed,
        step_delay_s=0.35,
        label="demo",
    )
    session = Session(config)
    result = session.run()
    _print_summary(result, session.out_dir)

    if plan is not None:
        checks = evaluate(plan, result.summary, result.crashes)
        verdict_name = summarize(checks)["verdict"]
        payload = result.to_dict()
        payload["checks"] = [check.to_dict() for check in checks]
        payload["summary"]["verdict"] = verdict_name
        payload["summary"]["check_summary"] = summarize(checks)
        write_html(payload, session.out_dir)
        write_junit(payload, os.path.join(session.out_dir, "junit.xml"))
        print("\nchecks:")
        for check in checks:
            mark = "PASS" if check.passed else "FAIL"
            print(f"  [{mark}] {check.id}: {check.title} (expected {check.expected}, actual {check.actual})")
        print(f"verdict   : {verdict_name.upper()}")
        if verdict_name == "fail":
            return 2
        return 0

    if args.fail_on_crash and result.crashes:
        return 2
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    if not os.path.exists(args.session):
        print(f"error: no such session: {args.session}", file=sys.stderr)
        return 1
    out_dir = args.session if os.path.isdir(args.session) else os.path.dirname(os.path.abspath(args.session))
    try:
        data = load_session(args.session)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read session.json: {exc}", file=sys.stderr)
        return 1
    html_path = write_html(data, out_dir)
    print(f"wrote {html_path}")
    if args.junit:
        junit = write_junit(data, os.path.join(out_dir, "junit.xml"))
        print(f"wrote {junit}")
    return 0


def cmd_check_script(args: argparse.Namespace) -> int:
    try:
        actions, loop = load_script(args.actions)
    except (OSError, json.JSONDecodeError, ActionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{len(actions)} action(s) valid, loop={loop}")
    for index, action in enumerate(actions[:10], 1):
        print(f"  {index:>3}. {action.label}")
    if len(actions) > 10:
        print(f"  ... {len(actions) - 10} more")
    return 0


# -- entry point -----------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    level = logging.WARNING if args.quiet else (logging.DEBUG if args.verbose > 1 else logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)-7s %(message)s", stream=sys.stderr)
    if args.verbose > 1:
        logging.getLogger("apkharness").setLevel(logging.DEBUG)

    try:
        if args.command == "devices":
            return cmd_devices(args)
        if args.command == "inspect":
            return cmd_inspect(args)
        if args.command == "run":
            return cmd_run(args)
        if args.command == "demo":
            return cmd_demo(args)
        if args.command == "report":
            return cmd_report(args)
        if args.command == "check-script":
            return cmd_check_script(args)
        if args.command == "serve":
            return cmd_serve(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except AdbNotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except AdbError as exc:
        print(f"adb error: {exc}", file=sys.stderr)
        return 1
    except (ValueError, ActionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.error(f"unknown command {args.command}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
