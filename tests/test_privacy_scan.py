from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
BACKSLASH = chr(92)
SPEC = importlib.util.spec_from_file_location("privacy_scan", ROOT / "scripts" / "privacy_scan.py")
assert SPEC is not None and SPEC.loader is not None
PRIVACY_SCAN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PRIVACY_SCAN
SPEC.loader.exec_module(PRIVACY_SCAN)


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _rules(path: Path) -> set[str]:
    return {item.rule for item in PRIVACY_SCAN.scan(path)}


def _signed_url(name: str, value: str = "fixture-value") -> str:
    return f"https://example.org/records?{name}={value}"


def test_clean_tree_passes(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "A neutral synthetic example.\n")
    assert PRIVACY_SCAN.scan(tmp_path) == []


@pytest.mark.parametrize(
    "private_path",
    [
        "/" + "Users" + "/person/analysis/input.json",
        "/" + "home" + "/person/analysis/input.json",
        "/" + "root" + "/analysis/input.json",
        "/" + "workspace" + "/" + "private-project/input.json",
        "/" + "tmp" + "/analysis/input.json",
        "/" + "private" + "/analysis/input.json",
        "/" + "var" + "/analysis/input.json",
        "/" + "Volumes" + "/analysis/input.json",
        "/" + "mnt" + "/analysis/input.json",
        "C:" + BACKSLASH + "Users" + BACKSLASH + "person/analysis/input.json",
        "C:" + BACKSLASH + "Temp" + BACKSLASH + "analysis/input.json",
        "D:" + "/" + "Temp" + "/analysis/input.json",
        (BACKSLASH * 2) + "server" + BACKSLASH + "Users/person/analysis/input.json",
        (BACKSLASH * 2) + "server" + BACKSLASH + "share/analysis/input.json",
        "fi" + "le:///" + "Users" + "/person/analysis/input.json",
    ],
)
def test_detects_private_paths_without_revealing_match(tmp_path: Path, private_path: str) -> None:
    _write(tmp_path / "note.txt", private_path)
    findings = PRIVACY_SCAN.scan(tmp_path)
    assert findings
    assert "person" not in " ".join(item.excerpt for item in findings)


def test_detects_archive_identifier(tmp_path: Path) -> None:
    accession = "S" + "RR" + "12345678"
    _write(tmp_path / "fixture.json", accession)
    assert "archive-accession" in _rules(tmp_path)


@pytest.mark.parametrize(
    "sequence",
    [
        ("AC" + "GT") * 8 + "\n" + ("TG" + "CA") * 8,
        ("ACGT" + "acgt") * 4 + "\n" + ("tgca" + "TGCA") * 4,
        ("AcDeFgHiKl" + "MnPqRsTvWy") + "\n" + ("AcDeFgHiKl" + "MnPqRsTvWy"),
        "ACDEFG" + "HIKL MNPQRS" + "TVWY ACDEFG" + "HIKL MNPQRS" + "TVWY",
        "acdef" + "ghikl\nmnpqr" + "stvwy\nacdef" + "ghikl\nmnpqr" + "stvwy",
    ],
)
def test_detects_wrapped_sequence_in_text_file(tmp_path: Path, sequence: str) -> None:
    _write(tmp_path / "notes.txt", sequence)
    assert "raw-biological-sequence" in _rules(tmp_path)


def test_detects_biological_file_extension(tmp_path: Path) -> None:
    _write(tmp_path / "records.fasta", "synthetic placeholder")
    assert _rules(tmp_path) == {"biological-file-extension"}


@pytest.mark.parametrize(
    "secret",
    [
        "gh" + "p_" + ("A" * 40),
        "sk" + "-" + ("A" * 30),
        "xox" + "b-" + ("A" * 24),
        "AK" + "IA" + ("A1" * 8),
        "api" + "_key=fixture-value",
        "AWS_" + "ACCESS_KEY_ID=" + "AK" + "IA" + ("A1" * 8),
        "Authorization: " + "Bearer " + "fixture-token-value-12345",
        "eyJ" + "hbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "signature12345",
    ],
)
def test_detects_credential_families(tmp_path: Path, secret: str) -> None:
    _write(tmp_path / "credential.txt", secret)
    assert PRIVACY_SCAN.scan(tmp_path)


@pytest.mark.parametrize(
    "query_name",
    [
        "key",
        "credential",
        "signature",
        "sig",
        "code",
        "session",
        "jwt",
        "X-Amz-Signature",
        "X-Goog-Credential",
    ],
)
def test_detects_signed_and_credential_urls(tmp_path: Path, query_name: str) -> None:
    _write(tmp_path / "url.txt", _signed_url(query_name, "abc"))
    assert "credential-url" in _rules(tmp_path)


def test_detects_url_userinfo(tmp_path: Path) -> None:
    value = "https://" + "fixture-user:fixture-password" + "@example.org/data"
    _write(tmp_path / "url.txt", value)
    assert "credential-url" in _rules(tmp_path)


def test_detects_json_escaped_windows_and_unc_paths(tmp_path: Path) -> None:
    value = {
        "drive": "C:" + BACKSLASH + "Users" + BACKSLASH + "person/secret.txt",
        "unc": (BACKSLASH * 2) + "server" + BACKSLASH + "share/secret.txt",
    }
    _write(tmp_path / "payload.json", json.dumps(value))
    rules = _rules(tmp_path)
    assert "windows-private-path" in rules
    assert "unc-private-path" in rules


@pytest.mark.parametrize(
    "query_name",
    ["X-Amz-Signature", "X-Goog-Credential", "access_token"],
)
def test_detects_json_solidus_escaped_credential_urls(tmp_path: Path, query_name: str) -> None:
    value = json.dumps({"url": _signed_url(query_name, "SECRET123")}).replace("/", "\\/")
    _write(tmp_path / "payload.json", value)
    assert "credential-url" in _rules(tmp_path)


def test_detects_json_secret_fields(tmp_path: Path) -> None:
    values = {
        "api" + "_key": "SECRET123",
        "access" + "_token": "TOKEN456",
        "pass" + "word": "PASS789",
    }
    _write(tmp_path / "payload.json", json.dumps(values))
    findings = PRIVACY_SCAN.scan(tmp_path)
    assert sum(item.rule == "assigned-secret" for item in findings) == 3
    rendered = " ".join(item.excerpt for item in findings)
    assert not any(value in rendered for value in values.values())


def test_detects_json_escaped_wrapped_mixed_case_sequence(tmp_path: Path) -> None:
    sequence = "\n".join(
        [
            "ACGTacgtACGTacgtACGT",
            "tgcaTGCAtgcaTGCAtgca",
            "ACGTacgtACGTacgtACGT",
        ]
    )
    _write(tmp_path / "payload.json", json.dumps({"sequence": sequence}))
    assert "raw-biological-sequence" in _rules(tmp_path)


def test_detects_json_escaped_wrapped_mixed_case_protein(tmp_path: Path) -> None:
    row = "AcDeFgHiKl" + "MnPqRsTvWy"
    sequence = row + "\n" + row
    _write(tmp_path / "payload.json", json.dumps({"sequence": sequence}))
    assert "raw-biological-sequence" in _rules(tmp_path)


def test_finding_excerpt_cannot_leak_adjacent_secret(tmp_path: Path) -> None:
    first = "A1B2C3D4"
    second = "E5F6G7H8"
    _write(tmp_path / "credentials.txt", "api" + f"_key={first} passwd={second}")
    findings = PRIVACY_SCAN.scan(tmp_path)
    rendered = json.dumps(
        [
            {
                "rule": item.rule,
                "path": item.path,
                "line": item.line,
                "excerpt": item.excerpt,
            }
            for item in findings
        ]
    )
    assert findings
    assert first not in rendered
    assert second not in rendered


def test_supports_custom_forbidden_terms(tmp_path: Path) -> None:
    _write(tmp_path / "plan.md", "Internal Project Alpha")
    findings = PRIVACY_SCAN.scan(tmp_path, ["Project Alpha"])
    assert [item.rule for item in findings] == ["forbidden-term-1"]


def test_rejects_invalid_utf8_instead_of_skipping_it(tmp_path: Path) -> None:
    (tmp_path / "opaque.txt").write_bytes(b"prefix\xffsuffix")
    assert _rules(tmp_path) == {"content-not-utf8"}


@pytest.mark.parametrize("payload", [b"prefix\x00suffix", b"prefix\x01suffix", b"prefix\x7fsuffix"])
def test_rejects_utf8_decodable_binary_controls(tmp_path: Path, payload: bytes) -> None:
    (tmp_path / "opaque.txt").write_bytes(payload)
    assert _rules(tmp_path) == {"binary-control-content"}


def test_rejects_fifo_root_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "named-pipe"
    try:
        os.mkfifo(fifo)
    except (AttributeError, OSError) as exc:  # pragma: no cover - unsupported platforms.
        pytest.skip(f"FIFO creation unavailable: {exc}")
    assert _rules(fifo) == {"non-regular-file"}


def test_scans_secret_bearing_filename_without_echoing_it(tmp_path: Path) -> None:
    token = "gh" + "p_" + ("A" * 40)
    (tmp_path / (token + ".fasta")).write_bytes(b"opaque\xff")
    findings = PRIVACY_SCAN.scan(tmp_path)
    rendered = " ".join(f"{item.rule} {item.path} {item.excerpt}" for item in findings)
    assert "path-github-token" in {item.rule for item in findings}
    assert token not in rendered


def test_secret_bearing_directory_never_leaks_through_child_finding(tmp_path: Path) -> None:
    token = "gh" + "p_" + ("A" * 40)
    secret_dir = tmp_path / token
    secret_dir.mkdir()
    (secret_dir / "opaque.txt").write_bytes(b"opaque\xff")
    findings = PRIVACY_SCAN.scan(tmp_path)
    rendered = " ".join(f"{item.rule} {item.path} {item.excerpt}" for item in findings)
    assert "path-github-token" in {item.rule for item in findings}
    assert "content-not-utf8" in {item.rule for item in findings}
    assert token not in rendered


def test_rejects_symlink_without_reading_external_target(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("gh" + "p_" + ("A" * 40), encoding="utf-8")
    link = release / "linked.txt"
    try:
        link.symlink_to(Path("..") / target.name)
    except OSError as exc:  # pragma: no cover - Windows may deny symlink creation.
        pytest.skip(f"symlink creation unavailable: {exc}")

    findings = PRIVACY_SCAN.scan(release)
    assert [item.rule for item in findings] == ["symbolic-link"]


def test_rejects_directory_symlink_without_following_it(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    _write(target / "secret.txt", "gh" + "p_" + ("A" * 40))
    link = release / "linked-directory"
    try:
        link.symlink_to(Path("..") / target.name, target_is_directory=True)
    except OSError as exc:  # pragma: no cover - Windows may deny symlink creation.
        pytest.skip(f"symlink creation unavailable: {exc}")

    findings = PRIVACY_SCAN.scan(release)
    assert [item.rule for item in findings] == ["symbolic-link"]


def test_scans_symlink_target_text_but_not_target_bytes(tmp_path: Path) -> None:
    link = tmp_path / "private-link"
    target = "/" + "Users" + "/person/unavailable.txt"
    try:
        link.symlink_to(target)
    except OSError as exc:  # pragma: no cover - Windows may deny symlink creation.
        pytest.skip(f"symlink creation unavailable: {exc}")

    assert _rules(tmp_path) == {"symbolic-link", "symlink-target-absolute-private-path"}


def test_ignores_generated_environment_directories(tmp_path: Path) -> None:
    private_path = "/" + "home" + "/person/generated.txt"
    _write(tmp_path / ".venv" / "record.txt", private_path)
    assert PRIVACY_SCAN.scan(tmp_path) == []


def test_exact_sha256_field_and_benign_urls_pass(tmp_path: Path) -> None:
    digest = "a" * 64
    _write(
        tmp_path / "README.md",
        "\n".join(
            [
                f'{{"artifact_sha256":"{digest}"}}',
                "https://example.org/records?monkey=capuchin&status_code=404",
                "workspace/project/result.json",
                "A bearer of records should document provenance clearly.",
                "This protein-family sentence contains punctuation and is ordinary prose.",
            ]
        ),
    )
    assert PRIVACY_SCAN.scan(tmp_path) == []


def test_repository_public_surface_passes() -> None:
    assert PRIVACY_SCAN.scan(ROOT) == []
