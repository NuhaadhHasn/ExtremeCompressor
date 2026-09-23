"""Benchmark harness: measure every profile on a sample corpus.

Usage:
    .venv\\Scripts\\python.exe tools\\bench.py <sample_dir> [--profiles fast,normal,extreme]

Compresses <sample_dir> with each profile, verifies extraction, and writes a
markdown results table to docs/benchmarks/. Run it on a real game folder /
video folder / document folder to calibrate profile expectations on this
machine before trusting any preset.
"""

from __future__ import annotations

import argparse
import platform
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from excmp import engine  # noqa: E402
from excmp.analyzer import analyze_tree  # noqa: E402
from excmp.planner import Profile  # noqa: E402
from excmp.sample import DEFAULT_SAMPLE_BYTES, pick_sample  # noqa: E402
from excmp.stages.base import StageContext  # noqa: E402


def fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} GB"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sample_dir")
    ap.add_argument("--profiles", default="fast,normal,extreme")
    # I6: the GUI's "Measure presets" runs on a bounded, representative slice
    # rather than the whole folder. Same selection here, from the same module,
    # so a number quoted in a benchmark doc and a number on a card mean the
    # same thing.
    ap.add_argument("--sample", type=int, nargs="?", const=DEFAULT_SAMPLE_BYTES,
                    default=0, metavar="BYTES",
                    help="measure at most BYTES of the input (default 100 MB "
                         "when the flag is given without a value), chosen by "
                         "excmp.sample.pick_sample")
    args = ap.parse_args()

    sample = Path(args.sample_dir).resolve()
    if not sample.exists():
        print(f"error: {sample} not found", file=sys.stderr)
        return 1
    profiles = [Profile(p.strip()) for p in args.profiles.split(",")]

    inputs: list[Path] = [sample]
    chosen = None
    if args.sample:
        print(f"analysing {sample} to choose a <= {fmt_size(args.sample)} "
              f"sample ...", flush=True)
        chosen = pick_sample(analyze_tree(sample), cap_bytes=args.sample)
        inputs = [f.path for f in chosen.files]
        print(f"  {len(chosen.files)} of {chosen.source_files} files, "
              f"{fmt_size(chosen.total_bytes)} of "
              f"{fmt_size(chosen.source_bytes)} ({chosen.fraction:.1%})")
        # No silent caps: say what the sample could not carry, every time.
        for label, cats in (("missing", chosen.missing_categories),
                            ("under-represented", chosen.under_represented)):
            if cats:
                print(f"  {label}: {', '.join(c.value for c in cats)}")
        if not inputs:
            print("error: nothing to measure", file=sys.stderr)
            return 1

    work = Path(tempfile.mkdtemp(prefix="excmp-bench-"))
    rows: list[dict] = []
    try:
        for prof in profiles:
            ctx = StageContext(temp_dir=work / f"tmp-{prof.value}")
            arc = work / f"bench-{prof.value}.excmp"
            print(f"[{prof.value}] compressing {sample.name} ...", flush=True)
            t0 = time.monotonic()
            try:
                result = engine.compress(inputs, arc, prof, ctx)
            except Exception as exc:
                print(f"  FAILED: {exc}")
                rows.append({"profile": prof.value, "error": str(exc)})
                continue
            c_time = time.monotonic() - t0

            t0 = time.monotonic()
            engine.extract(arc, work / f"x-{prof.value}", ctx)
            x_time = time.monotonic() - t0

            rows.append({
                "profile": prof.value,
                "orig": result.orig_bytes,
                "size": result.final_bytes,
                "saved": (1 - result.ratio) * 100,
                "c_time": c_time,
                "x_time": x_time,
                "warnings": len(result.warnings),
            })
            print(f"  {fmt_size(result.orig_bytes)} -> {fmt_size(result.final_bytes)} "
                  f"({(1 - result.ratio) * 100:.1f}% saved), "
                  f"compress {c_time:.1f}s / extract+verify {x_time:.1f}s")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    out_dir = Path(__file__).resolve().parent.parent / "docs" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{date.today().isoformat()}-{platform.node()}.md"
    lines = [
        f"# Benchmark: `{sample}`",
        "",
        f"- Machine: {platform.node()} / {platform.processor()}",
        f"- Date: {date.today().isoformat()}",
    ]
    if chosen is not None:
        lines += [
            f"- **Sampled**: {len(chosen.files)} of {chosen.source_files} files, "
            f"{fmt_size(chosen.total_bytes)} of {fmt_size(chosen.source_bytes)} "
            f"({chosen.fraction:.1%}), cap {fmt_size(chosen.cap_bytes)}",
        ]
        left_out = list(chosen.missing_categories) + list(chosen.under_represented)
        if left_out:
            lines.append(
                "- ⚠️ the sample could not carry these in proportion: "
                + ", ".join(c.value for c in left_out)
                + " — these rows rank the profiles, they do not predict the "
                  "whole job")
    lines += [
        "",
        "| profile | original | compressed | saved | compress time | extract+verify |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['profile']} | - | - | FAILED | - | - |")
        else:
            lines.append(
                f"| {r['profile']} | {fmt_size(r['orig'])} | {fmt_size(r['size'])} "
                f"| {r['saved']:.1f}% | {r['c_time']:.1f}s | {r['x_time']:.1f}s |"
            )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nresults written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
