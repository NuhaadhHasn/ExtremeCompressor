import random

from excmp.analyzer import (Category, analyze_file, analyze_tree,
                            sample_entropy, sample_stats)


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


def test_measures_compressibility_in_the_same_read_pass(tmp_path):
    """The estimator needs a *measured* ratio, not a guess from a lookup table.
    Taking it in the pass that already reads the samples for entropy costs one
    zstd call and no extra I/O - which matters on the slow external drive the
    benchmark corpus lives on."""
    t = tmp_path / "t.txt"
    t.write_text("the quick brown fox " * 50_000)
    r = tmp_path / "r.bin"
    r.write_bytes(random.randbytes(200_000))

    assert analyze_file(t).sample_ratio < 0.2
    assert analyze_file(r).sample_ratio > 0.9


def test_the_worst_sample_is_reported_separately(tmp_path):
    """A compressible stub in front of an incompressible payload is the shape of
    every installer, and the mean of three samples over-promises on it. The
    estimator drives off the worst sample, so the analyzer has to hand both up."""
    stub = tmp_path / "installer.exe"
    # Deliberately > 3 MiB so the analyzer takes head/middle/tail rather than
    # one whole-file sample, and make only the head compressible.
    stub.write_bytes(b"MZ" + b"A" * (1 << 20) + random.randbytes(3 << 20))

    info = analyze_file(stub)
    assert info.sample_ratio < info.sample_ratio_max
    assert info.sample_ratio_max > 0.9

    uniform = tmp_path / "uniform.bin"
    uniform.write_bytes(random.randbytes(4 << 20))
    same = analyze_file(uniform)
    assert same.sample_ratio_max == same.sample_ratio


def test_sample_stats_and_sample_entropy_agree(tmp_path):
    """sample_entropy() stays a thin wrapper - callers and the old plan docs
    still import it by name."""
    p = tmp_path / "mixed.bin"
    p.write_bytes(b"hello world " * 5_000 + random.randbytes(50_000))
    stats = sample_stats(p)
    assert stats.entropy_bps == sample_entropy(p)
    assert 0.0 < stats.ratio <= 1.0
    assert stats.ratio <= stats.ratio_max


def test_empty_file_has_a_neutral_ratio(tmp_path):
    p = tmp_path / "empty.bin"
    p.write_bytes(b"")
    info = analyze_file(p)
    assert info.sample_ratio == 1.0
    assert info.sample_ratio_max == 1.0


def test_analyze_tree_walks_recursively(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("x" * 10)
    (tmp_path / "sub" / "b.txt").write_text("y" * 10)
    infos = analyze_tree(tmp_path)
    assert len(infos) == 2
    assert all(i.size == 10 for i in infos)
