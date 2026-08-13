"""ToolUniverse adapter for the local PhytoParalog compiler."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tooluniverse.base_tool import BaseTool
from tooluniverse.tool_registry import register_tool

TARGET_SELECTION = {"allowed": False, "status": "PROHIBITED"}
FIXTURE_ID = "synthetic-minimal-v1"
_OPERATION_ARGUMENTS = {
    "preflight": {"fixture_id", "study"},
    "compile": {"fixture_id", "study"},
    "validate_capsule": {
        "capsule_dir",
        "expected_capsule_digest",
        "fixture_id",
        "study",
    },
}


def _success(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "success",
        "data": data,
        "target_selected": False,
        "target_selection": dict(TARGET_SELECTION),
    }


def _error(code: str, message: str, remediation: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": message,
        "error_code": code,
        "remediation": remediation,
        "target_selected": False,
        "target_selection": dict(TARGET_SELECTION),
    }


def _validate_adapter_arguments(arguments: dict[str, Any], operation: str) -> None:
    """Closed-validate at the adapter boundary so ToolUniverse cannot replace the envelope."""

    if any(not isinstance(key, str) for key in arguments):
        raise ValueError("Argument field names must be strings.")
    allowed = _OPERATION_ARGUMENTS[operation]
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise ValueError(f"Unrecognized argument field(s): {', '.join(unknown)}.")

    study = arguments.get("study")
    if study is not None and not isinstance(study, Mapping):
        raise ValueError("'study' must be an object when supplied.")
    fixture_id = arguments.get("fixture_id")
    if fixture_id is not None and not isinstance(fixture_id, str):
        raise ValueError("'fixture_id' must be a string when supplied.")
    if operation != "validate_capsule":
        return

    capsule_dir = arguments.get("capsule_dir")
    if capsule_dir is not None and not isinstance(capsule_dir, str):
        raise ValueError("'capsule_dir' must be a string when supplied.")
    expected_digest = arguments.get("expected_capsule_digest")
    if expected_digest is not None and (
        not isinstance(expected_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
    ):
        raise ValueError("'expected_capsule_digest' must be a lowercase SHA-256 string.")


def _fixture_payload() -> dict[str, Any]:
    """Build the neutral fixture under the current closed receipt schema."""

    def canonical_digest(value: Any) -> str:
        payload = (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def receipt(
        receipt_id: str,
        receipt_type: str,
        record_id: str,
        subject_sha256: str,
    ) -> dict[str, Any]:
        return {
            "artifact_sha256": subject_sha256,
            "issuer": "SYNTHETIC_FIXTURE_GENERATOR",
            "receipt_id": receipt_id,
            "receipt_type": receipt_type,
            "record_id": record_id,
            "source_version": "synthetic-v1",
            "subject_sha256": subject_sha256,
            "verification_method": "SHA256_RECALCULATED",
            "verification_state": "RECEIPT_VERIFIED",
        }

    members = [
        {
            "identity_receipt_ids": ["receipt-member-a"],
            "identity_state": "EXACT",
            "locus_id": "locus-a",
            "member_id": "member-a",
        },
        {
            "identity_receipt_ids": ["receipt-member-b"],
            "identity_state": "EXACT",
            "locus_id": "locus-b",
            "member_id": "member-b",
        },
        {
            "identity_receipt_ids": ["receipt-member-background"],
            "identity_state": "EXACT",
            "locus_id": "locus-background",
            "member_id": "member-background",
        },
    ]
    transcripts = [
        {
            "member_id": "member-a",
            "sequence": "ACGTTACGTTACGTTACGTT",
            "sequence_receipt_id": "receipt-transcript-a",
            "source_record": "synthetic-record-a",
            "source_version": "synthetic-v1",
            "transcript_id": "transcript-a",
        },
        {
            "member_id": "member-b",
            "sequence": "GATCCGATCCGATCCGATCC",
            "sequence_receipt_id": "receipt-transcript-b",
            "source_record": "synthetic-record-b",
            "source_version": "synthetic-v1",
            "transcript_id": "transcript-b",
        },
        {
            "member_id": "member-background",
            "sequence": "TTGCAATTGCAATTGCAATT",
            "sequence_receipt_id": "receipt-transcript-background",
            "source_record": "synthetic-record-background",
            "source_version": "synthetic-v1",
            "transcript_id": "transcript-background",
        },
    ]
    observations = [
        {
            "biological_unit_id": "biological-unit-1",
            "condition_id": "condition-a",
            "independence_receipt_id": "receipt-observation-1",
            "independence_state": "RECEIPT_VERIFIED",
            "observation_id": "observation-1",
            "parent_observation_id": None,
        },
        {
            "biological_unit_id": "biological-unit-2",
            "condition_id": "condition-a",
            "independence_receipt_id": "receipt-observation-2",
            "independence_state": "RECEIPT_VERIFIED",
            "observation_id": "observation-2",
            "parent_observation_id": None,
        },
    ]
    equivalence_classes = [
        {
            "counts": {"observation-1": 12, "observation-2": 18},
            "ec_id": "class-member-a",
            "evidence_receipt_ids": ["receipt-class-member-a"],
            "transcript_ids": ["transcript-a"],
        },
        {
            "counts": {"observation-1": 7, "observation-2": 9},
            "ec_id": "class-member-b",
            "evidence_receipt_ids": ["receipt-class-member-b"],
            "transcript_ids": ["transcript-b"],
        },
        {
            "counts": {"observation-1": 3, "observation-2": 4},
            "ec_id": "class-family-ambiguous",
            "evidence_receipt_ids": ["receipt-class-family-ambiguous"],
            "transcript_ids": ["transcript-a", "transcript-b"],
        },
        {
            "counts": {"observation-1": 2, "observation-2": 1},
            "ec_id": "class-background",
            "evidence_receipt_ids": ["receipt-class-background"],
            "transcript_ids": ["transcript-background"],
        },
    ]
    reference_scope = {
        "competitive_background_state": "RECEIPT_VERIFIED_COMPLETE",
        "competitive_member_ids": ["member-a", "member-b", "member-background"],
        "family_id": "synthetic-family",
        "family_member_ids": ["member-a", "member-b"],
        "kmer_size": 5,
        "scope_receipt_ids": ["receipt-reference"],
    }
    receipts = []
    for member in members:
        receipts.append(
            receipt(
                member["identity_receipt_ids"][0],
                "MEMBER_IDENTITY",
                f"{member['member_id']}-identity",
                canonical_digest(
                    {"locus_id": member["locus_id"], "member_id": member["member_id"]}
                ),
            )
        )
    for transcript in transcripts:
        receipts.append(
            receipt(
                transcript["sequence_receipt_id"],
                "TRANSCRIPT_SEQUENCE",
                transcript["source_record"],
                hashlib.sha256(transcript["sequence"].encode("utf-8")).hexdigest(),
            )
        )
    receipts.append(
        receipt(
            "receipt-reference",
            "REFERENCE_SCOPE",
            "synthetic-competitive-reference",
            canonical_digest(
                {
                    key: reference_scope[key]
                    for key in (
                        "competitive_background_state",
                        "competitive_member_ids",
                        "family_id",
                        "family_member_ids",
                        "kmer_size",
                    )
                }
            ),
        )
    )
    for observation in observations:
        receipts.append(
            receipt(
                observation["independence_receipt_id"],
                "OBSERVATION_UNIT",
                f"{observation['observation_id']}-origin",
                canonical_digest(
                    {
                        key: observation[key]
                        for key in (
                            "biological_unit_id",
                            "condition_id",
                            "observation_id",
                            "parent_observation_id",
                        )
                    }
                ),
            )
        )
    for equivalence_class in equivalence_classes:
        receipts.append(
            receipt(
                equivalence_class["evidence_receipt_ids"][0],
                "EQUIVALENCE_CLASS",
                f"{equivalence_class['ec_id']}-evidence",
                canonical_digest(
                    {
                        "counts": equivalence_class["counts"],
                        "ec_id": equivalence_class["ec_id"],
                        "transcript_ids": equivalence_class["transcript_ids"],
                    }
                ),
            )
        )
    return {
        "bound_memory_head_sha256": None,
        "equivalence_classes": equivalence_classes,
        "members": members,
        "observation_units": observations,
        "reference_scope": reference_scope,
        "schema_version": "phytoparalog.study.v0.1",
        "source_receipts": receipts,
        "species": "Synthetic plant model",
        "stock_id": "synthetic-stock",
        "study_id": FIXTURE_ID,
        "target_selection": dict(TARGET_SELECTION),
        "transcripts": transcripts,
    }


def _core() -> dict[str, Any]:
    """Import the optional scientific core only when an operation runs."""

    from phytoparalog import (
        Study,
        ValidationError,
        __version__,
        compile_capsule,
        compile_study,
        validate_capsule,
    )
    from phytoparalog.engine import canonical_json_bytes, sha256_bytes

    return {
        "Study": Study,
        "ValidationError": ValidationError,
        "version": __version__,
        "compile_capsule": compile_capsule,
        "compile_study": compile_study,
        "validate_capsule": validate_capsule,
        "canonical_json_bytes": canonical_json_bytes,
        "sha256_bytes": sha256_bytes,
    }


def _select_study(arguments: dict[str, Any], core: dict[str, Any]) -> Any:
    study_value = arguments.get("study")
    fixture_id = arguments.get("fixture_id")
    supplied = (study_value is not None) + (fixture_id is not None)
    if supplied != 1:
        raise ValueError("Supply exactly one of 'study' or 'fixture_id'.")
    if fixture_id is not None:
        if fixture_id != FIXTURE_ID:
            raise ValueError(f"Unknown fixture_id; the packaged fixture is {FIXTURE_ID!r}.")
        study_value = _fixture_payload()
    return core["Study"].from_dict(study_value)


def _compile_summary(study: Any, core: dict[str, Any]) -> dict[str, Any]:
    compiled = core["compile_study"](study)
    documents = compiled.documents()
    digests = {
        name: core["sha256_bytes"](core["canonical_json_bytes"](document))
        for name, document in sorted(documents.items())
    }
    identifiability = compiled.identifiability
    return {
        "authority": "IDENTIFIABILITY_EVIDENCE_ONLY",
        "core_version": core["version"],
        "document_sha256": digests,
        "hold_reasons": list(identifiability["hold_reasons"]),
        "producer_status": identifiability["producer_status"],
        "schema_versions": {
            name: document["schema_version"] for name, document in sorted(documents.items())
        },
        "study_id": study.study_id,
    }


def _capsule_summary(
    capsule_dir: Path,
    core: dict[str, Any],
    *,
    study: Any = None,
    expected_capsule_digest: str | None = None,
) -> dict[str, Any]:
    validation = core["validate_capsule"](
        capsule_dir,
        study=study,
        expected_capsule_digest=expected_capsule_digest,
    )
    validation_mode = validation["status"]
    if validation_mode not in {"STUDY_RECOMPUTED", "EXTERNAL_DIGEST_ANCHORED"}:
        raise ValueError("Trusted validation requires an original study or external digest anchor.")
    summary = {
        "capsule_digest": validation["capsule_digest"],
        "capsule_valid": True,
        "capsule_semantics_trusted": validation_mode == "STUDY_RECOMPUTED",
        "core_version": core["version"],
        "document_count": validation["file_count"],
        "validation_authority": (
            "STUDY_RECOMPUTED_STRUCTURE_AND_SEMANTICS"
            if validation_mode == "STUDY_RECOMPUTED"
            else "EXTERNALLY_ANCHORED_INTEGRITY_ONLY"
        ),
        "validation_mode": validation_mode,
    }
    if validation_mode == "STUDY_RECOMPUTED":
        identifiability = core["compile_study"](study).identifiability
        summary.update(
            {
                "hold_reasons": list(identifiability["hold_reasons"]),
                "producer_status": identifiability["producer_status"],
            }
        )
    return summary


@register_tool("PhytoParalogTool")
class PhytoParalogTool(BaseTool):
    """Dispatch the three configured ToolUniverse operations."""

    def __init__(self, tool_config: dict[str, Any]):
        super().__init__(tool_config)
        self.operation = self.tool_config.get("phytoparalog_operation", "")

    def validate_parameters(self, arguments: dict[str, Any]) -> None:
        """Defer validation to ``run`` so errors always use the public adapter envelope."""

        return None

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return a structured result; never propagate an operational exception."""

        operation = self.operation
        try:
            if not isinstance(arguments, dict):
                raise ValueError("Arguments must be an object.")
            if operation not in {"preflight", "compile", "validate_capsule"}:
                return _error(
                    "UNKNOWN_OPERATION",
                    "The configured operation is not supported.",
                    "Use a packaged PhytoParalog tool configuration.",
                )
            _validate_adapter_arguments(arguments, operation)
            core = _core()
            if operation == "preflight":
                return self._preflight(arguments, core)
            if operation == "compile":
                return self._compile(arguments, core)
            return self._validate_capsule(arguments, core)
        except ModuleNotFoundError:
            return _error(
                "DEPENDENCY_MISSING",
                "PhytoParalog or ToolUniverse is not installed in the active environment.",
                "Install the package with the 'tooluniverse' optional dependency.",
            )
        except ValueError as exc:
            is_core_validation = exc.__class__.__name__ == "ValidationError"
            if is_core_validation and operation == "validate_capsule":
                code = "CAPSULE_INVALID"
                message = "Capsule validation failed against the supplied trusted anchor."
                remediation = "Recreate the capsule from the original validated study."
            elif is_core_validation:
                code = "INVALID_STUDY"
                message = "Study validation failed under the closed PhytoParalog schema."
                remediation = "Correct the closed study object or its receipt bindings."
            else:
                code = "INVALID_ARGUMENTS"
                message = str(exc)
                remediation = (
                    "Correct the named argument or use the packaged synthetic fixture "
                    "to verify setup."
                )
            return _error(
                code,
                message,
                remediation,
            )
        except (FileNotFoundError, NotADirectoryError):
            return _error(
                "CAPSULE_NOT_FOUND",
                "The capsule directory or a required capsule file was not found.",
                "Provide a directory containing exactly the five PhytoParalog capsule files.",
            )
        except (OSError, json.JSONDecodeError) as exc:
            return _error(
                "CAPSULE_INVALID",
                f"Capsule validation failed: {exc.__class__.__name__}.",
                "Recreate the capsule from validated input and do not alter its files.",
            )
        except Exception:
            return _error(
                "INTERNAL_ERROR",
                "PhytoParalog could not complete the operation.",
                "Run the CLI with the same synthetic fixture and report a minimal reproduction.",
            )

    @staticmethod
    def _preflight(arguments: dict[str, Any], core: dict[str, Any]) -> dict[str, Any]:
        study = _select_study(arguments, core)
        return _success(
            {
                "authority": "INPUT_VALIDATION_ONLY",
                "competitive_member_count": len(study.reference_scope.competitive_member_ids),
                "equivalence_class_count": len(study.equivalence_classes),
                "family_member_count": len(study.reference_scope.family_member_ids),
                "member_count": len(study.members),
                "observation_count": len(study.observation_units),
                "schema_version": study.schema_version,
                "study_id": study.study_id,
                "transcript_count": len(study.transcripts),
                "validated": True,
            }
        )

    @staticmethod
    def _compile(arguments: dict[str, Any], core: dict[str, Any]) -> dict[str, Any]:
        study = _select_study(arguments, core)
        return _success(_compile_summary(study, core))

    @staticmethod
    def _validate_capsule(arguments: dict[str, Any], core: dict[str, Any]) -> dict[str, Any]:
        capsule_value = arguments.get("capsule_dir")
        study_value = arguments.get("study")
        expected_digest = arguments.get("expected_capsule_digest")
        fixture_id = arguments.get("fixture_id")
        if fixture_id is not None:
            if any(value is not None for value in (capsule_value, study_value, expected_digest)):
                raise ValueError("fixture_id cannot be combined with capsule or anchor fields.")
            if fixture_id != FIXTURE_ID:
                raise ValueError(f"Unknown fixture_id; the packaged fixture is {FIXTURE_ID!r}.")
            with tempfile.TemporaryDirectory(prefix="phytoparalog-fixture-") as temporary:
                output_dir = Path(temporary) / "capsule"
                fixture = _fixture_payload()
                frozen_fixture = core["Study"].from_dict(fixture)
                core["compile_capsule"](frozen_fixture, output_dir)
                return _success(_capsule_summary(output_dir, core, study=frozen_fixture))
        if capsule_value is None:
            raise ValueError("Supply capsule_dir with exactly one trusted anchor, or fixture_id.")
        anchor_count = (study_value is not None) + (expected_digest is not None)
        if anchor_count != 1:
            raise ValueError(
                "Supply exactly one trusted capsule anchor: 'study' or 'expected_capsule_digest'."
            )
        capsule_dir = Path(capsule_value)
        if not capsule_dir.is_dir():
            raise NotADirectoryError
        frozen_study = core["Study"].from_dict(study_value) if study_value is not None else None
        return _success(
            _capsule_summary(
                capsule_dir,
                core,
                study=frozen_study,
                expected_capsule_digest=expected_digest,
            )
        )
