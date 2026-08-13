from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import phytoparalog.capsule as capsule_module
from phytoparalog.capsule import CAPSULE_FILES, compile_capsule, validate_capsule
from phytoparalog.engine import canonical_json_bytes, sha256_bytes
from phytoparalog.models import ValidationError

FIXTURE = Path(__file__).parents[1] / "examples" / "synthetic" / "study.json"


def study_dict() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _refresh_manifest(capsule: Path) -> None:
    manifest_path = capsule / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for row in manifest["files"]:
        payload = (capsule / row["path"]).read_bytes()
        row["bytes"] = len(payload)
        row["sha256"] = sha256_bytes(payload)
    manifest["files"].sort(key=lambda row: row["path"])
    manifest["capsule_digest"] = sha256_bytes(canonical_json_bytes(manifest["files"]))
    manifest_path.write_bytes(canonical_json_bytes(manifest))


def test_capsule_has_exactly_five_deterministic_files(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    one = compile_capsule(study_dict(), first)
    two = compile_capsule(study_dict(), second)
    assert sorted(item.name for item in first.iterdir()) == sorted(CAPSULE_FILES)
    assert one["capsule_digest"] == two["capsule_digest"]
    assert one["validation"]["status"] == "STUDY_RECOMPUTED"
    assert "output_dir" not in one
    for filename in CAPSULE_FILES:
        assert (first / filename).read_bytes() == (second / filename).read_bytes()


@pytest.mark.parametrize("with_sentinel", [False, True])
def test_concurrent_destination_creation_is_preserved_and_temp_is_cleaned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_sentinel: bool,
) -> None:
    destination = tmp_path / "capsule"
    original_mkdir = os.mkdir
    injected = False

    def create_concurrent_destination(
        path: str | bytes | os.PathLike[str], mode: int = 0o777
    ) -> None:
        nonlocal injected
        if Path(path) == destination and not injected:
            injected = True
            original_mkdir(path, mode)
            if with_sentinel:
                (destination / "owner.txt").write_text("preserve me", encoding="utf-8")
        original_mkdir(path, mode)

    monkeypatch.setattr(capsule_module.os, "mkdir", create_concurrent_destination)

    with pytest.raises(ValidationError, match="output path already exists"):
        compile_capsule(study_dict(), destination)

    assert destination.is_dir()
    assert sorted(path.name for path in destination.iterdir()) == (
        ["owner.txt"] if with_sentinel else []
    )
    if with_sentinel:
        assert (destination / "owner.txt").read_text(encoding="utf-8") == "preserve me"
    assert list(tmp_path.glob(".capsule.*")) == []


def test_integrity_only_mode_is_explicit(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    result = compile_capsule(study_dict(), capsule)
    assert validate_capsule(capsule)["status"] == "INTEGRITY_ONLY"
    assert (
        validate_capsule(capsule, expected_capsule_digest=result["capsule_digest"])["status"]
        == "EXTERNAL_DIGEST_ANCHORED"
    )


@pytest.mark.parametrize("mutation", ["reformat", "reverse"])
def test_external_digest_requires_canonical_manifest_bytes(tmp_path: Path, mutation: str) -> None:
    capsule = tmp_path / "capsule"
    result = compile_capsule(study_dict(), capsule)
    manifest_path = capsule / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "reformat":
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    else:
        manifest["files"].reverse()
        manifest_path.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(ValidationError, match="canonical"):
        validate_capsule(
            capsule,
            expected_capsule_digest=result["capsule_digest"],
        )


def test_refreshed_manifest_forgery_fails_study_recomputation(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(study_dict(), capsule)
    identifiability_path = capsule / "identifiability.json"
    identifiability = json.loads(identifiability_path.read_text())
    identifiability["observations"][0]["member_bounds"][0]["lower_count"] = 999
    identifiability_path.write_bytes(canonical_json_bytes(identifiability))
    _refresh_manifest(capsule)
    assert validate_capsule(capsule)["status"] == "INTEGRITY_ONLY"
    with pytest.raises(ValidationError, match="full study recomputation"):
        validate_capsule(capsule, study=study_dict())


def test_sequence_and_stock_never_enter_capsule(tmp_path: Path) -> None:
    value = study_dict()
    capsule = tmp_path / "capsule"
    compile_capsule(value, capsule)
    payload = b"\n".join((capsule / name).read_bytes() for name in CAPSULE_FILES)
    assert value["stock_id"].encode() not in payload
    for transcript in value["transcripts"]:
        assert transcript["sequence"].encode() not in payload


def test_extra_file_and_tampering_fail_closed(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(study_dict(), capsule)
    (capsule / "extra.json").write_text("{}")
    with pytest.raises(ValidationError, match="exactly"):
        validate_capsule(capsule)


def test_hardlinked_capsule_member_is_rejected(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(study_dict(), capsule)
    original = capsule / "identifiability.json"
    outside = tmp_path / "outside.json"
    outside.hardlink_to(original)
    with pytest.raises(ValidationError, match="single-link regular file"):
        validate_capsule(capsule)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_fifo_capsule_member_is_rejected_before_open(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(study_dict(), capsule)
    member = capsule / "identifiability.json"
    member.unlink()
    os.mkfifo(member)

    with pytest.raises(ValidationError, match="single-link regular file"):
        validate_capsule(capsule)


def test_malformed_nested_event_is_validation_error(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(study_dict(), capsule)
    events_path = capsule / "phytoresolve_proposed_events.json"
    events = json.loads(events_path.read_text())
    events["events"][0]["payload"] = "malformed"
    events_path.write_bytes(canonical_json_bytes(events))
    _refresh_manifest(capsule)
    with pytest.raises(ValidationError, match="event memory head mismatch"):
        validate_capsule(capsule)


def test_malformed_top_level_document_is_validation_error(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(study_dict(), capsule)
    identifiability_path = capsule / "identifiability.json"
    identifiability_path.write_bytes(canonical_json_bytes([]))
    _refresh_manifest(capsule)
    with pytest.raises(ValidationError, match=r"identifiability\.json: expected object"):
        validate_capsule(capsule)


def test_numeric_overflow_is_validation_error(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(study_dict(), capsule)
    identifiability_path = capsule / "identifiability.json"
    payload = identifiability_path.read_bytes()
    assert payload.endswith(b"}\n")
    identifiability_path.write_bytes(payload[:-2] + b',"overflow_probe":1e999}\n')
    _refresh_manifest(capsule)
    with pytest.raises(ValidationError, match="non-finite number"):
        validate_capsule(capsule)


def test_oversized_integer_is_validation_error(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(study_dict(), capsule)
    identifiability_path = capsule / "identifiability.json"
    payload = identifiability_path.read_bytes()
    assert payload.endswith(b"}\n")
    identifiability_path.write_bytes(
        payload[:-2] + b',"oversized_integer":' + (b"9" * 5_000) + b"}\n"
    )
    _refresh_manifest(capsule)

    with pytest.raises(ValidationError, match="integer exceeds 1000 digit limit"):
        validate_capsule(capsule)


def test_extreme_json_nesting_is_validation_error(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(study_dict(), capsule)
    identifiability_path = capsule / "identifiability.json"
    identifiability_path.write_text(("[" * 100_000) + ("]" * 100_000), encoding="utf-8")
    _refresh_manifest(capsule)

    with pytest.raises(ValidationError, match="JSON nesting exceeds parser limit"):
        validate_capsule(capsule)


def test_lone_surrogate_is_validation_error_before_canonical_encoding(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(study_dict(), capsule)
    identifiability_path = capsule / "identifiability.json"
    payload = identifiability_path.read_bytes()
    assert payload.endswith(b"}\n")
    identifiability_path.write_bytes(payload[:-2] + b',"surrogate_probe":"\\ud800"}\n')
    _refresh_manifest(capsule)

    with pytest.raises(ValidationError, match="non-Unicode-scalar"):
        validate_capsule(capsule)


@pytest.mark.parametrize("bad_digest", [123, True, [], "A" * 64])
def test_external_digest_type_errors_are_validation_errors(
    tmp_path: Path, bad_digest: object
) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(study_dict(), capsule)
    with pytest.raises(ValidationError, match="expected lowercase SHA-256"):
        validate_capsule(capsule, expected_capsule_digest=bad_digest)  # type: ignore[arg-type]
