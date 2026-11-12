"""Evidence archives must retain exact Windows bytes and reject tampering."""
import json

import pytest

from tools import qait_broad_artifacts as artifacts


@pytest.fixture
def archive(tmp_path, monkeypatch):
    study = tmp_path / "study"
    target = study / "EURUSD/base"
    target.mkdir(parents=True)
    raw = target / "report.json"
    content = b'{\r\n  "status": "complete", "unicode": "\xc3\xa9"\r\n}\r\n'
    raw.write_bytes(content)
    (study / "registration.json").write_text(json.dumps(dict(jobs=[dict(symbol="EURUSD", scenario="base")])))
    monkeypatch.setattr(artifacts, "ROOT", tmp_path)
    monkeypatch.setattr(artifacts, "STUDY", study)
    return study, raw, content


def test_archives_round_trip_exact_crlf_bytes_without_overwriting(archive):
    study, raw, content = archive
    artifacts.pack()
    raw.unlink()
    artifacts.unpack()
    assert raw.read_bytes() == content
    artifacts.unpack()  # Existing identical evidence is only verified.
    assert raw.read_bytes() == content
    with pytest.raises(ValueError, match="already exists"):
        artifacts.pack()


def test_corrupt_archive_is_rejected_before_restoration(archive):
    study, raw, _ = archive
    artifacts.pack()
    raw.unlink()
    packed = raw.with_suffix(".json.gz")
    packed.write_bytes(packed.read_bytes() + b"tampered")
    with pytest.raises(AssertionError):
        artifacts.unpack()
    assert not raw.exists()


def test_archive_manifest_cannot_restore_outside_study(archive):
    study, raw, _ = archive
    artifacts.pack()
    manifest = study / "artifact_manifest.json"
    document = json.loads(manifest.read_text())
    document["reports"][0]["raw"] = "outside.json"
    manifest.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="escapes study"):
        artifacts.unpack()
    assert not (study.parent / "outside.json").exists()
