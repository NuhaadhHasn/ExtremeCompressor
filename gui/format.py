"""Human-facing formatting. No Qt, no engine - importable from tests.

The rounding here is deliberately coarse. An archiver that says "4 minutes
23 seconds remaining" and then takes 19 minutes has lied twice; one that
says "~5 min" has only been vague.
"""

from __future__ import annotations

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def fmt_size(num_bytes: float) -> str:
    """1536 -> '1.5 KB'. Bytes stay integral; everything else gets 1 decimal."""
    value = float(num_bytes)
    for unit in _UNITS:
        if abs(value) < 1024.0 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PB"


def fmt_percent(fraction: float) -> str:
    """0.7243 -> '72%'. Whole numbers only - decimals imply precision we lack."""
    return f"{fraction * 100:.0f}%"


def fmt_duration(seconds: float) -> str:
    """Elapsed time, exact-ish: '8.5s', '3m 04s', '1h 12m'."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def fmt_eta(seconds: float | None) -> str:
    """A remaining-time estimate, rounded *up* to a granularity that matches
    how much we actually know. ``None`` means "not enough data yet"."""
    if seconds is None:
        return "estimating…"
    seconds = max(0.0, float(seconds))
    if seconds < 10:
        return "a few seconds"
    if seconds < 60:
        return f"~{int(seconds / 10 + 0.999) * 10}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"~{int(minutes + 0.999)} min"
    hours = minutes / 60
    if hours < 10:
        whole = int(hours)
        rest = int((hours - whole) * 60 / 15 + 0.999) * 15
        if rest >= 60:
            return f"~{whole + 1} h"
        return f"~{whole} h {rest} min" if rest else f"~{whole} h"
    return f"~{int(hours + 0.999)} h"
