from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from phytoparalog.models import Study, ValidationError

FIXTURE = Path(__file__).parents[1] / "examples" / "synthetic" / "study.json"


def study_dict() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_strict_study_accepts_receipt_bound_fixture() -> None:
    study = Study.from_dict(study_dict())
    assert study.study_id == "synthetic-identifiability"
    assert study.bound_memory_head_sha256 is None
    assert len(study.source_receipts) == 11


def test_direct_mapping_rejects_lone_surrogate() -> None:
    value = study_dict()
    value["study_id"] = "bad\ud800id"

    with pytest.raises(ValidationError, match="non-Unicode-scalar"):
        Study.from_dict(value)


def test_unknown_field_fails_closed() -> None:
    value = study_dict()
    value["unexpected"] = True
    with pytest.raises(ValidationError, match="unknown"):
        Study.from_dict(value)


def test_target_selection_is_structurally_prohibited() -> None:
    value = study_dict()
    value["target_selection"]["allowed"] = True
    with pytest.raises(ValidationError, match="must be"):
        Study.from_dict(value)


def test_receipt_subject_cannot_launder_changed_sequence() -> None:
    value = study_dict()
    value["transcripts"][0]["sequence"] = "AAAAACCCCCGGGGA"
    with pytest.raises(ValidationError, match="sequence checksum mismatch"):
        Study.from_dict(value)


def test_receipts_are_typed_and_bound() -> None:
    value = study_dict()
    receipt = next(item for item in value["source_receipts"] if item["receipt_id"] == "REC_TX_A")
    receipt["receipt_type"] = "MEMBER_IDENTITY"
    with pytest.raises(ValidationError, match="receipt type mismatch"):
        Study.from_dict(value)


def test_unbound_receipt_fails_closed() -> None:
    value = study_dict()
    receipt = copy.deepcopy(value["source_receipts"][0])
    receipt["receipt_id"] = "REC_UNUSED"
    value["source_receipts"].append(receipt)
    with pytest.raises(ValidationError, match="unbound receipts"):
        Study.from_dict(value)


def test_memory_head_requires_lowercase_sha256() -> None:
    value = study_dict()
    value["bound_memory_head_sha256"] = "ABC"
    with pytest.raises(ValidationError, match="lowercase SHA-256"):
        Study.from_dict(value)


def test_direct_study_instance_is_revalidated_by_compiler() -> None:
    from phytoparalog.engine import compile_study

    valid = Study.from_dict(study_dict())
    invalid = replace(
        valid,
        reference_scope=replace(
            valid.reference_scope,
            competitive_member_ids=("FAM_A", "FAM_B", "UNDECLARED"),
        ),
    )
    with pytest.raises(ValidationError, match="unknown member"):
        compile_study(invalid)


def test_transcripts_outside_competitive_scope_fail_closed() -> None:
    value = study_dict()
    value["members"].append(
        {
            "identity_receipt_ids": ["REC_MEMBER_X"],
            "identity_state": "UNRESOLVED",
            "locus_id": "LOCUS_X",
            "member_id": "MEMBER_X",
        }
    )
    value["transcripts"].append(
        {
            "member_id": "MEMBER_X",
            "sequence": "AACCGGTTAACCGGT",
            "sequence_receipt_id": "REC_TX_X",
            "source_record": "TX_X",
            "source_version": "1",
            "transcript_id": "TX_X",
        }
    )
    import hashlib
    import json

    def digest(item: object) -> str:
        return hashlib.sha256(
            (json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode()
        ).hexdigest()

    member_sha = digest({"locus_id": "LOCUS_X", "member_id": "MEMBER_X"})
    sequence_sha = hashlib.sha256(b"AACCGGTTAACCGGT").hexdigest()
    common = {
        "issuer": "SYNTHETIC_FIXTURE_GENERATOR",
        "source_version": "1",
        "verification_method": "SHA256_RECALCULATED",
        "verification_state": "DECLARED_NOT_VERIFIED",
    }
    value["source_receipts"].extend(
        [
            {
                **common,
                "artifact_sha256": member_sha,
                "receipt_id": "REC_MEMBER_X",
                "receipt_type": "MEMBER_IDENTITY",
                "record_id": "MEMBER_X",
                "subject_sha256": member_sha,
            },
            {
                **common,
                "artifact_sha256": sequence_sha,
                "receipt_id": "REC_TX_X",
                "receipt_type": "TRANSCRIPT_SEQUENCE",
                "record_id": "TX_X",
                "subject_sha256": sequence_sha,
            },
        ]
    )
    with pytest.raises(ValidationError, match="competitive_member_ids"):
        Study.from_dict(value)


def test_derived_observation_cannot_inflate_independence() -> None:
    value = study_dict()
    child = value["observation_units"][1]
    child["parent_observation_id"] = value["observation_units"][0]["observation_id"]
    subject = {
        key: child[key]
        for key in (
            "biological_unit_id",
            "condition_id",
            "observation_id",
            "parent_observation_id",
        )
    }
    digest = hashlib.sha256(
        (json.dumps(subject, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    receipt = next(
        item
        for item in value["source_receipts"]
        if item["receipt_id"] == child["independence_receipt_id"]
    )
    receipt["artifact_sha256"] = digest
    receipt["subject_sha256"] = digest
    with pytest.raises(ValidationError, match="share the parent biological_unit_id"):
        Study.from_dict(value)
