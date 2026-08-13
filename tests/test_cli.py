from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from phytoparalog.cli import main
from phytoparalog.engine import canonical_json_bytes, sha256_bytes

FIXTURE = Path(__file__).parents[1] / "examples" / "synthetic" / "study.json"


def test_validate_and_version(capsys) -> None:
    assert main(["validate", str(FIXTURE)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "VALID"
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_compile_stdout_has_no_local_output_path(tmp_path: Path, capsys) -> None:
    capsule = tmp_path / "private-location" / "capsule"
    capsule.parent.mkdir()
    assert main(["compile", str(FIXTURE), str(capsule)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert "output_dir" not in result
    assert str(tmp_path) not in json.dumps(result)
    assert result["validation"]["status"] == "STUDY_RECOMPUTED"


def test_validate_capsule_cli_modes(tmp_path: Path, capsys) -> None:
    capsule = tmp_path / "capsule"
    assert main(["compile", str(FIXTURE), str(capsule)]) == 0
    capsys.readouterr()
    assert main(["validate-capsule", str(capsule)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "INTEGRITY_ONLY"
    assert main(["validate-capsule", str(capsule), "--study", str(FIXTURE)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "STUDY_RECOMPUTED"


def test_invalid_input_returns_machine_readable_error(tmp_path: Path, capsys) -> None:
    source = tmp_path / "bad.json"
    source.write_text("{}", encoding="utf-8")
    assert main(["validate", str(source)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "INVALID"


def test_study_numeric_overflow_is_machine_readable_invalid(tmp_path: Path, capsys) -> None:
    source = tmp_path / "overflow.json"
    source.write_text('{"overflow_probe":1e999}\n', encoding="utf-8")
    assert main(["validate", str(source)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "INVALID"
    assert result["error_code"] == "STUDY_INVALID"


def test_study_oversized_integer_is_machine_readable_invalid(tmp_path: Path, capsys) -> None:
    source = tmp_path / "oversized-integer.json"
    source.write_text(
        '{"oversized_integer":' + ("9" * 5_000) + "}\n",
        encoding="utf-8",
    )

    assert main(["validate", str(source)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "INVALID"
    assert result["error_code"] == "STUDY_INVALID"


def test_extreme_json_nesting_is_machine_readable_invalid(tmp_path: Path, capsys) -> None:
    source = tmp_path / "nested.json"
    source.write_text(("[" * 100_000) + ("]" * 100_000), encoding="utf-8")

    assert main(["validate", str(source)]) == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "INVALID"
    assert result["error_code"] == "STUDY_INVALID"
    assert captured.err == ""


def test_lone_surrogate_is_machine_readable_invalid(tmp_path: Path, capsys) -> None:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value["study_id"] = "bad\ud800id"
    source = tmp_path / "surrogate.json"
    source.write_text(json.dumps(value) + "\n", encoding="utf-8")

    assert main(["validate", str(source)]) == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "INVALID"
    assert result["error_code"] == "STUDY_INVALID"
    assert captured.err == ""

    assert main(["compile", str(source), str(tmp_path / "capsule")]) == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "INVALID"
    assert result["error_code"] == "CAPSULE_COMPILE_INVALID"
    assert captured.err == ""


def test_cli_io_error_redacts_caller_path(monkeypatch, capsys) -> None:
    private_path = "/".join(("", "var", "private", "caller-secret", "input.json"))

    def unreadable(_path: Path) -> object:
        raise PermissionError(13, "permission denied", private_path)

    monkeypatch.setattr("phytoparalog.cli.load_json", unreadable)
    assert main(["validate", private_path]) == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result == {
        "error": "Study input could not be read.",
        "error_code": "STUDY_IO_ERROR",
        "status": "INVALID",
    }
    assert private_path not in captured.out
    assert captured.err == ""


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_fifo_study_input_is_machine_readable_invalid(tmp_path: Path, capsys) -> None:
    source = tmp_path / "input.json"
    os.mkfifo(source)

    assert main(["validate", str(source)]) == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "INVALID"
    assert result["error_code"] == "STUDY_INVALID"
    assert str(source) not in captured.out
    assert captured.err == ""


def test_capsule_numeric_overflow_is_machine_readable_invalid(tmp_path: Path, capsys) -> None:
    capsule = tmp_path / "capsule"
    assert main(["compile", str(FIXTURE), str(capsule)]) == 0
    capsys.readouterr()
    identifiability_path = capsule / "identifiability.json"
    payload = identifiability_path.read_bytes()
    identifiability_path.write_bytes(payload[:-2] + b',"overflow_probe":1e999}\n')
    manifest_path = capsule / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for row in manifest["files"]:
        member = (capsule / row["path"]).read_bytes()
        row["bytes"] = len(member)
        row["sha256"] = sha256_bytes(member)
    manifest["capsule_digest"] = sha256_bytes(canonical_json_bytes(manifest["files"]))
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    assert main(["validate-capsule", str(capsule)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "INVALID"
    assert result["error_code"] == "CAPSULE_INVALID"


def test_capsule_extreme_nesting_is_machine_readable_invalid(tmp_path: Path, capsys) -> None:
    capsule = tmp_path / "capsule"
    assert main(["compile", str(FIXTURE), str(capsule)]) == 0
    capsys.readouterr()
    identifiability_path = capsule / "identifiability.json"
    identifiability_path.write_text(("[" * 100_000) + ("]" * 100_000), encoding="utf-8")

    assert main(["validate-capsule", str(capsule)]) == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert result["status"] == "INVALID"
    assert result["error_code"] == "CAPSULE_INVALID"
    assert captured.err == ""


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_fifo_capsule_member_is_machine_readable_invalid(tmp_path: Path, capsys) -> None:
    capsule = tmp_path / "capsule"
    assert main(["compile", str(FIXTURE), str(capsule)]) == 0
    capsys.readouterr()
    member = capsule / "identifiability.json"
    member.unlink()
    os.mkfifo(member)

    assert main(["validate-capsule", str(capsule)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "INVALID"
    assert result["error_code"] == "CAPSULE_INVALID"
