"""A binary release must carry the licence texts it owes (THIRD-PARTY-NOTICES.md: PySide6 is LGPL-3.0)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_the_texts_are_in_the_repo_and_are_the_real_licences():
    lgpl = (ROOT / "licenses" / "LGPL-3.0.txt").read_text(encoding="utf-8")
    gpl = (ROOT / "licenses" / "GPL-3.0.txt").read_text(encoding="utf-8")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in lgpl[:300] and "Version 3, 29 June 2007" in lgpl[:400]
    assert "GNU GENERAL PUBLIC LICENSE" in gpl[:300] and "Version 3, 29 June 2007" in gpl[:400]
    assert len(lgpl) > 7000 and len(gpl) > 30000          # whole texts, not a stub
    assert (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License")


def test_the_installer_installs_them_next_to_the_program():
    iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    assert r'Source: "..\LICENSE"' in iss
    assert r'Source: "..\THIRD-PARTY-NOTICES.md"' in iss
    assert r'Source: "..\licenses\*"' in iss and r'DestDir: "{app}\licenses"' in iss


def test_the_notices_file_says_where_they_are_shipped():
    text = (ROOT / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    assert "licenses/LGPL-3.0.txt" in text
