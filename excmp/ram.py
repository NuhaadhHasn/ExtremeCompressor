"""Peak-RAM arithmetic for LZMA2, and the guard rails around the knobs.

Nobody else tells you what a compression setting will cost in memory before
you start it — 7-Zip's own Add dialog is the exception, and this is that
number, backed out of the same source (doc 19 §3, from
`CompressDialog.cpp:2942-3017`). On a 16 GB two-core laptop it is the
difference between a job and a swap storm, which is why it earns a column.

**The formula is authoritative; "≈13× dict" is a consequence of it.** The
source study says so in bold, and the shorthand drifts badly at small
dictionaries where the fixed ~8 MiB per block thread dominates.
"""

from __future__ import annotations

import re

MIB = 1 << 20
GIB = 1 << 30

# C/LzmaEnc.c:76-81. Changed in 24.09 and still true in 26.02; docs claiming
# "mx9 = 64 MB" are two generations stale, and the RAM figure moves 4x with it.
_DEFAULT_DICT = {
    1: 64 * 1024, 2: 1 * MIB, 3: 4 * MIB, 4: 4 * MIB, 5: 16 * MIB,
    6: 32 * MIB, 7: 64 * MIB, 8: 128 * MIB, 9: 256 * MIB,
}

# 7zHandlerOut.cpp:201-226 — LZMA2's internal block size is dict*4, clamped.
_CHUNK_MIN, _CHUNK_MAX = 1 * MIB, 256 * MIB

#: Safety margin on the allocation model, because it **under-booked** against
#: measurement - the dangerous direction, since under-booking is what lets a
#: job be accepted and then thrash (B9, 2026-09-11, Silesia, peak working set
#: from `GetProcessMemoryInfo`; harness `tools/ram_backtest.py`):
#:
#: | job | model | measured | ratio |
#: |---|---|---|---|
#: | `-md=16m`, mmt=2 | 176 MiB | **198 MiB** | **1.12** |
#: | `-md=64m`, mmt=2 | 680 MiB | **686 MiB** | **1.01** |
#: | `-md=192m`, mmt=2 | 2,024 MiB | 2,006 MiB | 0.99 |
#: | 300 KB input, mmt=4 | 32.7 MiB | 15.8 MiB | 0.48 |
#:
#: **A flat term was tried first and measurement rejected it.** Fitting only
#: the three large rows gives `10.25 x dict + 34 MiB` against the model's
#: `10.5 x dict + 8 MiB`, which reads like a missing constant - the process,
#: its DLLs, the heap 7-Zip needs regardless, none of which `CompressDialog`
#: has any reason to count. Adding 32 MiB fixed all three and then predicted
#: **64.7 MiB for a job that measures 15.8** - re-creating the exact failure
#: `effective_dict` exists to prevent, where a 371 KB job was quoted 6.0 GB
#: in the one panel that must never frighten anyone.
#:
#: So the margin is proportional instead. It covers every measured
#: under-book, and a small job stays small: 1.15 x 32.7 = 37.6 MiB, still
#: generous against 15.8 but not alarming. The tiny-job over-book is
#: pre-existing and lives in the multi-block branch, not here.
_SAFETY_MARGIN = 1.15

# B9. The target is 16 GB / 2 cores, and the cap there is 512 MiB: past that,
# mx9 multithreaded LZMA2 can outgrow physical memory (doc 19 §3).
_HARD_DICT_CAP = 512 * MIB
_DICT_FLOOR = 16 * MIB
# LzmaEnc's own floor once it has reduced for a small input.
_MIN_REDUCED_DICT = 64 * 1024
# Leave the OS and everything else the user is doing a third of the machine.
_RAM_BUDGET = 0.55


def lzma2_default_dict(level: int) -> int:
    """7-Zip's own default dictionary for ``-mx<level>``."""
    return _DEFAULT_DICT.get(max(0, min(9, int(level))), 16 * MIB)


def _block_threads(threads: int) -> int:
    """``-mmt=N`` at mx9 gives N/2 block threads: each LZMA encoder already
    spawns a match-finder thread plus a coder thread (C/LzmaEnc.c:103-109,
    C/Lzma2Enc.c:262)."""
    return max(1, int(threads) // 2)


def lzma2_compress_ram(dict_bytes: int, threads: int = 2, level: int = 9) -> int:
    """Peak compression RAM, per `CompressDialog.cpp:2942-3014`.

    ``size1 = hs*4 + dict*4 + dict*4 (level>=5) + 2 MiB``, with ``hs*4 ~= dict``
    and another ``2+4 MiB`` once an encoder runs its two threads; plus a
    ``(dict + 64 KiB) * 1.5`` window buffer. One block thread is the solid
    case; more than one additionally pays ``chunk = dict*4`` (capped 256 MiB)
    each, which is where the ~13x shorthand comes from.
    """
    dict_bytes = max(1, int(dict_bytes))
    blocks = _block_threads(threads)

    size1 = dict_bytes                      # hs*4 ~= dict
    size1 += dict_bytes * 4                 # match finder
    if level >= 5:
        size1 += dict_bytes * 4             # bt4 son array
    size1 += 2 * MIB
    if threads >= 2:
        size1 += 6 * MIB                    # +2 MiB +4 MiB for the 2-thread pair
    window = int((dict_bytes + 64 * 1024) * 1.5)
    per_block = size1 + window

    if blocks == 1:
        total = per_block                   # solid: no separate chunk buffers
    else:
        chunk = max(_CHUNK_MIN, min(_CHUNK_MAX, dict_bytes * 4))
        total = blocks * (per_block + chunk) + chunk
    return int(total * _SAFETY_MARGIN)


def effective_dict(dict_bytes: int, input_bytes: int) -> int:
    """The dictionary LZMA2 will *actually* allocate for this much data.

    `reduceSize` in LzmaEnc, and `CompressDialog` applies the same clamp
    before showing its own estimate: a dictionary larger than the input buys
    nothing, so the encoder shrinks it to the next power of two at or above
    the input size. Without this the RAM column quoted 6.0 GB for a 371 KB
    job - false, and frightening, in the one panel that must be neither.
    """
    dict_bytes = max(1, int(dict_bytes))
    need = max(1, int(input_bytes))
    size = _MIN_REDUCED_DICT
    while size < need and size < dict_bytes:
        size <<= 1
    return min(size, dict_bytes)


def lzma2_decompress_ram(dict_bytes: int, threads: int = 1) -> int:
    """`decompressMemory = dict + (2 << 20)` (CompressDialog.cpp:3016).

    **That figure is per decoder thread, and it was measured** (B9/G7,
    2026-09-11, Silesia at ``-md=64m``, peak working set via
    `GetProcessMemoryInfo`; harness `tools/ram_backtest.py`):

    | extract | peak |
    |---|---|
    | `-mmt=1` | **71 MiB** against 66 MiB predicted |
    | no switch / `-mmt=2` / `-mmt=4` | **255 MiB** |

    So the source-pinned formula was never wrong - it was *unreachable*,
    because `build_extract_cmd` passed no `-mmt` at all and 7-Zip therefore
    decoded with several dictionary buffers live at once. The number the app
    computed was ~3.9x optimistic against what 7-Zip actually did, on the one
    path where being optimistic matters most: an archive is extracted on
    whatever machine it lands on, which is routinely weaker than the one that
    made it.

    ``threads`` multiplies the per-thread figure. It is an **upper bound, not
    a fit**: 7-Zip's decoder thread count is not simply the core count - this
    2-core machine produced a peak consistent with four buffers - so
    over-booking is deliberate. Under-booking is the failure that lets a job
    be accepted and then thrash.
    """
    per_thread = int(dict_bytes) + 2 * MIB
    return per_thread * max(1, int(threads))


def max_safe_dict(total_ram_bytes: int, threads: int = 2) -> int:
    """The largest power-of-two dictionary whose peak fits the budget (B9).

    Returns a real 7-Zip dictionary size, not an arbitrary byte count: the
    tool only accepts powers of two, so handing it anything else means a
    refused job at the worst possible moment.
    """
    budget = int(total_ram_bytes * _RAM_BUDGET)
    candidate = _DICT_FLOOR
    size = _DICT_FLOOR
    while size <= _HARD_DICT_CAP:
        if lzma2_compress_ram(size, threads) <= budget:
            candidate = size
        else:
            break
        size <<= 1
    return candidate


def fmt_dict(dict_bytes: int) -> str:
    """``268435456`` -> ``"256m"``, the spelling ``-md=`` wants."""
    if dict_bytes >= GIB and dict_bytes % GIB == 0:
        return f"{dict_bytes // GIB}g"
    if dict_bytes >= MIB:
        return f"{dict_bytes // MIB}m"
    return f"{max(1, dict_bytes // 1024)}k"


# ---------------------------------------------------------------------------
# The Parameters line
# ---------------------------------------------------------------------------
# 7-Zip's own escape hatch, and PeaZip's too. There is no shell here - stages
# build argument LISTS - so this is not a shell-injection surface. What it IS:
# a way to hand 7-Zip a switch that breaks promises the engine has already
# made. `-o` and `-w` move the output and work directories the atomic publish
# and the free-space preflight were computed against; `@listfile` changes what
# goes into the archive after the ledger was built; `-p` puts a password in
# the job log. So this is an ALLOWLIST of method switches, not a blocklist of
# bad ones - a blocklist is a promise to have thought of everything.
_ALLOWED = re.compile(r"^-m[a-zA-Z0-9]+(=[A-Za-z0-9_.:+]+)?$")
# Spelled out so the refusal can name the reason rather than just saying no.
_REFUSED = {
    "-p": "would put a password in the job log",
    "-o": "would move the output away from the verified atomic publish",
    "-w": "would move the work folder the free-space check was made against",
    "-sfx": "self-extracting output needs code signing first (Phase H)",
    "@": "a listfile would change the contents after the ledger was built",
    "--": "ends switch parsing, so everything after it is treated as a path",
}


def parse_extra_args(text: str) -> list[str]:
    """Split and validate the free-text Parameters line.

    Raises ``ValueError`` naming the offending token. The message never
    repeats the token's *value* - refusing "-phunter2" must not print the
    password back (PeaZip's redaction rule, doc 17 section 4).
    """
    tokens = text.split()
    out: list[str] = []
    for token in tokens:
        for prefix, why in _REFUSED.items():
            if token == prefix or token.startswith(prefix):
                raise ValueError(f"{prefix} is not allowed here: {why}")
        if not _ALLOWED.match(token):
            raise ValueError(
                f"{token[:12]!r} is not an allowed switch — this line takes "
                f"7-Zip method switches only, like -mqs or -mmemuse=8g")
        out.append(token)
    return out


def total_ram_bytes(default: int = 8 * GIB) -> int:
    """Physical RAM, or ``default`` when the platform will not say.

    No psutil dependency for one number. Windows goes through
    GlobalMemoryStatusEx; POSIX through sysconf. A wrong answer here only
    widens or narrows the dictionary menu, so a conservative default beats
    adding a dependency or raising.
    """
    import ctypes
    import os

    try:
        if os.name == "nt":
            class _Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = _Status()
            status.dwLength = ctypes.sizeof(_Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullTotalPhys)
        else:
            pages = os.sysconf("SC_PHYS_PAGES")
            page = os.sysconf("SC_PAGE_SIZE")
            if pages > 0 and page > 0:
                return int(pages) * int(page)
    except Exception:
        pass
    return default


def dict_choices(threads: int = 2) -> list[int]:
    """Every dictionary this machine can actually run, smallest first.

    Stops at ``max_safe_dict`` rather than listing sizes that would swap: a
    choice the machine cannot honour is not a choice, it is a trap.
    """
    ceiling = max_safe_dict(total_ram_bytes(), threads)
    sizes, size = [], _DICT_FLOOR
    while size <= ceiling:
        sizes.append(size)
        size <<= 1
    return sizes


# --- zstd (Fast profile) --------------------------------------------------
#
# Added 2026-09-07. Until then this module modelled LZMA2 only, and the GUI's
# peak-RAM column was therefore **blank for Fast** on the stated grounds that
# "zstd's window is a tenth of it and never the thing that runs a 16 GB laptop
# out of memory". K4 falsified that: with the window pinned at 31 the same
# stage measured a 1,813 MiB peak, which is the same order as an LZMA2
# dictionary and very much the thing that matters on a 2-core/16 GB target.
#
# `zstandard.ZstdCompressionParameters.estimated_compression_context_size()`
# would answer this exactly and **must not be called**: for the parameter sets
# ZstdStage builds it kills the process with STATUS_INTEGER_DIVIDE_BY_ZERO
# (0xC0000094) inside libzstd - not an exception, a crash. So the model is
# fitted to measurement, which is this module's convention anyway.
#
# Measured on this machine, ZstdStage's real parameters (level 19, LDM on,
# threads=-1), 96 MiB of compressible input, each window in a fresh process
# because peak working set is a high-water mark for the life of a process:
#
#     window_log   window    peak
#         20         1 MiB   100 MiB
#         23         8 MiB   103 MiB
#         25        32 MiB   115 MiB
#         27       128 MiB   163 MiB
#
# That is a clean `base + 0.5 x window` (predicting 103/115/163 exactly), but
# the base is NOT constant: K4's 1.8 GiB run measured 1,813 MiB at window 31
# where this fit predicts 1,123. The gap is the multi-threaded worker buffers,
# which scale with the input as well as the window. So the shipped constants
# are deliberately above the fit - they cover the wl31 measurement too, and
# over-reading is the safe direction for a "will this fit in RAM?" column, the
# same bias `estimate.py` documents for every one of its own numbers.
_ZSTD_BASE_BYTES = 128 * MIB
_ZSTD_WINDOW_SHARE = 0.85


def zstd_compress_ram(window_log: int) -> int:
    """Peak working set for one ZstdStage compress, in bytes.

    Takes the window the stage will actually use - `_window_log_for` fits it
    to the input, so passing the maximum would over-report by more than a
    gigabyte on an ordinary job.
    """
    return int(_ZSTD_BASE_BYTES + _ZSTD_WINDOW_SHARE * (1 << window_log))


def zstd_decompress_ram(window_log: int) -> int:
    """Peak for one extract. The window buffer dominates and there are no
    worker buffers, so this is the window plus a small fixed cost - measured
    14 MiB for a narrow frame under a 2 GiB *ceiling*, which is why the
    ceiling is safe to raise but the frame's own window still costs."""
    return int((1 << window_log) + 16 * MIB)


# --- zpaqfranz (B17) --------------------------------------------------------
#
# Insane's final codec never had a model here, so the comparison table quoted
# LZMA2's figure for it: 7,084 MiB for a Silesia-sized (212 MB) job at the
# default thread count, where zpaqfranz measured 1,819 MiB at -m5 on a
# comparable 237 MB input. Every number below is a measurement: bare
# zpaqfranz v64.8j, `PeakWorkingSetSize` from the exited process handle, on
# B12's two .pcf intermediates (docs/benchmarks/2026-09-23-b12-lolz-vs-
# zpaqfranz.md):
#
#     method  threads  input                       peak
#       -m4      2     62,482,862 B (1 block)      441 MiB
#       -m4      1     62,482,862 B (1 block)      442 MiB
#       -m4      2     236,958,376 B (4 blocks)    915 MiB
#       -m4      1     236,958,376 B (4 blocks)    421 MiB
#       -m5      2     62,482,862 B (1 block)      895 MiB
#       -m5      2     236,958,376 B (4 blocks)  1,819 MiB
#
# So the peak scales with the threads that actually have a block to work on.
# zpaqfranz compresses independent blocks (it echoes plain -m4/-m5 as
# -m46/-m56, 64 MiB), so a one-block input cannot occupy a second thread
# however many it is given.
#
# Block size is the second lever, and memory grows with it. The B17 probe on
# the same 237 MB .pcf, restored and SHA-256 compared like everything above:
#
#       -m57     2     236,958,376 B (2 x 128 MiB)   2,903 MiB
#       -m58     2     236,958,376 B (1 x 256 MiB)   2,761 MiB (one thread busy)
#
#       -m58     2     644,802,560 B (3 x 256 MiB)   4,916 MiB (two threads busy)
#
# The last row is 645 MB of distinct installers from the Programs corpus,
# tarred the way the engine feeds the stage. Its peak was read from the live
# process every half second until it exited; the restore was stopped
# because only the RAM was wanted. It shows that -m58's second thread costs
# less than its first: about 606 MiB of the footprint is shared, so doubling
# the one-thread figure would over-read by 12%.
#
# Each method is therefore ``(shared, per busy thread)``. Where only one
# thread count was measured (-m4, -m5, -m57), the shared part is taken as
# zero and the per-thread part is the two-thread peak halved. That fits their
# one-thread points within 5%, erring high. -m58 has both points, so its line
# goes through both. Past two busy threads the line is extended, not measured:
# the target has two physical cores, which is what zpaqfranz uses by default.
_ZPAQFRANZ_MODEL: dict[int, tuple[int, int]] = {
    4: (0, 959_545_344 // 2),         # 457.5 MiB per thread
    5: (0, 1_907_761_152 // 2),       # 909.7 MiB per thread
    57: (0, 3_043_823_616 // 2),      # 1,451.4 MiB per thread
    58: (2 * 2_894_667_776 - 5_154_344_960,   # 605.6 MiB shared
         5_154_344_960 - 2_894_667_776),       # 2,155.0 MiB per thread
}


#: Small blocks, -m58 only. zpaq sizes its model to the block's real size,
#: not to the block limit, so a small job does not pay for 256 MiB. Found by
#: rendering the GUI: the first version of this model quoted 2.7 GB for a
#: 371.5 KB job. Measured on slices of the installer .pcf, -m58 -t2, every
#: slice restored and SHA-256 compared:
#:
#:     input      peak
#:     1 MiB      104,259,584 B   (99.4 MiB)
#:     4 MiB      151,838,720 B  (144.8 MiB)
#:     16 MiB     328,740,864 B  (313.5 MiB)
#:
#: A straight line through the 1 and 16 MiB points: about 85 MiB plus 14.3
#: bytes per byte in flight. The 4 MiB point sits 1.8% above it. The line is
#: used only until it meets the full-block model above, which it does well
#: before a block fills: the 237 MB single block peaked at 2,761 MiB, not the
#: 3,310 the line would say.
_ZPAQFRANZ_SMALL_SLOPE: dict[int, float] = {
    58: (328_740_864 - 104_259_584) / (15 * MIB),
}
_ZPAQFRANZ_SMALL_BASE: dict[int, float] = {
    58: 104_259_584 - _ZPAQFRANZ_SMALL_SLOPE[58] * MIB,
}


def _zpaqfranz_block_bytes(method: int) -> int:
    """Plain -m4/-m5 use 64 MiB blocks (zpaqfranz echoes them as -m46/-m56).
    A two-digit method's second digit is the block size as a power of two
    in MiB, so -m58 is 256 MiB."""
    return (1 << (method % 10)) * MIB if method >= 10 else 64 * MIB

#: The method the Insane stage runs. Duplicated from
#: `excmp.stages.zpaqfranz.DEFAULT_METHOD` rather than imported, because this
#: module sits below the stages. `tests/test_b17_insane_m5.py` asserts the two
#: agree, so the table can't describe a job that is not the one that runs.
ZPAQFRANZ_METHOD = 58


def zpaqfranz_compress_ram(method: int, threads: int, input_bytes: int) -> int:
    """Peak working set for one zpaqfranz add, in bytes.

    ``input_bytes`` is what zpaqfranz itself receives. In the Insane chain
    that is Precomp's output, which can be several times the original, so a
    caller holding only the original size should inflate it (see
    `planner.precomp_inflation`). Under-counting blocks under-states the
    peak, which is the dangerous direction.

    Only measured methods are answered: -m4, -m5, -m57 and -m58. -m1 to -m3,
    and blocks above 256 MiB, have never been run here, and borrowing a
    neighbour's figure for them would be a number nobody took.
    """
    model = _ZPAQFRANZ_MODEL.get(int(method))
    if model is None:
        raise ValueError(f"no measured peak for zpaqfranz -m{method}")
    shared, per_thread = model
    block = _zpaqfranz_block_bytes(int(method))
    blocks = max(1, -(-int(input_bytes) // block))
    busy = max(1, min(int(threads) or 1, blocks))
    full = shared + per_thread * busy
    slope = _ZPAQFRANZ_SMALL_SLOPE.get(int(method))
    if slope is None:
        return full
    in_flight = min(max(0, int(input_bytes)), busy * block)
    return int(min(full, _ZPAQFRANZ_SMALL_BASE[int(method)] + slope * in_flight))


def lzma2_auto_threads(dict_bytes: int, level: int = 9,
                       total_ram: int | None = None,
                       cores: int | None = None) -> int:
    """7-Zip's thread count for "auto": one per physical core, capped at what
    fits `_RAM_BUDGET`.

    The cap is needed because passing any -mmt switches off 7-Zip's own rule,
    which fits memory "by changing the number of working threads, if the
    number of threads was not specified". On the 2-core target the cap never
    bites (2 threads at mx9 is ~3 GiB by this model); on a 6-core 8 GB
    machine a forced -mmt6 would want ~9 GiB.
    """
    total = total_ram if total_ram is not None else total_ram_bytes()
    n = max(1, int(cores) if cores else physical_cores())
    budget = total * _RAM_BUDGET
    while n > 1 and lzma2_compress_ram(dict_bytes, n, level) > budget:
        n -= 1
    return n


def zpaqfranz_threads(requested: int, method: int,
                      total_ram: int | None = None) -> int:
    """How many threads zpaqfranz may use: the request, or physical cores
    for 0, capped at what fits `_RAM_BUDGET` on this machine.

    The cap is B17's own justification made binding. -m58 was chosen as the
    largest block whose *two-thread* peak fits the budget on the 16 GB target,
    but nothing held it to two: the Worker threads setting went straight
    through as ``-t``, and with no ``-t`` zpaqfranz takes every physical core.
    At about 2.1 GiB per busy thread, 8 threads is ~17 GB. The stage now always
    passes an explicit count from here, for compress and restore alike.
    """
    total = total_ram if total_ram is not None else total_ram_bytes()
    budget = total * _RAM_BUDGET
    cap = 1
    while cap < 64 and zpaqfranz_compress_ram(method, cap + 1, 1 << 40) <= budget:
        cap += 1
    want = int(requested) if requested and int(requested) > 0 else physical_cores()
    return max(1, min(want, cap))


def physical_cores() -> int:
    """Physical CPU cores, which is what zpaqfranz uses when given no ``-t``.

    Measured on the target laptop (2 cores, 4 logical processors): no switch
    reports ``2T``, ``-t2`` reports ``2T``, and only ``-ht`` reaches ``4T``.
    `os.cpu_count()` answers 4 there, so using it would double zpaqfranz's
    quoted RAM.

    Windows only, through GetLogicalProcessorInformation. Anywhere it can't
    answer, this falls back to the logical count: that over-states the peak
    rather than under-stating it.
    """
    import ctypes
    import os

    logical = os.cpu_count() or 1
    if os.name != "nt":
        return logical
    try:
        from ctypes import wintypes

        class _Info(ctypes.Structure):          # SYSTEM_LOGICAL_PROCESSOR_INFORMATION
            _fields_ = [("ProcessorMask", ctypes.c_size_t),
                        ("Relationship", ctypes.c_int),
                        ("_union", ctypes.c_ulonglong * 2)]

        kernel32 = ctypes.windll.kernel32
        size = wintypes.DWORD(0)
        kernel32.GetLogicalProcessorInformation(None, ctypes.byref(size))
        count = size.value // ctypes.sizeof(_Info)
        if count <= 0:
            return logical
        buf = (_Info * count)()
        if not kernel32.GetLogicalProcessorInformation(buf, ctypes.byref(size)):
            return logical
        cores = sum(1 for entry in buf if entry.Relationship == 0)  # RelationProcessorCore
        return max(1, min(cores, logical)) if cores else logical
    except Exception:                                        # noqa: BLE001
        return logical
