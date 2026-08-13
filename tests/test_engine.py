from __future__ import annotations

import hashlib
import json
from pathlib import Path

from phytoparalog.engine import compile_study
from phytoparalog.models import Study

FIXTURE = Path(__file__).parents[1] / "examples" / "synthetic" / "study.json"


def study_dict() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _receipt(value: dict, receipt_id: str) -> dict:
    return next(item for item in value["source_receipts"] if item["receipt_id"] == receipt_id)


def test_conservative_member_and_family_bounds() -> None:
    compiled = compile_study(Study.from_dict(study_dict()))
    assert compiled.identifiability["producer_status"] == "HOLD"
    assert "EXTERNAL_RECEIPT_AUTHORITY_NOT_ESTABLISHED" in compiled.identifiability["hold_reasons"]
    observation = compiled.identifiability["observations"][0]
    bounds = {item["member_id"]: item for item in observation["member_bounds"]}
    assert (bounds["FAM_A"]["lower_count"], bounds["FAM_A"]["upper_count"]) == (None, None)
    assert (
        bounds["FAM_A"]["technical_lower_count"],
        bounds["FAM_A"]["technical_upper_count"],
    ) == (5, 7)
    assert (
        bounds["FAM_B"]["technical_lower_count"],
        bounds["FAM_B"]["technical_upper_count"],
    ) == (4, 6)
    assert bounds["FAM_A"]["quantitative_resolution"] == "NONE"
    assert observation["family_bounds"]["admissible_lower_count"] is None
    assert observation["family_bounds"]["admissible_upper_count"] is None
    assert observation["family_bounds"]["technical_lower_count"] == 11
    assert observation["family_bounds"]["technical_upper_count"] == 11


def test_family_only_reference_never_establishes_member_discriminator() -> None:
    compiled = compile_study(study_dict())
    assert {
        row["reference_state"]
        for row in compiled.identifiability["reference_diagnostics"]["members"]
    } == {"COMPETITIVE_BACKGROUND_MISSING"}
    assert "COMPETITIVE_BACKGROUND_MISSING" in compiled.identifiability["hold_reasons"]


def test_empty_observations_and_equivalence_classes_hold() -> None:
    value = study_dict()
    value["observation_units"] = []
    value["equivalence_classes"] = []
    value["source_receipts"] = [
        receipt
        for receipt in value["source_receipts"]
        if receipt["receipt_type"] not in {"OBSERVATION_UNIT", "EQUIVALENCE_CLASS"}
    ]
    compiled = compile_study(value)
    assert compiled.identifiability["producer_status"] == "HOLD"
    assert {"NO_OBSERVATIONS", "NO_EQUIVALENCE_CLASSES"} <= set(
        compiled.identifiability["hold_reasons"]
    )


def test_missing_equivalence_class_dataset_is_not_an_observed_zero() -> None:
    value = study_dict()
    value["equivalence_classes"] = []
    value["source_receipts"] = [
        receipt
        for receipt in value["source_receipts"]
        if receipt["receipt_type"] != "EQUIVALENCE_CLASS"
    ]
    compiled = compile_study(value)
    assert "NO_EQUIVALENCE_CLASSES" in compiled.identifiability["hold_reasons"]
    for observation in compiled.identifiability["observations"]:
        assert observation["family_bounds"]["technical_lower_count"] is None
        assert observation["family_bounds"]["technical_upper_count"] is None
        for bound in observation["member_bounds"]:
            assert bound["technical_observed_state"] == "NOT_ASSESSED"
            assert bound["technical_lower_count"] is None
            assert bound["technical_upper_count"] is None
            assert bound["technical_quantitative_resolution"] == "NONE"


def test_reused_biological_unit_holds() -> None:
    value = study_dict()
    observation = value["observation_units"][1]
    observation["biological_unit_id"] = value["observation_units"][0]["biological_unit_id"]
    subject = {
        "biological_unit_id": observation["biological_unit_id"],
        "condition_id": observation["condition_id"],
        "observation_id": observation["observation_id"],
        "parent_observation_id": observation["parent_observation_id"],
    }
    digest = hashlib.sha256(
        (json.dumps(subject, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    receipt = _receipt(value, observation["independence_receipt_id"])
    receipt["subject_sha256"] = digest
    receipt["artifact_sha256"] = digest
    compiled = compile_study(value)
    assert "BIOLOGICAL_UNIT_REUSED_ACROSS_OBSERVATIONS" in compiled.identifiability["hold_reasons"]


def test_member_set_aggregation_preserves_ec_and_receipt_provenance() -> None:
    compiled = compile_study(study_dict())
    shared = next(
        item
        for item in compiled.identifiability["member_set_counts"]
        if item["member_ids"] == ["FAM_A", "FAM_B"]
    )
    assert shared["constituent_ec_ids"] == ["EC_SHARED"]
    assert shared["evidence_receipt_claims_well_formed"] is True
    assert shared["external_evidence_authority_established"] is False
    assert len(shared["evidence_receipt_commitments"]) == 1


def test_exact_cross_member_duplicate_forces_copy_collapsed_and_family_resolution() -> None:
    value = study_dict()
    sequence = value["transcripts"][0]["sequence"]
    value["transcripts"][1]["sequence"] = sequence
    digest = hashlib.sha256(sequence.encode("utf-8")).hexdigest()
    receipt = _receipt(value, "REC_TX_B")
    receipt["subject_sha256"] = digest
    receipt["artifact_sha256"] = digest
    compiled = compile_study(Study.from_dict(value))
    identity = {item["member_id"]: item for item in compiled.identifiability["identity"]}
    assert identity["FAM_A"]["effective_identity_state"] == "COPY_COLLAPSED"
    assert identity["FAM_B"]["effective_identity_state"] == "COPY_COLLAPSED"
    for observation in compiled.identifiability["observations"]:
        for bounds in observation["member_bounds"]:
            assert bounds["lower_count"] is None
            assert bounds["technical_lower_count"] == 0
            assert bounds["quantitative_resolution"] == "NONE"
    assert compiled.identifiability["producer_status"] == "HOLD"


def test_declared_complete_reference_cannot_earn_member_resolution() -> None:
    value = study_dict()
    value["reference_scope"]["competitive_background_state"] = "DECLARED_COMPLETE"
    subject = {
        key: value["reference_scope"][key]
        for key in (
            "competitive_background_state",
            "competitive_member_ids",
            "family_id",
            "family_member_ids",
            "kmer_size",
        )
    }
    digest = hashlib.sha256(
        (json.dumps(subject, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    _receipt(value, "REC_SCOPE")["subject_sha256"] = digest
    compiled = compile_study(value)
    states = {
        item["reference_state"]
        for item in compiled.identifiability["reference_diagnostics"]["members"]
    }
    assert states == {"COMPETITIVE_BACKGROUND_MISSING"}
    assert compiled.identifiability["producer_status"] == "HOLD"


def test_unverified_ec_evidence_forces_not_assessed() -> None:
    value = study_dict()
    _receipt(value, "REC_EC_SHARED")["verification_state"] = "DECLARED_NOT_VERIFIED"
    compiled = compile_study(value)
    assert compiled.identifiability["producer_status"] == "HOLD"
    assert "SOURCE_RECEIPT_NOT_VERIFIED" in compiled.identifiability["hold_reasons"]
    assert {
        bounds["observed_state"]
        for observation in compiled.identifiability["observations"]
        for bounds in observation["member_bounds"]
    } == {"NOT_ASSESSED"}
    assert {
        bounds["quantitative_resolution"]
        for observation in compiled.identifiability["observations"]
        for bounds in observation["member_bounds"]
    } == {"NONE"}


def test_no_compatible_fragments_is_not_biological_absence() -> None:
    value = study_dict()
    for ec in value["equivalence_classes"]:
        ec["counts"] = {key: 0 for key in ec["counts"]}
        subject = {
            "counts": dict(sorted(ec["counts"].items())),
            "ec_id": ec["ec_id"],
            "transcript_ids": sorted(ec["transcript_ids"]),
        }
        digest = hashlib.sha256(
            (json.dumps(subject, sort_keys=True, separators=(",", ":")) + "\n").encode()
        ).hexdigest()
        receipt = _receipt(value, ec["evidence_receipt_ids"][0])
        receipt["subject_sha256"] = digest
        receipt["artifact_sha256"] = digest
    compiled = compile_study(value)
    assert "NO_COMPATIBLE_FRAGMENTS_IS_NOT_ABSENCE" in compiled.identifiability["hold_reasons"]
    assert (
        "NO_COMPATIBLE_FRAGMENTS_MUST_NOT_BE_INTERPRETED_AS_BIOLOGICAL_ABSENCE"
        in compiled.identifiability["warnings"]
    )


def test_no_output_contains_target_selection_language_other_than_prohibition() -> None:
    documents = compile_study(study_dict()).documents()
    serialized = json.dumps(documents, sort_keys=True).lower()
    for forbidden in ("recommended_target", "winner", '"rank"', '"score"'):
        assert forbidden not in serialized
    assert serialized.count('"status": "prohibited"') == 4


def test_exact_duplicate_closure_is_transitive_and_order_invariant() -> None:
    value = study_dict()
    value["reference_scope"]["competitive_member_ids"].append("FAM_C")
    value["members"].append(
        {
            "identity_receipt_ids": ["REC_MEMBER_C"],
            "identity_state": "EXACT",
            "locus_id": "LOCUS_C",
            "member_id": "FAM_C",
        }
    )
    sequence_one = value["transcripts"][0]["sequence"]
    sequence_two = "AACCGGTTAACCGGT"
    value["transcripts"][1]["sequence"] = sequence_one
    value["transcripts"].extend(
        [
            {
                "member_id": "FAM_B",
                "sequence": sequence_two,
                "sequence_receipt_id": "REC_TX_B2",
                "source_record": "TX_B2",
                "source_version": "1",
                "transcript_id": "TX_B2",
            },
            {
                "member_id": "FAM_C",
                "sequence": sequence_two,
                "sequence_receipt_id": "REC_TX_C",
                "source_record": "TX_C",
                "source_version": "1",
                "transcript_id": "TX_C",
            },
        ]
    )

    def digest(item: object) -> str:
        return hashlib.sha256(
            (json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode()
        ).hexdigest()

    common = {
        "issuer": "SYNTHETIC_FIXTURE_GENERATOR",
        "source_version": "1",
        "verification_method": "SHA256_RECALCULATED",
        "verification_state": "RECEIPT_VERIFIED",
    }
    member_sha = digest({"locus_id": "LOCUS_C", "member_id": "FAM_C"})
    value["source_receipts"].append(
        {
            **common,
            "artifact_sha256": member_sha,
            "receipt_id": "REC_MEMBER_C",
            "receipt_type": "MEMBER_IDENTITY",
            "record_id": "FAM_C",
            "subject_sha256": member_sha,
        }
    )
    for receipt_id, record_id, sequence in (
        ("REC_TX_B", "TX_B", sequence_one),
        ("REC_TX_B2", "TX_B2", sequence_two),
        ("REC_TX_C", "TX_C", sequence_two),
    ):
        sequence_sha = hashlib.sha256(sequence.encode()).hexdigest()
        if receipt_id == "REC_TX_B":
            receipt = _receipt(value, receipt_id)
            receipt["artifact_sha256"] = sequence_sha
            receipt["subject_sha256"] = sequence_sha
        else:
            value["source_receipts"].append(
                {
                    **common,
                    "artifact_sha256": sequence_sha,
                    "receipt_id": receipt_id,
                    "receipt_type": "TRANSCRIPT_SEQUENCE",
                    "record_id": record_id,
                    "subject_sha256": sequence_sha,
                }
            )
    scope = value["reference_scope"]
    scope_subject = {
        key: scope[key]
        for key in (
            "competitive_background_state",
            "competitive_member_ids",
            "family_id",
            "family_member_ids",
            "kmer_size",
        )
    }
    scope_sha = digest(scope_subject)
    _receipt(value, "REC_SCOPE")["artifact_sha256"] = scope_sha
    _receipt(value, "REC_SCOPE")["subject_sha256"] = scope_sha
    ec = value["equivalence_classes"][0]
    ec["transcript_ids"] = ["TX_C"]
    ec_subject = {
        "counts": dict(sorted(ec["counts"].items())),
        "ec_id": ec["ec_id"],
        "transcript_ids": ["TX_C"],
    }
    ec_sha = digest(ec_subject)
    receipt = _receipt(value, ec["evidence_receipt_ids"][0])
    receipt["artifact_sha256"] = ec_sha
    receipt["subject_sha256"] = ec_sha

    first = compile_study(value).documents()
    reordered = json.loads(json.dumps(value))
    reordered["transcripts"].reverse()
    second = compile_study(reordered).documents()
    assert first == second
    member_sets = first["identifiability.json"]["member_set_counts"]
    assert any(row["member_ids"] == ["FAM_A", "FAM_B", "FAM_C"] for row in member_sets)


def test_outsider_crossing_ec_does_not_earn_subgroup_support() -> None:
    value = study_dict()
    value["members"].append(
        {
            "identity_receipt_ids": ["REC_MEMBER_OUT"],
            "identity_state": "UNRESOLVED",
            "locus_id": "LOCUS_OUT",
            "member_id": "OUT",
        }
    )
    value["reference_scope"]["competitive_member_ids"].append("OUT")
    out_sequence = "AACCGGTTAACCGGT"
    value["transcripts"].append(
        {
            "member_id": "OUT",
            "sequence": out_sequence,
            "sequence_receipt_id": "REC_TX_OUT",
            "source_record": "TX_OUT",
            "source_version": "1",
            "transcript_id": "TX_OUT",
        }
    )

    def canonical_digest(item: object) -> str:
        return hashlib.sha256(
            (json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n").encode()
        ).hexdigest()

    common = {
        "issuer": "SYNTHETIC_FIXTURE_GENERATOR",
        "source_version": "1",
        "verification_method": "SHA256_RECALCULATED",
        "verification_state": "RECEIPT_VERIFIED",
    }
    member_digest = canonical_digest({"locus_id": "LOCUS_OUT", "member_id": "OUT"})
    sequence_digest = hashlib.sha256(out_sequence.encode()).hexdigest()
    value["source_receipts"].extend(
        [
            {
                **common,
                "artifact_sha256": member_digest,
                "receipt_id": "REC_MEMBER_OUT",
                "receipt_type": "MEMBER_IDENTITY",
                "record_id": "OUT",
                "subject_sha256": member_digest,
            },
            {
                **common,
                "artifact_sha256": sequence_digest,
                "receipt_id": "REC_TX_OUT",
                "receipt_type": "TRANSCRIPT_SEQUENCE",
                "record_id": "TX_OUT",
                "subject_sha256": sequence_digest,
            },
        ]
    )
    scope = value["reference_scope"]
    scope_digest = canonical_digest(
        {
            key: scope[key]
            for key in (
                "competitive_background_state",
                "competitive_member_ids",
                "family_id",
                "family_member_ids",
                "kmer_size",
            )
        }
    )
    scope_receipt = _receipt(value, "REC_SCOPE")
    scope_receipt["artifact_sha256"] = scope_digest
    scope_receipt["subject_sha256"] = scope_digest
    crossing = value["equivalence_classes"][0]
    crossing["transcript_ids"] = ["TX_A", "TX_OUT"]
    subject = {
        "counts": crossing["counts"],
        "ec_id": crossing["ec_id"],
        "transcript_ids": sorted(crossing["transcript_ids"]),
    }
    digest = canonical_digest(subject)
    receipt = next(
        item
        for item in value["source_receipts"]
        if item["receipt_id"] == crossing["evidence_receipt_ids"][0]
    )
    receipt["artifact_sha256"] = digest
    receipt["subject_sha256"] = digest
    compiled = compile_study(value)
    bound = next(
        item
        for item in compiled.identifiability["observations"][0]["member_bounds"]
        if item["member_id"] == "FAM_A"
    )
    assert bound["supported_subgroup_member_ids"] == []
