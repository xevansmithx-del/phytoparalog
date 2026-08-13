"""Atomic deterministic five-file evidence capsules."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .engine import (
    TARGET_SELECTION,
    TOOL_VERSION,
    canonical_json_bytes,
    compile_study,
    sha256_bytes,
)
from .io import (
    MAX_JSON_BYTES,
    _bounded_int,
    _finite_float,
    _pairs_no_duplicates,
    _reject_constant,
    _validate_json_unicode_scalars,
)
from .models import Study, ValidationError

DOCUMENT_FILES = (
    "study_lock.json",
    "identifiability.json",
    "pec_candidate_evidence.json",
    "phytoresolve_proposed_events.json",
)
CAPSULE_FILES = (*DOCUMENT_FILES, "manifest.json")


def _manifest(documents: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    files = []
    for filename in sorted(documents):
        payload = canonical_json_bytes(documents[filename])
        files.append(
            {
                "bytes": len(payload),
                "path": filename,
                "sha256": sha256_bytes(payload),
            }
        )
    digest = sha256_bytes(canonical_json_bytes(files))
    return {
        "capsule_digest": digest,
        "files": files,
        "schema_version": "phytoparalog.manifest.v0.1",
        "target_selection": dict(TARGET_SELECTION),
        "tool_version": TOOL_VERSION,
    }


def compile_capsule(value: Study | Mapping[str, Any], output_dir: str | Path) -> dict[str, Any]:
    """Compile into a newly reserved directory without clobbering a concurrent creator."""

    destination = Path(output_dir)
    if destination.exists():
        raise ValidationError(f"output path already exists: {destination}")
    parent = destination.parent
    if not parent.exists() or not parent.is_dir():
        raise ValidationError(f"output parent directory does not exist: {parent}")
    if parent.is_symlink():
        raise ValidationError(f"refusing symbolic-link output parent: {parent}")
    compiled = compile_study(value)
    documents = compiled.documents()
    manifest = _manifest(documents)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=parent))
    try:
        for filename, document in documents.items():
            (temporary / filename).write_bytes(canonical_json_bytes(document))
        (temporary / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        _publish_no_clobber(temporary, destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    report = validate_capsule(destination, study=value)
    return {
        "capsule_digest": manifest["capsule_digest"],
        "producer_status": compiled.identifiability["producer_status"],
        "validation": report,
    }


def _publish_no_clobber(temporary: Path, destination: Path) -> None:
    """Reserve ``destination`` atomically, then populate it without replacing names."""

    try:
        os.mkdir(destination, mode=0o700)
    except FileExistsError as exc:
        raise ValidationError(f"output path already exists: {destination}") from exc

    reservation = os.lstat(destination)
    descriptor = -1
    created: dict[str, tuple[int, int]] = {}
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(destination, flags)
        opened = os.fstat(descriptor)
        if (reservation.st_dev, reservation.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValidationError("output reservation identity changed during publication")
        for filename in CAPSULE_FILES:
            os.link(
                temporary / filename,
                filename,
                dst_dir_fd=descriptor,
                follow_symlinks=False,
            )
            details = os.stat(filename, dir_fd=descriptor, follow_symlinks=False)
            created[filename] = (details.st_dev, details.st_ino)
        current = os.lstat(destination)
        if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValidationError("output reservation identity changed during publication")
        shutil.rmtree(temporary)
    except Exception:
        if descriptor >= 0:
            for filename, identity in created.items():
                try:
                    details = os.stat(filename, dir_fd=descriptor, follow_symlinks=False)
                    if (details.st_dev, details.st_ino) == identity:
                        os.unlink(filename, dir_fd=descriptor)
                except OSError:
                    pass
        try:
            current = os.lstat(destination)
            if (current.st_dev, current.st_ino) == (
                reservation.st_dev,
                reservation.st_ino,
            ) and not any(destination.iterdir()):
                os.rmdir(destination)
        except OSError:
            pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _exact_fields(value: Any, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{path}: expected object")
    if set(value) != expected:
        raise ValidationError(f"{path}: closed-schema field mismatch")
    return value


def _target_selection(value: Any, path: str) -> None:
    selection = _exact_fields(value, {"allowed", "status"}, path)
    if selection != TARGET_SELECTION:
        raise ValidationError(f"{path}: target selection must remain prohibited")


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _read_member_once(path: Path) -> bytes:
    """Read one bounded, single-link regular member through a no-follow fd."""

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode):
        raise ValidationError(f"capsule member cannot be a symbolic link: {path.name}")
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValidationError(f"capsule member must be a single-link regular file: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | nofollow
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValidationError(f"capsule member cannot be opened safely: {path.name}") from exc
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ValidationError(f"capsule member must be a single-link regular file: {path.name}")
        if details.st_size > MAX_JSON_BYTES:
            raise ValidationError(f"capsule member exceeds byte limit: {path.name}")
        chunks: list[bytes] = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise ValidationError(f"capsule member changed while reading: {path.name}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValidationError(f"capsule member grew while reading: {path.name}")
        after = os.fstat(descriptor)
        after_path = os.lstat(path)
        if (
            details.st_dev,
            details.st_ino,
            details.st_size,
            details.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValidationError(f"capsule member changed while reading: {path.name}")
        if (before.st_dev, before.st_ino) != (details.st_dev, details.st_ino) or (
            after_path.st_dev,
            after_path.st_ino,
        ) != (details.st_dev, details.st_ino):
            raise ValidationError(f"capsule member identity changed while reading: {path.name}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _parse_owned_json(payload: bytes, path: str) -> Any:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError(f"{path}: JSON is not UTF-8") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
            parse_int=_bounded_int,
        )
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc
    except RecursionError as exc:
        raise ValidationError(f"{path}: JSON nesting exceeds parser limit") from exc
    _validate_json_unicode_scalars(value)
    return value


def validate_capsule(
    capsule_dir: str | Path,
    *,
    study: Study | Mapping[str, Any] | None = None,
    expected_capsule_digest: str | None = None,
) -> dict[str, Any]:
    """Verify integrity, with optional external digest or full study recomputation.

    A capsule's self-authored manifest establishes only internal integrity.  Passing
    ``expected_capsule_digest`` externally anchors that integrity.  Passing the
    original study additionally recomputes every scientific output byte-for-byte.
    """

    capsule = Path(capsule_dir)
    if capsule.is_symlink() or not capsule.is_dir():
        raise ValidationError(f"capsule is not a regular directory: {capsule}")
    members = sorted(item.name for item in capsule.iterdir())
    if members != sorted(CAPSULE_FILES):
        raise ValidationError(
            f"capsule must contain exactly {list(CAPSULE_FILES)}; observed {members}"
        )
    owned_bytes = {filename: _read_member_once(capsule / filename) for filename in CAPSULE_FILES}
    owned_documents = {
        filename: _parse_owned_json(payload, filename) for filename, payload in owned_bytes.items()
    }

    manifest = _exact_fields(
        owned_documents["manifest.json"],
        {"capsule_digest", "files", "schema_version", "target_selection", "tool_version"},
        "manifest",
    )
    if owned_bytes["manifest.json"] != canonical_json_bytes(manifest):
        raise ValidationError("manifest.json: JSON is not canonical")
    if manifest["schema_version"] != "phytoparalog.manifest.v0.1":
        raise ValidationError("manifest.schema_version: unsupported value")
    if manifest["tool_version"] != TOOL_VERSION:
        raise ValidationError("manifest.tool_version: unsupported value")
    if not _is_sha256(manifest["capsule_digest"]):
        raise ValidationError("manifest.capsule_digest: expected lowercase SHA-256")
    _target_selection(manifest["target_selection"], "manifest.target_selection")
    if not isinstance(manifest["files"], list) or len(manifest["files"]) != 4:
        raise ValidationError("manifest.files: expected four entries")
    expected_paths = sorted(DOCUMENT_FILES)
    actual_paths: list[str] = []
    manifest_rows: list[dict[str, Any]] = []
    documents: dict[str, dict[str, Any]] = {}
    for index, raw_row in enumerate(manifest["files"]):
        row = _exact_fields(raw_row, {"bytes", "path", "sha256"}, f"manifest.files[{index}]")
        filename = row["path"]
        if not isinstance(filename, str):
            raise ValidationError(f"manifest.files[{index}].path: expected string")
        if type(row["bytes"]) is not int or row["bytes"] < 0:
            raise ValidationError(f"manifest.files[{index}].bytes: expected non-negative integer")
        if not _is_sha256(row["sha256"]):
            raise ValidationError(f"manifest.files[{index}].sha256: expected lowercase SHA-256")
        actual_paths.append(filename)
        if filename not in DOCUMENT_FILES:
            raise ValidationError(f"manifest.files[{index}].path: unexpected capsule member")
        payload = owned_bytes[filename]
        if row["bytes"] != len(payload) or row["sha256"] != sha256_bytes(payload):
            raise ValidationError(f"manifest.files[{index}]: byte count or digest mismatch")
        document = owned_documents[filename]
        if not isinstance(document, dict):
            raise ValidationError(f"{filename}: expected object")
        if payload != canonical_json_bytes(document):
            raise ValidationError(f"{filename}: JSON is not canonical")
        documents[filename] = _exact_fields(
            document, set(document), filename
        )  # object type check; schemas below own fields
        manifest_rows.append(dict(row))
    if actual_paths != expected_paths or len(set(actual_paths)) != 4:
        raise ValidationError(
            "manifest.files: paths must name each document exactly once in canonical order"
        )
    if manifest["capsule_digest"] != sha256_bytes(
        canonical_json_bytes(sorted(manifest_rows, key=lambda row: row["path"]))
    ):
        raise ValidationError("manifest.capsule_digest: mismatch")
    if expected_capsule_digest is not None:
        if not _is_sha256(expected_capsule_digest):
            raise ValidationError("expected_capsule_digest: expected lowercase SHA-256")
        if manifest["capsule_digest"] != expected_capsule_digest:
            raise ValidationError("capsule digest does not match external expected digest")

    for filename, document in documents.items():
        if "target_selection" not in document:
            raise ValidationError(f"{filename}: missing target_selection")
        _target_selection(document["target_selection"], f"{filename}.target_selection")
    lock_hash = sha256_bytes(canonical_json_bytes(documents["study_lock.json"]))
    pec = documents["pec_candidate_evidence.json"]
    if pec.get("study_lock_sha256") != lock_hash:
        raise ValidationError("pec_candidate_evidence.json: study lock digest mismatch")
    events = documents["phytoresolve_proposed_events.json"]
    expected_head = documents["study_lock.json"].get("bound_memory_head_sha256")
    if events.get("bound_memory_head_sha256") != expected_head:
        raise ValidationError("phytoresolve_proposed_events.json: stale or missing memory head")
    precondition = events.get("append_precondition")
    if (
        not isinstance(precondition, dict)
        or precondition.get("expected_memory_head_sha256") != expected_head
    ):
        raise ValidationError("phytoresolve_proposed_events.json: invalid append precondition")
    raw_events = events.get("events")
    if not isinstance(raw_events, list):
        raise ValidationError("phytoresolve_proposed_events.json: events must be an array")
    for event in raw_events:
        if not isinstance(event, dict):
            raise ValidationError("phytoresolve_proposed_events.json: event must be an object")
        payload = event.get("payload")
        if (
            not isinstance(payload, dict)
            or payload.get("bound_memory_head_sha256") != expected_head
        ):
            raise ValidationError("phytoresolve_proposed_events.json: event memory head mismatch")
    mode = "INTEGRITY_ONLY"
    if expected_capsule_digest is not None:
        mode = "EXTERNAL_DIGEST_ANCHORED"
    if study is not None:
        source_study = study if isinstance(study, Study) else Study.from_dict(study)
        expected_documents = compile_study(source_study).documents()
        for filename in DOCUMENT_FILES:
            expected_bytes = canonical_json_bytes(expected_documents[filename])
            if expected_bytes != owned_bytes[filename]:
                raise ValidationError(f"{filename}: differs from full study recomputation")
        expected_manifest = _manifest(expected_documents)
        if canonical_json_bytes(expected_manifest) != owned_bytes["manifest.json"]:
            raise ValidationError("manifest.json: differs from full study recomputation")
        mode = "STUDY_RECOMPUTED"
    return {
        "capsule_digest": manifest["capsule_digest"],
        "file_count": 5,
        "status": mode,
    }
