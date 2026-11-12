"""Losslessly pack/unpack large broad-study reports with exact-byte hashes."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "reports/qait/broad_20261112"


def sha256(path):
    """Hash bytes in bounded memory."""
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def pack():
    """Preserve every complete report, without altering its raw bytes."""
    registration = json.loads((STUDY / "registration.json").read_text())
    manifest_path = STUDY / "artifact_manifest.json"
    if manifest_path.exists():
        raise ValueError("Artifact manifest already exists")
    records = []
    for job in registration["jobs"]:
        raw = STUDY / job["symbol"] / job["scenario"] / "report.json"
        packed = raw.with_suffix(".json.gz")
        with raw.open("rb") as source, packed.open("xb") as target:
            with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as zipped:
                shutil.copyfileobj(source, zipped)
        # Independently stream the decompressed bytes through a second hash.
        check = hashlib.sha256()
        with gzip.open(packed, "rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                check.update(block)
        assert check.hexdigest() == sha256(raw)
        records.append(dict(raw=str(raw.relative_to(ROOT)), raw_sha256=sha256(raw),
                            raw_bytes=raw.stat().st_size, packed=str(packed.relative_to(ROOT)),
                            packed_sha256=sha256(packed), packed_bytes=packed.stat().st_size))
    with manifest_path.open("x", encoding="utf-8") as stream:
        json.dump(dict(format="gzip, deterministic mtime=0, exact raw report bytes", reports=records), stream, indent=2)
    print(f"Packed and round-trip verified {len(records)} complete reports")


def unpack():
    """Restore ignored working reports only after verifying archive identity."""
    manifest = json.loads((STUDY / "artifact_manifest.json").read_text())
    for record in manifest["reports"]:
        packed, raw = ((ROOT / record[key]).resolve() for key in ("packed", "raw"))
        if not packed.is_relative_to(STUDY.resolve()) or not raw.is_relative_to(STUDY.resolve()):
            raise ValueError("Artifact path escapes study directory")
        assert sha256(packed) == record["packed_sha256"]
        if raw.exists():
            assert sha256(raw) == record["raw_sha256"]
            continue
        with gzip.open(packed, "rb") as source, raw.open("xb") as target:
            remaining = record["raw_bytes"]
            while remaining:
                block = source.read(min(remaining, 1024 * 1024))
                if not block:
                    raise ValueError("Truncated archive")
                target.write(block)
                remaining -= len(block)
            if source.read(1):
                raise ValueError("Archive exceeds registered size")
        assert sha256(raw) == record["raw_sha256"]
    print("Verified exact-byte report restoration")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("pack", "unpack"))
    args = parser.parse_args()
    pack() if args.command == "pack" else unpack()
