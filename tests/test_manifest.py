import pytest

from excmp.manifest import Manifest, StageRecord, read_container, write_container


def test_container_roundtrip(tmp_path):
    payload = tmp_path / "p.bin"
    payload.write_bytes(b"DATA" * 1000)
    m = Manifest.new(
        profile="normal",
        stages=[StageRecord("sevenzip", "7z", "24.08", {"mx": 9})],
        inputs={"a.txt": {"size": 4, "sha256": "aa"}},
        payload_name="p.bin",
    )
    arc = tmp_path / "out.excmp"
    write_container(arc, m, payload)

    m2, payload2 = read_container(arc, extract_dir=tmp_path / "x")
    assert m2.profile == "normal"
    assert m2.schema == 1
    assert m2.stages[0].stage == "sevenzip"
    assert m2.stages[0].params == {"mx": 9}
    assert m2.inputs["a.txt"]["sha256"] == "aa"
    assert payload2.read_bytes() == payload.read_bytes()


def test_json_roundtrip_preserves_stage_order(tmp_path):
    m = Manifest.new(
        profile="extreme",
        stages=[
            StageRecord("tar", "python", "3.12", {}),
            StageRecord("precomp", "precomp", "0.4.8", {}),
            StageRecord("sevenzip", "7z", "", {"mx": 9}),
        ],
        inputs={},
        payload_name="payload",
    )
    m2 = Manifest.from_json(m.to_json())
    assert [s.stage for s in m2.stages] == ["tar", "precomp", "sevenzip"]


def test_read_rejects_non_excmp(tmp_path):
    bad = tmp_path / "bad.excmp"
    bad.write_bytes(b"not a zip at all")
    with pytest.raises(Exception):
        read_container(bad, extract_dir=tmp_path / "x")
