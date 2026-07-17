import random

from excmp.analyzer import Category, analyze_file, analyze_tree, sample_entropy


def test_detects_text(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello world " * 1000)
    assert analyze_file(p).category == Category.TEXT


def test_detects_mp4_magic(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)
    assert analyze_file(p).category == Category.VIDEO


def test_detects_mkv_magic(tmp_path):
    p = tmp_path / "clip.mkv"
    p.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 100)
    assert analyze_file(p).category == Category.VIDEO


def test_detects_zip_magic(tmp_path):
    p = tmp_path / "x.zip"
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 50)
    assert analyze_file(p).category == Category.COMPRESSED_ARCHIVE


def test_detects_exe_magic(tmp_path):
    p = tmp_path / "x.exe"
    p.write_bytes(b"MZ" + b"\x00" * 100)
    assert analyze_file(p).category == Category.EXECUTABLE


def test_extension_fallback_video(tmp_path):
    p = tmp_path / "weird.avi"
    p.write_bytes(b"\x01\x02\x03\x04" * 10)
    assert analyze_file(p).category == Category.VIDEO


def test_entropy_random_high_text_low(tmp_path):
    r = tmp_path / "r.bin"
    r.write_bytes(random.randbytes(200_000))
    t = tmp_path / "t.txt"
    t.write_text("abc" * 100_000)
    assert sample_entropy(r) > 7.5
    assert sample_entropy(t) < 3.0


def test_zlib_stream_flag(tmp_path):
    import zlib
    z = tmp_path / "pak.dat"
    z.write_bytes(zlib.compress(b"payload " * 1000, 9))
    info = analyze_file(z)
    assert info.zlib_stream is True
    t = tmp_path / "t.txt"
    t.write_text("plain")
    assert analyze_file(t).zlib_stream is False


def test_analyze_tree_walks_recursively(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("x" * 10)
    (tmp_path / "sub" / "b.txt").write_text("y" * 10)
    infos = analyze_tree(tmp_path)
    assert len(infos) == 2
    assert all(i.size == 10 for i in infos)
