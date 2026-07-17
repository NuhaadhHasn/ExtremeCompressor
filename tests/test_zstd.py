from excmp.stages.base import StageContext
from excmp.stages.zstdstage import ZstdStage


def _make_tree(root):
    root.mkdir()
    (root / "a.txt").write_text("hello world, this repeats. " * 40_000)  # ~1 MB
    (root / "sub").mkdir()
    (root / "sub" / "b.bin").write_bytes(bytes(range(256)) * 100)


def test_zstd_roundtrip(tmp_path):
    src = tmp_path / "src"
    _make_tree(src)
    seen = []
    ctx = StageContext(temp_dir=tmp_path / "tmp", progress_cb=lambda s, p: seen.append(p))
    stage = ZstdStage()

    arc = stage.compress(src, tmp_path / "out.tar.zst", ctx)
    out = tmp_path / "ext"
    stage.extract(arc, out, ctx)

    assert (out / "a.txt").read_text() == "hello world, this repeats. " * 40_000
    assert (out / "sub" / "b.bin").read_bytes() == bytes(range(256)) * 100
    assert seen and all(0 <= p <= 100 for p in seen)


def test_zstd_ratio_on_text(tmp_path):
    src = tmp_path / "src"
    _make_tree(src)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    arc = ZstdStage().compress(src, tmp_path / "out.tar.zst", ctx)
    orig = sum(p.stat().st_size for p in src.rglob("*") if p.is_file())
    assert arc.stat().st_size < orig * 0.10


def test_zstd_single_file(tmp_path):
    f = tmp_path / "one.dat"
    f.write_bytes(b"XYZ" * 50_000)
    ctx = StageContext(temp_dir=tmp_path / "tmp")
    stage = ZstdStage()
    arc = stage.compress(f, tmp_path / "one.tar.zst", ctx)
    out = tmp_path / "ext"
    stage.extract(arc, out, ctx)
    assert (out / "one.dat").read_bytes() == b"XYZ" * 50_000
