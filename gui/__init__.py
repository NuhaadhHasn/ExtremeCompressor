"""ExtremeCompressor desktop GUI (PySide6).

The engine in ``excmp`` knows nothing about this package - it is a plain
library with a CLI. Everything here is presentation: threading the engine
off the UI thread, turning routing decisions into sentences, and drawing
the queue.
"""

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    from .app import main as _main
    return _main(argv)
