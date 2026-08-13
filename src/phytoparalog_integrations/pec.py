"""Plant Evidence Compiler adapter with a descriptive-only claim ceiling."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from phytoparalog import Study, compile_study
from phytoparalog.engine import CompiledStudy, canonical_json_bytes, sha256_bytes


class IntegrationDependencyError(RuntimeError):
    """An optional independent consumer is not installed."""


def _digest(document: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(document))


def _project_document(compiled: CompiledStudy) -> dict[str, Any]:
    lock_digest = _digest(compiled.study_lock)
    identifiability_digest = _digest(compiled.identifiability)
    project_id = f"phytoparalog-{compiled.study_lock['input_sha256'][:16]}"
    return {
        "schema_version": "1.0",
        "project": {
            "id": project_id,
            "title": "PhytoParalog identifiability provenance audit",
            "species": "Declared plant study context",
            "study_kind": "provenance_audit",
            "summary": (
                "Nonpublic provenance evidence for deterministic paralog-identifiability "
                "compilation. Identifiability is not biological function or causality."
            ),
        },
        "identities": [
            {
                "id": "study-lock-document",
                "kind": "dataset",
                "label": "Canonical PhytoParalog study lock",
                "checksum_sha256": lock_digest,
            },
            {
                "id": "identifiability-document",
                "kind": "dataset",
                "label": "Canonical PhytoParalog identifiability document",
                "checksum_sha256": identifiability_digest,
            },
        ],
        "identity_edges": [],
        "source_receipts": [
            {
                "id": "study-lock-digest-receipt",
                "kind": "file_digest",
                "title": "Canonical study-lock digest",
                "checksum_sha256": lock_digest,
                "verified": True,
                "identity_ids": ["study-lock-document"],
            },
            {
                "id": "identifiability-digest-receipt",
                "kind": "file_digest",
                "title": "Canonical identifiability-document digest",
                "checksum_sha256": identifiability_digest,
                "verified": True,
                "identity_ids": ["identifiability-document"],
            },
        ],
        "evidence": [
            {
                "id": "compiler-fixity-evidence",
                "kind": "provenance",
                "title": "Deterministic compiler fixity",
                "description": (
                    "Content digests bind the normalized study lock and derived "
                    "identifiability document without establishing biological interpretation."
                ),
                "method": "PhytoParalog deterministic canonical compilation",
                "verification": "verified",
                "receipt_ids": [
                    "study-lock-digest-receipt",
                    "identifiability-digest-receipt",
                ],
                "identity_ids": ["study-lock-document", "identifiability-document"],
                "gate_ids": ["input_provenance"],
                "claim_ids": ["identifiability-artifact-compiled"],
            }
        ],
        "gates": [
            {
                "id": "identity_lock",
                "disposition": "HOLD",
                "rationale": "Compiler fixity does not authenticate biological member identity.",
            },
            {
                "id": "input_provenance",
                "disposition": "HOLD",
                "rationale": (
                    "Compiler fixity is diagnostic candidate evidence; independent provenance "
                    "authority and adjudication remain required."
                ),
                "evidence_ids": ["compiler-fixity-evidence"],
            },
            {
                "id": "reproducibility",
                "disposition": "HOLD",
                "rationale": "Independent full-study recomputation remains required.",
            },
            {
                "id": "contradiction_review",
                "disposition": "HOLD",
                "rationale": "Independent scientific contradiction review remains required.",
            },
            {
                "id": "artifact_manifest",
                "disposition": "HOLD",
                "rationale": "The complete capsule manifest was not adjudicated by this adapter.",
            },
            {
                "id": "rights_and_licenses",
                "disposition": "HOLD",
                "rationale": "Rights and licenses require independent review.",
            },
            {
                "id": "member_identity",
                "disposition": "HOLD",
                "rationale": "Identity declarations and receipts require independent adjudication.",
            },
            {
                "id": "member_function",
                "disposition": "HOLD",
                "rationale": "Identifiability evidence does not establish biological function.",
            },
            {
                "id": "causal_interpretation",
                "disposition": "HOLD",
                "rationale": "No causal experiment is represented by this compilation.",
            },
            {
                "id": "wet_lab_readiness",
                "disposition": "HOLD",
                "rationale": "Assay qualification and wet-lab readiness were not assessed.",
            },
            {
                "id": "target_selection",
                "disposition": "HOLD",
                "rationale": "PhytoParalog prohibits target ranking and selection.",
            },
        ],
        "claims": [
            {
                "id": "identifiability-artifact-compiled",
                "statement": (
                    "A paralog-identifiability artifact was deterministically compiled "
                    "for independent review."
                ),
                "requested_level": "descriptive",
                "evidence_ids": ["compiler-fixity-evidence"],
                "public": False,
            }
        ],
        "claim_ceiling": {
            "level": "descriptive",
            "rationale": (
                "The adapter supports artifact provenance only, not member identity, function, "
                "causality, phenotype, safety, rights, readiness, or target selection."
            ),
            "evidence_ids": ["compiler-fixity-evidence"],
        },
        "contradictions": [
            {
                "id": "identifiability-is-not-function",
                "statement": (
                    "Sequence and fragment identifiability do not establish biological function."
                ),
                "severity": "major",
                "claim_ids": ["identifiability-artifact-compiled"],
                "evidence_ids": ["compiler-fixity-evidence"],
                "resolved": False,
            },
            {
                "id": "compatibility-bounds-are-not-causality",
                "statement": (
                    "Compatibility bounds are allocation bounds, not causal or phenotypic evidence."
                ),
                "severity": "major",
                "claim_ids": ["identifiability-artifact-compiled"],
                "evidence_ids": ["compiler-fixity-evidence"],
                "resolved": False,
            },
        ],
        "public_release": {
            "data_classification": "non_public",
            "contains_unpublished_sequences": True,
            "contains_personal_data": False,
            "contains_secrets": False,
        },
    }


def pec_project_spec(value: Study | Mapping[str, Any] | CompiledStudy) -> Any:
    """Return an actual conservative ``plant_evidence.models.ProjectSpec``.

    The returned project is intentionally nonpublic with a descriptive claim
    ceiling. The Plant Evidence Compiler remains the only authority that can
    adjudicate its gates and disposition.
    """

    compiled = value if isinstance(value, CompiledStudy) else compile_study(value)
    document = _project_document(compiled)
    try:
        from plant_evidence.models import ProjectSpec
    except ModuleNotFoundError as exc:
        raise IntegrationDependencyError(
            "Plant Evidence Compiler is not installed; install its supported release "
            "before calling pec_project_spec()."
        ) from exc
    return ProjectSpec.model_validate(document)
