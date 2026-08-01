"""Print the estimator's profile comparison for a real path, and score it.

Two modes:

    python tools/estimate_report.py <path> [<path> ...]
        Analyze the inputs and print the four-profile comparison table - the
        same numbers the GUI shows, without needing Qt.

    python tools/estimate_report.py --backtest
        Replay the recorded 2026-08-01 corpus and print predicted vs measured
        for size and time. This is what regenerates the figures in
        docs/benchmarks/2026-08-01-estimator-backtest.md.

The scoring mode is in-sample by construction (those numbers calibrated the
shipped rates), so it is a regression guard. Out-of-sample evidence comes from
running mode one on a corpus, then measuring it with tools/bench.py.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from excmp.analyzer import analyze_tree  # noqa: E402
from excmp.estimate import compare_profiles, estimate_size, estimate_time  # noqa: E402
from excmp.planner import Profile, plan as make_plan  # noqa: E402
from excmp.tools import find_tools  # noqa: E402

BACKTEST_CORPUS = Path(r"C:\Users\nuhaa\Desktop\Downloads-1\PalluVaapaHDD"
                       r"\0No Need To Check\Programs")
BACKTEST_FILES = [
    "R-4.5.1-win.exe",
    "Windows-KB890830-x64-V5.129.exe",
    "lghub_installer.exe",
    "DB.Browser.for.SQLite-v3.13.0-win64.msi",
    "Winxvideo.AI.3.5.0.0.w64.rar",
    "Wondershare UniConverter 15.0.9.15 (x64) pass=123.zip",
]
# Post-B11/D9 run of 2026-08-01 (precomp->sevenzip chain, total includes the
# pre-publish restore+verify gate) - keep in step with tests/test_estimate_backtest.py.
BACKTEST_MEASURED = {Profile.NORMAL: (0.0280, 103.8), Profile.EXTREME: (0.0297, 254.3)}

SIZE_TOLERANCE = 0.10
TIME_TOLERANCE = 0.40
# Precomp chains run at two very different speeds depending on whether Precomp
# finds anything to expand (2.642 vs 0.842 MB/s measured). Same gate as
# tests/test_estimate_backtest.py - keep the two in step.
PRECOMP_TIME_TOLERANCE = 0.80


def mb(n: float) -> str:
    return f"{n / 1e6:,.1f} MB"


def secs(n: float) -> str:
    return f"{n:,.0f}s" if n < 600 else f"{n / 60:,.0f}m"


def show_table(infos, tools) -> None:
    total = sum(i.size for i in infos)
    print(f"\n{len(infos)} files, {mb(total)} in\n")
    head = f"{'profile':<9} {'chain':<26} {'est. size':>12} {'saved':>7} {'est. time':>10}  note"
    print(head)
    print("-" * len(head))
    for row in compare_profiles(infos, tools):
        note = ""
        if row.not_worth_it and row.beaten_by is not None:
            note = (f"{row.time_multiple:.1f}x the time of {row.beaten_by.value} "
                    f"for {row.extra_points:+.2f} points")
        chain = " -> ".join(row.stages) or "(none)"
        print(f"{row.profile.value:<9} {chain:<26} {mb(row.size.expected):>12} "
              f"{row.size.saved_percent:>6.2f}% {secs(row.time.expected):>10}  {note}")
        print(f"{'':<9} {'range':<26} {mb(row.size.low):>12}-{mb(row.size.high):<12} "
              f"{secs(row.time.low)}-{secs(row.time.high)}")


def backtest() -> int:
    missing = [n for n in BACKTEST_FILES if not (BACKTEST_CORPUS / n).is_file()]
    if missing:
        print(f"corpus incomplete, missing: {missing}", file=sys.stderr)
        return 1

    tools = find_tools()
    t0 = time.monotonic()
    infos = [analyze_tree(BACKTEST_CORPUS / n)[0] for n in BACKTEST_FILES]
    analysis_s = time.monotonic() - t0
    total = sum(i.size for i in infos)

    print(f"analyzed {len(infos)} files ({mb(total)}) in {analysis_s:.2f}s "
          f"- {analysis_s / len(infos) * 1000:.0f} ms/file\n")
    print(f"{'file':<46} {'size':>13} {'mean':>7} {'max':>7} {'entropy':>8}")
    for i in infos:
        print(f"{i.path.name[:46]:<46} {i.size:>13,} {i.sample_ratio:>7.4f} "
              f"{i.sample_ratio_max:>7.4f} {i.entropy_bps:>8.2f}")

    print(f"\n{'profile':<9} {'measured':>13} {'predicted':>13} {'err':>8}"
          f" {'meas. time':>11} {'pred. time':>11} {'err':>8}  in range")
    ok = True
    for profile, (saved, seconds) in BACKTEST_MEASURED.items():
        the_plan = make_plan(infos, profile, tools)
        size = estimate_size(infos, the_plan)
        est_time = estimate_time(infos, the_plan)
        measured_bytes = total * (1 - saved)
        s_err = (size.expected - measured_bytes) / measured_bytes
        t_err = (est_time.expected - seconds) / seconds
        in_range = (size.low <= measured_bytes <= size.high
                    and est_time.low <= seconds <= est_time.high)
        stages = next((r.stages for r in the_plan.routes if r.action == "pipeline"), [])
        t_gate = PRECOMP_TIME_TOLERANCE if "precomp" in stages else TIME_TOLERANCE
        ok = ok and abs(s_err) <= SIZE_TOLERANCE and abs(t_err) <= t_gate and in_range
        print(f"{profile.value:<9} {mb(measured_bytes):>13} {mb(size.expected):>13} "
              f"{s_err:>+7.2%} {seconds:>10.1f}s {est_time.expected:>10.1f}s "
              f"{t_err:>+7.2%}  {'yes' if in_range else 'NO'}"
              f"  (gate +/-{t_gate:.0%})")
        print(f"{'':<9} {'':<13} {mb(size.low)}-{mb(size.high)}"
              f"        {est_time.low:.0f}-{est_time.high:.0f}s")

    show_table(infos, tools)
    print("\nGATE:", "pass" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--backtest", action="store_true")
    args = ap.parse_args()

    if args.backtest:
        return backtest()
    if not args.paths:
        ap.error("give one or more paths, or --backtest")

    tools = find_tools()
    t0 = time.monotonic()
    infos: list = []
    for path in args.paths:
        infos.extend(analyze_tree(Path(path)))
    print(f"analysis took {time.monotonic() - t0:.2f}s for {len(infos)} files")
    show_table(infos, tools)
    return 0


if __name__ == "__main__":
    sys.exit(main())
