import json
import subprocess
import sys

import pytest

from excmp.tools import find_tools

needs_7z = pytest.mark.skipif(find_tools()["7z"] is None, reason="7z not installed")


def run_cli(*argv):
    return subprocess.run([sys.executable, "-m", "excmp", *argv],
                          capture_output=True, text=True, timeout=300)


def _tree(tmp_path):
    src = tmp_path / "data"
    src.mkdir()
    (src / "a.txt").write_text("text data " * 10_000)
    return src


def test_analyze_json(tmp_path):
    src = _tree(tmp_path)
    proc = run_cli("analyze", str(src), "--json")
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["files"][0]["category"] == "text"


@needs_7z
def test_compress_extract_cycle(tmp_path):
    src = _tree(tmp_path)
    arc = tmp_path / "o.excmp"
    proc = run_cli("compress", str(src), "-o", str(arc), "-p", "normal",
                   "--temp", str(tmp_path / "t"), "--json")
    assert proc.returncode == 0, proc.stderr
    stats = json.loads(proc.stdout)
    assert stats["saved_percent"] > 50  # repetitive text must shrink a lot

    out = tmp_path / "restore"
    proc = run_cli("extract", str(arc), "-o", str(out),
                   "--temp", str(tmp_path / "t"), "--json")
    assert proc.returncode == 0, proc.stderr
    assert (out / "data" / "a.txt").read_text() == "text data " * 10_000


def test_error_is_clean_one_liner(tmp_path):
    proc = run_cli("extract", str(tmp_path / "missing.excmp"),
                   "-o", str(tmp_path / "x"), "--temp", str(tmp_path / "t"))
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
