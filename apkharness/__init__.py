"""apkharness - automated black-box testing for Android game APKs.

The harness installs an APK, drives it with a policy (heuristic, LLM-backed or
scripted), watches logcat plus process liveness for crashes/ANRs and turns the
session into a self-contained HTML report.

Pure standard library: no third-party packages are required.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
