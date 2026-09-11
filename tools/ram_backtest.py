"""B9 — score `excmp.ram`'s formulas against the RAM 7-Zip actually uses.

The formulas in `excmp/ram.py` are source-pinned: every term cites a line in
7-Zip's `CompressDialog.cpp` or `LzmaEnc.c`. What none of them had until this
script is a **measurement**. That is the same gap B8 found in the size
estimator, where a constant fitted on one corpus had been mistaken for a
property of the codec and the range excluded the truth on 3 of 4 profiles.

A source-pinned formula can still be wrong here, for reasons the source does
not show:

- `CompressDialog` predicts what 7-Zip *allocates*. Windows reports the
  **working set** - pages actually resident - which is smaller when an
  allocation is never touched, and larger because of the exe, its DLLs and the
  heap it needs regardless.
- The dictionary is clamped to the input by `reduceSize`, so a small corpus
  never pays the dictionary it asked for (`effective_dict` models this, and
  that clamp is the reason a 371 KB job once had a 6.0 GB figure shown to a
  user).

**How the peak is taken.** `GetProcessMemoryInfo` on the child's handle after
it exits, which gives `PeakWorkingSetSize` for the whole run - not a sampled
poll, which would miss a spike between samples. The handle stays valid after
exit precisely so this can be read.

Usage:
    .venv\\Scripts\\python.exe tools\\ram_backtest.py <corpus_dir> [--dicts 16,64,192]
"""

from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from excmp import ram                                    # noqa: E402
from excmp.tools import find_tools                       # noqa: E402

MIB = 1 << 20


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def run_and_measure_peak(cmd: list[str]) -> tuple[int, int]:
    """Run ``cmd`` to completion; return (exit code, peak working set bytes).

    The peak is read from the process handle *after* the child exits. A
    polling sampler was the obvious alternative and is worse: LZMA2 allocates
    its match finder in one step, so the spike can sit entirely between two
    samples.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    proc.wait()
    counters = _PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    ok = ctypes.windll.psapi.GetProcessMemoryInfo(
        int(proc._handle), ctypes.byref(counters), counters.cb)
    if not ok:
        raise OSError(ctypes.GetLastError(),
                      "GetProcessMemoryInfo failed on the exited child")
    return proc.returncode, int(counters.PeakWorkingSetSize)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("--dicts", default="16,64,192",
                    help="dictionary sizes in MiB, comma separated")
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args()

    sevenzip = find_tools().get("7z")
    if sevenzip is None:
        print("7z not installed", file=sys.stderr)
        return 1
    corpus = Path(args.corpus)
    if not corpus.is_dir():
        print(f"{corpus} is not a directory", file=sys.stderr)
        return 1

    total = sum(p.stat().st_size for p in corpus.rglob("*") if p.is_file())
    print(f"corpus {corpus}")
    print(f"  {total:,} bytes, threads={args.threads}\n")

    header = (f"{'dict':>8} {'effective':>10} {'predicted':>12} "
              f"{'measured':>12} {'ratio':>7}  verdict")
    print(header)
    print("-" * len(header))

    rows = []
    for mib in [int(x) for x in args.dicts.split(",")]:
        dict_bytes = mib * MIB
        effective = ram.effective_dict(dict_bytes, total)
        predicted = ram.lzma2_compress_ram(effective, threads=args.threads,
                                           level=9)
        with tempfile.TemporaryDirectory(prefix="excmp-ram-") as tmp:
            out = Path(tmp) / "probe.7z"
            cmd = [sevenzip.path, "a", "-t7z", "-mx9", "-y",
                   f"-md={mib}m", f"-mmt={args.threads}",
                   str(out), str(corpus)]
            code, peak = run_and_measure_peak(cmd)
        if code != 0:
            print(f"{mib:>6}m  7-Zip exited {code}")
            continue
        ratio = peak / predicted if predicted else float("inf")
        verdict = "over-books" if ratio < 1 else "UNDER-BOOKS"
        print(f"{mib:>6}m {effective / MIB:>9.0f}M {predicted / MIB:>11.0f}M "
              f"{peak / MIB:>11.0f}M {ratio:>7.2f}  {verdict}")
        rows.append((mib, effective, predicted, peak, ratio))

    # --- extraction, which is what G7 needs and nothing had measured ------
    print("")
    print(f"{'dict':>8} {'predicted':>12} {'measured':>12} {'ratio':>7}"
          f"  (EXTRACT)")
    print("-" * 50)
    for mib in [int(x) for x in args.dicts.split(",")]:
        dict_bytes = mib * MIB
        effective = ram.effective_dict(dict_bytes, total)
        predicted = ram.lzma2_decompress_ram(effective)
        with tempfile.TemporaryDirectory(prefix="excmp-ramx-") as tmp:
            archive = Path(tmp) / "probe.7z"
            code, _ = run_and_measure_peak(
                [sevenzip.path, "a", "-t7z", "-mx9", "-y", f"-md={mib}m",
                 f"-mmt={args.threads}", str(archive), str(corpus)])
            if code != 0:
                continue
            dest = Path(tmp) / "out"
            code, peak = run_and_measure_peak(
                [sevenzip.path, "x", "-bsp1", "-y", f"-o{dest}", str(archive)])
        if code != 0:
            print(f"{mib:>6}m  extract exited {code}")
            continue
        ratio = peak / predicted if predicted else float("inf")
        print(f"{mib:>6}m {predicted / MIB:>11.0f}M {peak / MIB:>11.0f}M "
              f"{ratio:>7.2f}  {'UNDER-BOOKS' if ratio > 1 else 'ok'}")
        rows.append((f"x{mib}", effective, predicted, peak, ratio))

    if rows:
        worst = max(rows, key=lambda r: r[4])
        print(f"\nworst ratio measured/predicted: {worst[4]:.2f} "
              f"at -md={worst[0]}m")
        print("A ratio above 1.00 means the formula promised less RAM than "
              "7-Zip actually used, which is the dangerous direction: it is "
              "what would let a job be accepted that then thrashes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
