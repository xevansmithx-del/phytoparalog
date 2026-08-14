from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from phytoparalog import compile_capsule, validate_capsule
from phytoparalog.capsule import _manifest
from phytoparalog.engine import canonical_json_bytes

pytest.importorskip("tooluniverse", reason="ToolUniverse is an optional integration")
jsonschema = pytest.importorskip("jsonschema", reason="ToolUniverse installs jsonschema")

from phytoparalog_tu.tool import (  # noqa: E402
    PhytoParalogTool,
    _capsule_summary,
    _core,
    _fixture_payload,
)

ROOT = Path(__file__).parents[1]
CONFIG_PATH = ROOT / "src" / "phytoparalog_tu" / "data" / "phytoparalog_tools.json"
TOOLUNIVERSE_DOC = ROOT / "docs" / "tooluniverse.md"
ERROR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "status",
        "error",
        "error_code",
        "remediation",
        "target_selected",
        "target_selection",
    ],
    "properties": {
        "status": {"const": "error"},
        "error": {"type": "string", "minLength": 1},
        "error_code": {"type": "string", "minLength": 1},
        "remediation": {"type": "string", "minLength": 1},
        "target_selected": {"const": False},
        "target_selection": {
            "type": "object",
            "additionalProperties": False,
            "required": ["allowed", "status"],
            "properties": {
                "allowed": {"const": False},
                "status": {"const": "PROHIBITED"},
            },
        },
    },
}


def _configs() -> list[dict[str, Any]]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _config(name: str) -> dict[str, Any]:
    return next(config for config in _configs() if config["name"] == name)


def _validate_result(result: dict[str, Any], return_schema: dict[str, Any]) -> None:
    if result.get("status") == "success":
        assert set(result) == {"status", "data", "target_selected", "target_selection"}
        assert result["target_selected"] is False
        assert result["target_selection"] == {"allowed": False, "status": "PROHIBITED"}
        jsonschema.validate(result["data"], return_schema)
        return
    jsonschema.validate(result, ERROR_SCHEMA)


def test_tool_configs_defer_inputs_and_strictly_schema_check_outputs() -> None:
    configs = _configs()
    assert {config["name"] for config in configs} == {
        "PhytoParalog_preflight",
        "PhytoParalog_compile",
        "PhytoParalog_validate_capsule",
    }
    for config in configs:
        jsonschema.Draft202012Validator.check_schema(config["return_schema"])
        assert len(config["name"]) <= 55
        assert config["type"] == "PhytoParalogTool"
        assert config["parameter"]["additionalProperties"] is True
        assert "operation" not in config["parameter"]["properties"]
        assert "fields" not in config
        assert config["phytoparalog_operation"] in {
            "preflight",
            "compile",
            "validate_capsule",
        }
        assert len(config["description"]) >= 150
        assert not {"status", "data"} & set(config["return_schema"].get("properties", {}))
        for example in config["test_examples"]:
            output = PhytoParalogTool(config).run(example)
            _validate_result(output, config["return_schema"])
            assert output["status"] == "success"
            assert output["target_selected"] is False
            assert output["target_selection"] == {
                "allowed": False,
                "status": "PROHIBITED",
            }


def test_public_docs_declare_the_inner_success_data_schema_contract() -> None:
    documentation = TOOLUNIVERSE_DOC.read_text(encoding="utf-8")
    assert "validates `return_schema` against the inner `data` object" in documentation
    assert "adapter-owned error envelope remains a separate typed contract" in documentation


def test_direct_class_error_contract_matches_schema() -> None:
    for config in _configs():
        output = PhytoParalogTool(config).run({})
        _validate_result(output, config["return_schema"])
        assert output["status"] == "error"
        assert output["error_code"] == "INVALID_ARGUMENTS"
        assert output["target_selected"] is False


def test_fixture_is_competitive_and_intentionally_held() -> None:
    preflight = PhytoParalogTool(_config("PhytoParalog_preflight")).run(
        {"fixture_id": "synthetic-minimal-v1"}
    )
    compilation = PhytoParalogTool(_config("PhytoParalog_compile")).run(
        {"fixture_id": "synthetic-minimal-v1"}
    )
    assert preflight["data"]["competitive_member_count"] == 3
    assert preflight["data"]["family_member_count"] == 2
    assert compilation["data"]["producer_status"] == "HOLD"
    assert "EXTERNAL_RECEIPT_AUTHORITY_NOT_ESTABLISHED" in compilation["data"]["hold_reasons"]


def test_validate_fixture_is_full_study_recomputation() -> None:
    output = PhytoParalogTool(_config("PhytoParalog_validate_capsule")).run(
        {"fixture_id": "synthetic-minimal-v1"}
    )
    assert output["status"] == "success"
    assert output["data"]["capsule_valid"] is True
    assert output["data"]["capsule_semantics_trusted"] is True
    assert output["data"]["validation_mode"] == "STUDY_RECOMPUTED"
    assert output["data"]["validation_authority"] == "STUDY_RECOMPUTED_STRUCTURE_AND_SEMANTICS"


def test_external_digest_authenticates_bytes_not_semantics(tmp_path: Path) -> None:
    capsule = tmp_path / "capsule"
    compile_capsule(_fixture_payload(), capsule)
    manifest = json.loads((capsule / "manifest.json").read_text(encoding="utf-8"))
    output = PhytoParalogTool(_config("PhytoParalog_validate_capsule")).run(
        {
            "capsule_dir": str(capsule),
            "expected_capsule_digest": manifest["capsule_digest"],
        }
    )

    _validate_result(output, _config("PhytoParalog_validate_capsule")["return_schema"])
    assert output["status"] == "success"
    assert output["data"]["capsule_valid"] is True
    assert output["data"]["capsule_semantics_trusted"] is False
    assert output["data"]["capsule_digest"] == manifest["capsule_digest"]
    assert output["data"]["validation_mode"] == "EXTERNAL_DIGEST_ANCHORED"
    assert output["data"]["validation_authority"] == "EXTERNALLY_ANCHORED_INTEGRITY_ONLY"
    assert "producer_status" not in output["data"]
    assert "hold_reasons" not in output["data"]


def test_capsule_numeric_overflow_uses_capsule_error_envelope(tmp_path: Path) -> None:
    fixture = _fixture_payload()
    capsule = tmp_path / "capsule"
    compile_capsule(fixture, capsule)
    identifiability_path = capsule / "identifiability.json"
    payload = identifiability_path.read_bytes()
    identifiability_path.write_bytes(payload[:-2] + b',"overflow_probe":1e999}\n')
    manifest_path = capsule / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for row in manifest["files"]:
        member = (capsule / row["path"]).read_bytes()
        row["bytes"] = len(member)
        row["sha256"] = hashlib.sha256(member).hexdigest()
    manifest["capsule_digest"] = hashlib.sha256(canonical_json_bytes(manifest["files"])).hexdigest()
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    output = PhytoParalogTool(_config("PhytoParalog_validate_capsule")).run(
        {
            "capsule_dir": str(capsule),
            "expected_capsule_digest": manifest["capsule_digest"],
        }
    )
    _validate_result(output, _config("PhytoParalog_validate_capsule")["return_schema"])
    assert output["status"] == "error"
    assert output["error_code"] == "CAPSULE_INVALID"


def test_capsule_oversized_integer_uses_capsule_error_envelope(tmp_path: Path) -> None:
    fixture = _fixture_payload()
    capsule = tmp_path / "capsule"
    compile_capsule(fixture, capsule)
    identifiability_path = capsule / "identifiability.json"
    payload = identifiability_path.read_bytes()
    identifiability_path.write_bytes(
        payload[:-2] + b',"oversized_integer":' + (b"9" * 5_000) + b"}\n"
    )
    manifest_path = capsule / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for row in manifest["files"]:
        member = (capsule / row["path"]).read_bytes()
        row["bytes"] = len(member)
        row["sha256"] = hashlib.sha256(member).hexdigest()
    manifest["capsule_digest"] = hashlib.sha256(canonical_json_bytes(manifest["files"])).hexdigest()
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    output = PhytoParalogTool(_config("PhytoParalog_validate_capsule")).run(
        {
            "capsule_dir": str(capsule),
            "expected_capsule_digest": manifest["capsule_digest"],
        }
    )
    _validate_result(output, _config("PhytoParalog_validate_capsule")["return_schema"])
    assert output["status"] == "error"
    assert output["error_code"] == "CAPSULE_INVALID"


def test_core_validation_error_does_not_echo_caller_capsule_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capsule = tmp_path / "caller-private-capsule"
    capsule.mkdir()
    arguments = {
        "capsule_dir": str(capsule),
        "expected_capsule_digest": "a" * 64,
    }
    config = _config("PhytoParalog_validate_capsule")
    core = _core()

    def reject_with_caller_path(*args: Any, **kwargs: Any) -> None:
        raise core["ValidationError"](f"capsule is invalid: {capsule}")

    monkeypatch.setitem(core, "validate_capsule", reject_with_caller_path)
    monkeypatch.setattr("phytoparalog_tu.tool._core", lambda: core)

    direct = PhytoParalogTool(config).run(arguments)
    _validate_result(direct, config["return_schema"])
    assert direct["status"] == "error"
    assert direct["error_code"] == "CAPSULE_INVALID"
    assert str(tmp_path) not in direct["error"]
    assert "caller-private-capsule" not in direct["error"]

    from tooluniverse import ToolUniverse

    tu = ToolUniverse()
    tu.load_tools(include_tools=["PhytoParalog_validate_capsule"])
    loaded = tu.tools.PhytoParalog_validate_capsule(**arguments)
    _validate_result(loaded, config["return_schema"])
    assert loaded["status"] == "error"
    assert loaded["error_code"] == "CAPSULE_INVALID"
    assert str(tmp_path) not in loaded["error"]
    assert "caller-private-capsule" not in loaded["error"]


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_fifo_capsule_member_uses_capsule_error_envelope(tmp_path: Path) -> None:
    fixture = _fixture_payload()
    capsule = tmp_path / "capsule"
    compile_capsule(fixture, capsule)
    manifest = json.loads((capsule / "manifest.json").read_text(encoding="utf-8"))
    member = capsule / "identifiability.json"
    member.unlink()
    os.mkfifo(member)

    output = PhytoParalogTool(_config("PhytoParalog_validate_capsule")).run(
        {
            "capsule_dir": str(capsule),
            "expected_capsule_digest": manifest["capsule_digest"],
        }
    )
    _validate_result(output, _config("PhytoParalog_validate_capsule")["return_schema"])
    assert output["status"] == "error"
    assert output["error_code"] == "CAPSULE_INVALID"


def test_extreme_capsule_json_nesting_uses_capsule_error_envelope(tmp_path: Path) -> None:
    fixture = _fixture_payload()
    capsule = tmp_path / "capsule"
    compile_capsule(fixture, capsule)
    identifiability_path = capsule / "identifiability.json"
    identifiability_path.write_text(("[" * 100_000) + ("]" * 100_000), encoding="utf-8")
    manifest_path = capsule / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for row in manifest["files"]:
        member = (capsule / row["path"]).read_bytes()
        row["bytes"] = len(member)
        row["sha256"] = hashlib.sha256(member).hexdigest()
    manifest["capsule_digest"] = hashlib.sha256(canonical_json_bytes(manifest["files"])).hexdigest()
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    output = PhytoParalogTool(_config("PhytoParalog_validate_capsule")).run(
        {
            "capsule_dir": str(capsule),
            "expected_capsule_digest": manifest["capsule_digest"],
        }
    )
    _validate_result(output, _config("PhytoParalog_validate_capsule")["return_schema"])
    assert output["status"] == "error"
    assert output["error_code"] == "CAPSULE_INVALID"


def test_lone_surrogate_uses_typed_tooluniverse_errors(tmp_path: Path) -> None:
    fixture = _fixture_payload()
    fixture["study_id"] = "bad\ud800id"
    direct = PhytoParalogTool(_config("PhytoParalog_compile")).run({"study": fixture})
    _validate_result(direct, _config("PhytoParalog_compile")["return_schema"])
    assert direct["status"] == "error"
    assert direct["error_code"] == "INVALID_STUDY"

    capsule = tmp_path / "capsule"
    compile_capsule(_fixture_payload(), capsule)
    identifiability_path = capsule / "identifiability.json"
    payload = identifiability_path.read_bytes()
    identifiability_path.write_bytes(payload[:-2] + b',"surrogate_probe":"\\ud800"}\n')
    manifest_path = capsule / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for row in manifest["files"]:
        member = (capsule / row["path"]).read_bytes()
        row["bytes"] = len(member)
        row["sha256"] = hashlib.sha256(member).hexdigest()
    manifest["capsule_digest"] = hashlib.sha256(canonical_json_bytes(manifest["files"])).hexdigest()
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    capsule_output = PhytoParalogTool(_config("PhytoParalog_validate_capsule")).run(
        {
            "capsule_dir": str(capsule),
            "expected_capsule_digest": manifest["capsule_digest"],
        }
    )
    _validate_result(
        capsule_output,
        _config("PhytoParalog_validate_capsule")["return_schema"],
    )
    assert capsule_output["status"] == "error"
    assert capsule_output["error_code"] == "CAPSULE_INVALID"


def test_capsule_summary_uses_validated_snapshot_not_reopened_files(tmp_path: Path) -> None:
    fixture = _fixture_payload()
    capsule = tmp_path / "capsule"
    compile_capsule(fixture, capsule)
    core = _core()
    validate = core["validate_capsule"]

    def validate_then_forge(*args: Any, **kwargs: Any) -> dict[str, Any]:
        report = validate(*args, **kwargs)
        path = capsule / "identifiability.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["producer_status"] = "COMPILED_FOR_INDEPENDENT_REVIEW"
        document["hold_reasons"] = []
        path.write_bytes(canonical_json_bytes(document))
        return report

    core["validate_capsule"] = validate_then_forge
    summary = _capsule_summary(capsule, core, study=fixture)

    assert summary["producer_status"] == "HOLD"
    assert "EXTERNAL_RECEIPT_AUTHORITY_NOT_ESTABLISHED" in summary["hold_reasons"]
    assert summary["capsule_semantics_trusted"] is True


def test_refreshed_manifest_forgery_cannot_be_laundered(tmp_path: Path) -> None:
    fixture = _fixture_payload()
    capsule = tmp_path / "capsule"
    compile_capsule(fixture, capsule)
    original_manifest = json.loads((capsule / "manifest.json").read_text(encoding="utf-8"))
    original_digest = original_manifest["capsule_digest"]

    identifiability_path = capsule / "identifiability.json"
    identifiability = json.loads(identifiability_path.read_text(encoding="utf-8"))
    identifiability["producer_status"] = "COMPILED_FOR_INDEPENDENT_REVIEW"
    identifiability["hold_reasons"] = []
    identifiability_path.write_bytes(canonical_json_bytes(identifiability))
    documents = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in capsule.glob("*.json")
        if path.name != "manifest.json"
    }
    (capsule / "manifest.json").write_bytes(canonical_json_bytes(_manifest(documents)))

    assert validate_capsule(capsule)["status"] == "INTEGRITY_ONLY"
    tool = PhytoParalogTool(_config("PhytoParalog_validate_capsule"))
    unanchored = tool.run({"capsule_dir": str(capsule)})
    assert unanchored["status"] == "error"
    assert unanchored["error_code"] == "INVALID_ARGUMENTS"
    study_anchored = tool.run({"capsule_dir": str(capsule), "study": fixture})
    assert study_anchored["status"] == "error"
    assert study_anchored["error_code"] == "CAPSULE_INVALID"
    digest_anchored = tool.run(
        {
            "capsule_dir": str(capsule),
            "expected_capsule_digest": original_digest,
        }
    )
    assert digest_anchored["status"] == "error"
    assert digest_anchored["error_code"] == "CAPSULE_INVALID"


def test_loaded_tooluniverse_plugin_executes_all_tools() -> None:
    from tooluniverse import ToolUniverse

    tu = ToolUniverse()
    expected = {
        "PhytoParalog_preflight",
        "PhytoParalog_compile",
        "PhytoParalog_validate_capsule",
    }
    tu.load_tools(include_tools=sorted(expected))
    assert expected <= set(tu.all_tool_dict)
    for name in sorted(expected):
        result = getattr(tu.tools, name)(fixture_id="synthetic-minimal-v1")
        assert result["status"] == "success"
        assert result["target_selected"] is False


def test_loaded_tooluniverse_invalid_inputs_use_adapter_envelopes(tmp_path: Path) -> None:
    from tooluniverse import ToolUniverse

    expected = {
        "PhytoParalog_preflight",
        "PhytoParalog_compile",
        "PhytoParalog_validate_capsule",
    }
    tu = ToolUniverse()
    tu.load_tools(include_tools=sorted(expected))
    probes = {
        "PhytoParalog_preflight": [
            {},
            {"operation": "compile"},
            {"study": "x"},
        ],
        "PhytoParalog_compile": [
            {},
            {"extra": 1, "fixture_id": "synthetic-minimal-v1"},
        ],
        "PhytoParalog_validate_capsule": [
            {},
            {"capsule_dir": str(tmp_path / "nope"), "expected_digest": "ABC"},
            {
                "capsule_dir": str(tmp_path / "nope"),
                "expected_capsule_digest": "ABC",
            },
        ],
    }
    for name, cases in probes.items():
        config = _config(name)
        for arguments in cases:
            # Transport validation deliberately permits the call so the adapter
            # can return its stable, target-prohibiting error contract.
            jsonschema.validate(arguments, config["parameter"])
            result = getattr(tu.tools, name)(**arguments)
            _validate_result(result, config["return_schema"])
            assert result["status"] == "error"
            assert result["error_code"] == "INVALID_ARGUMENTS"
            assert result["target_selected"] is False
            assert result["target_selection"] == {
                "allowed": False,
                "status": "PROHIBITED",
            }


def test_plugin_class_is_registered() -> None:
    from tooluniverse.tool_registry import get_tool_registry

    assert get_tool_registry()["PhytoParalogTool"] is PhytoParalogTool


@pytest.mark.parametrize("name", [config["name"] for config in _configs()])
def test_tooluniverse_cli_example_validates_inner_success_data(name: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "tooluniverse.cli", "test", "--json", name],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "success"
    assert report["passed"] == report["total"] == 1
