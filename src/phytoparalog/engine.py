"""Deterministic paralog identifiability compiler."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .models import (
    CompetitiveBackgroundState,
    IdentityState,
    IndependenceState,
    ObservedState,
    ProducerStatus,
    QuantitativeResolution,
    ReceiptVerificationState,
    ReferenceState,
    Study,
)

TOOL_VERSION = "0.1.0"
TARGET_SELECTION = {"allowed": False, "status": "PROHIBITED"}


def canonical_json_bytes(value: Any) -> bytes:
    """Return the single canonical serialization used by locks and capsules."""

    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _commit_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class CompiledStudy:
    """The four evidence documents written before the capsule manifest."""

    study_lock: dict[str, Any]
    identifiability: dict[str, Any]
    pec_candidate_evidence: dict[str, Any]
    phytoresolve_proposed_events: dict[str, Any]

    def documents(self) -> dict[str, dict[str, Any]]:
        return {
            "identifiability.json": self.identifiability,
            "pec_candidate_evidence.json": self.pec_candidate_evidence,
            "phytoresolve_proposed_events.json": self.phytoresolve_proposed_events,
            "study_lock.json": self.study_lock,
        }


def _reverse_complement(value: str) -> str:
    return value.translate(str.maketrans("ACGT", "TGCA"))[::-1]


def _canonical_kmers(sequence: str, size: int) -> set[str]:
    kmers: set[str] = set()
    for offset in range(len(sequence) - size + 1):
        item = sequence[offset : offset + size]
        if "N" in item:
            continue
        reverse = _reverse_complement(item)
        kmers.add(min(item, reverse))
    return kmers


def _exact_sequence_components(study: Study, member_ids: set[str]) -> set[tuple[str, ...]]:
    """Return deterministic transitive components of exact-sequence aliases."""

    parent = {member_id: member_id for member_id in member_ids}

    def find(member_id: str) -> str:
        while parent[member_id] != member_id:
            parent[member_id] = parent[parent[member_id]]
            member_id = parent[member_id]
        return member_id

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    sequence_owners: dict[str, set[str]] = defaultdict(set)
    for transcript in study.transcripts:
        if transcript.member_id in member_ids:
            sequence_owners[transcript.sequence].add(transcript.member_id)
    for owners in sequence_owners.values():
        ordered = sorted(owners)
        for member_id in ordered[1:]:
            union(ordered[0], member_id)

    components: dict[str, set[str]] = defaultdict(set)
    for member_id in sorted(member_ids):
        components[find(member_id)].add(member_id)
    return {tuple(sorted(component)) for component in components.values() if len(component) > 1}


def _reference_analysis(
    study: Study,
) -> tuple[list[dict[str, Any]], dict[str, set[str]], set[tuple[str, ...]]]:
    scope = study.reference_scope
    family = set(scope.family_member_ids)
    competitive = set(scope.competitive_member_ids)
    transcript_kmers: dict[str, set[str]] = {}
    owners: dict[str, set[str]] = defaultdict(set)
    for transcript in study.transcripts:
        if transcript.member_id not in competitive:
            continue
        items = _canonical_kmers(transcript.sequence, scope.kmer_size)
        transcript_kmers[transcript.transcript_id] = items
        for item in items:
            owners[item].add(transcript.member_id)

    member_kmers: dict[str, set[str]] = defaultdict(set)
    for transcript in study.transcripts:
        if transcript.member_id in competitive:
            member_kmers[transcript.member_id].update(transcript_kmers[transcript.transcript_id])

    subgroup_sets: set[tuple[str, ...]] = set()
    for owner_set in owners.values():
        if 1 < len(owner_set) < len(family) and owner_set <= family:
            subgroup_sets.add(tuple(sorted(owner_set)))

    results: list[dict[str, Any]] = []
    states: dict[str, set[str]] = {}
    receipt_by_id = {item.receipt_id: item for item in study.source_receipts}
    scope_verified = all(
        receipt_by_id[item].verification_state is ReceiptVerificationState.RECEIPT_VERIFIED
        for item in scope.scope_receipt_ids
    )
    competitive_transcript_claims_verified = all(
        receipt_by_id[transcript.sequence_receipt_id].verification_state
        is ReceiptVerificationState.RECEIPT_VERIFIED
        for transcript in study.transcripts
        if transcript.member_id in competitive
    )
    family_only_background = competitive == family
    for member_id in sorted(family):
        all_items = member_kmers[member_id]
        unique = {item for item in all_items if owners[item] == {member_id}}
        subgroup = {
            item
            for item in all_items
            if member_id in owners[item]
            and 1 < len(owners[item]) < len(family)
            and owners[item] <= family
        }
        if (
            scope.competitive_background_state
            is not CompetitiveBackgroundState.RECEIPT_VERIFIED_COMPLETE
            or not scope_verified
            or family_only_background
        ):
            technical_state = ReferenceState.COMPETITIVE_BACKGROUND_MISSING
        elif not competitive_transcript_claims_verified:
            technical_state = ReferenceState.NOT_ASSESSED
        elif not all_items:
            technical_state = ReferenceState.FAILED
        elif unique:
            technical_state = ReferenceState.MEMBER_DISCRIMINATOR_PRESENT
        elif subgroup:
            technical_state = ReferenceState.SUBGROUP_DISCRIMINATOR_ONLY
        else:
            technical_state = ReferenceState.NO_MEMBER_DISCRIMINATOR
        if technical_state is ReferenceState.COMPETITIVE_BACKGROUND_MISSING:
            admissible_state = ReferenceState.COMPETITIVE_BACKGROUND_MISSING
        elif technical_state is ReferenceState.FAILED:
            admissible_state = ReferenceState.FAILED
        else:
            admissible_state = ReferenceState.NOT_ASSESSED
        states[member_id] = {admissible_state.value}
        results.append(
            {
                "canonical_kmer_count": len(all_items),
                "external_reference_authority_established": False,
                "member_id": member_id,
                "member_unique_kmer_count": len(unique),
                "reference_state": admissible_state.value,
                "subgroup_kmer_count": len(subgroup),
                "technical_reference_state": technical_state.value,
            }
        )
    return results, states, subgroup_sets


def _effective_identities(
    study: Study,
) -> tuple[list[dict[str, Any]], dict[str, IdentityState], set[tuple[str, ...]]]:
    family = set(study.reference_scope.family_member_ids)
    competitive = set(study.reference_scope.competitive_member_ids)
    components = _exact_sequence_components(study, competitive)
    duplicate_members: dict[str, set[str]] = defaultdict(set)
    for component in components:
        component_set = set(component)
        for member_id in component_set & family:
            duplicate_members[member_id].update(component_set - {member_id})
    collapsed_groups = {component for component in components if set(component) <= family}

    declared = {item.member_id: item.identity_state for item in study.members}
    members = {item.member_id: item for item in study.members}
    receipt_by_id = {item.receipt_id: item for item in study.source_receipts}
    effective: dict[str, IdentityState] = {}
    results: list[dict[str, Any]] = []
    for member_id in sorted(family):
        technical_state = declared[member_id]
        receipt_claims_verified = all(
            receipt_by_id[item].verification_state is ReceiptVerificationState.RECEIPT_VERIFIED
            for item in members[member_id].identity_receipt_ids
        )
        if duplicate_members[member_id]:
            technical_state = IdentityState.COPY_COLLAPSED
            admissible_state = IdentityState.COPY_COLLAPSED
        elif technical_state is IdentityState.CONFLICT:
            admissible_state = IdentityState.CONFLICT
        elif technical_state is IdentityState.COPY_COLLAPSED:
            admissible_state = IdentityState.COPY_COLLAPSED
        else:
            admissible_state = IdentityState.UNRESOLVED
        effective[member_id] = admissible_state
        results.append(
            {
                "copy_collapsed_with": sorted(duplicate_members[member_id]),
                "declared_identity_state": declared[member_id].value,
                "effective_identity_state": admissible_state.value,
                "external_identity_authority_established": False,
                "identity_receipt_claims_well_formed": receipt_claims_verified,
                "member_id": member_id,
                "technical_identity_state": technical_state.value,
            }
        )
    return results, effective, collapsed_groups


def _sum_counts(
    groups: Mapping[tuple[str, ...], Mapping[str, int]],
    observation_id: str,
    predicate: Any,
) -> int:
    return sum(
        counts[observation_id] for members, counts in groups.items() if predicate(set(members))
    )


def _resolution(
    *,
    identity: IdentityState,
    reference: ReferenceState,
    observed: ObservedState,
    has_subgroup: bool,
    upper: int,
) -> QuantitativeResolution:
    # A compatibility bound is meaningful only when the reference and the
    # observed EC evidence were actually assessed.  In particular, do not let
    # an unverified EC or an incomplete competitive background fall through to
    # a reassuring-looking family/subgroup result.
    if reference in {
        ReferenceState.COMPETITIVE_BACKGROUND_MISSING,
        ReferenceState.NOT_ASSESSED,
        ReferenceState.FAILED,
    } or observed in {ObservedState.NOT_ASSESSED, ObservedState.FAILED}:
        return QuantitativeResolution.NONE
    if (
        identity is IdentityState.EXACT
        and reference is ReferenceState.MEMBER_DISCRIMINATOR_PRESENT
        and observed is ObservedState.EXACT_MEMBER_COUNTS
    ):
        return QuantitativeResolution.MEMBER_EXACT
    if (
        identity is IdentityState.EXACT
        and reference is ReferenceState.MEMBER_DISCRIMINATOR_PRESENT
        and observed is ObservedState.BOUNDED_MEMBER_COUNTS
    ):
        return QuantitativeResolution.MEMBER_BOUNDED
    if upper > 0 and has_subgroup and identity is IdentityState.EXACT:
        return QuantitativeResolution.SUBGROUP
    if upper > 0:
        return QuantitativeResolution.FAMILY_SUM
    return QuantitativeResolution.NONE


def _observation_analysis(
    study: Study,
    effective: Mapping[str, IdentityState],
    reference_rows: Iterable[Mapping[str, Any]],
    subgroup_sets: set[tuple[str, ...]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    transcript_member = {item.transcript_id: item.member_id for item in study.transcripts}
    observations = sorted(study.observation_units, key=lambda item: item.observation_id)
    family = set(study.reference_scope.family_member_ids)
    receipt_by_id = {item.receipt_id: item for item in study.source_receipts}
    reference = {row["member_id"]: ReferenceState(row["reference_state"]) for row in reference_rows}
    technical_reference = {
        row["member_id"]: ReferenceState(row["technical_reference_state"]) for row in reference_rows
    }
    technical_identity = {
        row.member_id: row.identity_state for row in study.members if row.member_id in family
    }
    duplicate_closures = [
        set(component)
        for component in _exact_sequence_components(
            study, set(study.reference_scope.competitive_member_ids)
        )
    ]
    for closure in duplicate_closures:
        for member_id in closure & family:
            technical_identity[member_id] = IdentityState.COPY_COLLAPSED

    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    for ec in study.equivalence_classes:
        ec_members = {transcript_member[item] for item in ec.transcript_ids}
        for closure in duplicate_closures:
            if ec_members & closure:
                ec_members.update(closure)
        member_set = tuple(sorted(ec_members))
        if member_set not in grouped:
            grouped[member_set] = {
                "counts": {item.observation_id: 0 for item in observations},
                "ec_ids": [],
                "receipt_ids": set(),
                "verified": True,
            }
        for observation_id, count in ec.counts.items():
            grouped[member_set]["counts"][observation_id] += count
        grouped[member_set]["ec_ids"].append(ec.ec_id)
        grouped[member_set]["receipt_ids"].update(ec.evidence_receipt_ids)
        grouped[member_set]["verified"] = grouped[member_set]["verified"] and all(
            receipt_by_id[item].verification_state is ReceiptVerificationState.RECEIPT_VERIFIED
            for item in ec.evidence_receipt_ids
        )
        if 1 < len(member_set) < len(family) and set(member_set) <= family:
            subgroup_sets.add(member_set)

    member_set_rows = [
        {
            "admissible_counts": None,
            "constituent_ec_ids": sorted(details["ec_ids"]),
            "external_evidence_authority_established": False,
            "evidence_receipt_commitments": sorted(
                _commit_text(item) for item in details["receipt_ids"]
            ),
            "evidence_receipt_claims_well_formed": details["verified"],
            "member_ids": list(member_set),
            "technical_counts": dict(sorted(details["counts"].items())),
        }
        for member_set, details in sorted(grouped.items())
    ]
    count_groups = {members: details["counts"] for members, details in grouped.items()}
    ec_dataset_present = bool(study.equivalence_classes)

    observation_rows: list[dict[str, Any]] = []
    for observation in observations:
        technical_independence = observation.independence_state
        effective_independence = (
            IndependenceState.MISSING
            if observation.independence_state is IndependenceState.MISSING
            else IndependenceState.DECLARED_NOT_VERIFIED
        )
        member_bounds: list[dict[str, Any]] = []
        for member_id in sorted(family):
            lower = _sum_counts(
                count_groups,
                observation.observation_id,
                lambda members, m=member_id: members == {m},
            )
            upper = _sum_counts(
                count_groups, observation.observation_id, lambda members, m=member_id: m in members
            )
            positive_member_sets = [
                set(observed_members)
                for observed_members, counts in count_groups.items()
                if counts[observation.observation_id] > 0 and member_id in observed_members
            ]
            supported_subgroups = sorted(
                group
                for group in subgroup_sets
                if member_id in group
                and positive_member_sets
                and all(member_set <= set(group) for member_set in positive_member_sets)
            )
            containing_subgroup = bool(supported_subgroups)
            if not ec_dataset_present:
                technical_observed = ObservedState.NOT_ASSESSED
            elif upper == 0:
                technical_observed = ObservedState.NO_COMPATIBLE_FRAGMENTS
            elif any(
                not details["verified"] and member_id in members
                for members, details in grouped.items()
            ):
                technical_observed = ObservedState.NOT_ASSESSED
            elif lower == upper:
                technical_observed = ObservedState.EXACT_MEMBER_COUNTS
            elif lower > 0:
                technical_observed = ObservedState.BOUNDED_MEMBER_COUNTS
            elif containing_subgroup:
                technical_observed = ObservedState.SUBGROUP_ONLY
            else:
                technical_observed = ObservedState.FAMILY_ONLY
            technical_resolution = (
                _resolution(
                    identity=technical_identity[member_id],
                    reference=technical_reference[member_id],
                    observed=technical_observed,
                    has_subgroup=containing_subgroup,
                    upper=upper,
                )
                if ec_dataset_present
                else QuantitativeResolution.NONE
            )
            observed = ObservedState.NOT_ASSESSED
            resolution = _resolution(
                identity=effective[member_id],
                reference=reference[member_id],
                observed=observed,
                has_subgroup=False,
                upper=0,
            )
            member_bounds.append(
                {
                    "admissibility": "EXTERNAL_RECEIPT_AUTHORITY_NOT_ESTABLISHED",
                    "lower_count": None,
                    "member_id": member_id,
                    "observed_state": observed.value,
                    "quantitative_resolution": resolution.value,
                    "supported_subgroup_member_ids": [list(group) for group in supported_subgroups],
                    "technical_lower_count": lower if ec_dataset_present else None,
                    "technical_observed_state": technical_observed.value,
                    "technical_quantitative_resolution": technical_resolution.value,
                    "technical_upper_count": upper if ec_dataset_present else None,
                    "upper_count": None,
                }
            )

        subgroup_bounds: list[dict[str, Any]] = []
        for group in sorted(subgroup_sets):
            group_set = set(group)
            lower = _sum_counts(
                count_groups,
                observation.observation_id,
                lambda members, g=group_set: bool(members) and members <= g,
            )
            upper = _sum_counts(
                count_groups,
                observation.observation_id,
                lambda members, g=group_set: bool(members & g),
            )
            subgroup_bounds.append(
                {
                    "admissible_lower_count": None,
                    "admissible_upper_count": None,
                    "member_ids": list(group),
                    "supported_by_contained_observation": bool(
                        positive_for_group := [
                            set(observed_members)
                            for observed_members, counts in count_groups.items()
                            if counts[observation.observation_id] > 0
                            and bool(set(observed_members) & group_set)
                        ]
                    )
                    and all(member_set <= group_set for member_set in positive_for_group),
                    "technical_lower_count": lower if ec_dataset_present else None,
                    "technical_upper_count": upper if ec_dataset_present else None,
                }
            )
        family_lower = _sum_counts(
            count_groups,
            observation.observation_id,
            lambda members: bool(members) and members <= family,
        )
        family_upper = _sum_counts(
            count_groups,
            observation.observation_id,
            lambda members: bool(members & family),
        )
        observation_rows.append(
            {
                "biological_unit_id": observation.biological_unit_id,
                "condition_id": observation.condition_id,
                "family_bounds": {
                    "admissible_lower_count": None,
                    "admissible_upper_count": None,
                    "family_id": study.reference_scope.family_id,
                    "technical_lower_count": family_lower if ec_dataset_present else None,
                    "technical_upper_count": family_upper if ec_dataset_present else None,
                },
                "independence_receipt_commitment": (
                    _commit_text(observation.independence_receipt_id)
                    if observation.independence_receipt_id is not None
                    else None
                ),
                "independence_state": effective_independence.value,
                "external_independence_authority_established": False,
                "member_bounds": member_bounds,
                "observation_id": observation.observation_id,
                "parent_observation_id": observation.parent_observation_id,
                "subgroup_bounds": subgroup_bounds,
                "technical_independence_state": technical_independence.value,
            }
        )
    return (
        observation_rows,
        member_set_rows,
        [{"member_ids": list(group)} for group in sorted(subgroup_sets)],
    )


def _producer_status(
    study: Study,
    identity_rows: Iterable[Mapping[str, Any]],
    reference_rows: Iterable[Mapping[str, Any]],
    observation_rows: Iterable[Mapping[str, Any]],
) -> tuple[ProducerStatus, list[str]]:
    hold_reasons: set[str] = set()
    # Receipt fields arrive inside the caller-controlled study document.  The
    # compiler checks their types, hashes, and subject bindings, but it cannot
    # authenticate the asserted issuer or signature without an external trust
    # anchor.  Keep the producer on HOLD; an independent consumer (for example
    # PEC) may later validate those receipts under its own authority policy.
    hold_reasons.add("EXTERNAL_RECEIPT_AUTHORITY_NOT_ESTABLISHED")
    if not study.observation_units:
        hold_reasons.add("NO_OBSERVATIONS")
    if not study.equivalence_classes:
        hold_reasons.add("NO_EQUIVALENCE_CLASSES")
    if (
        study.reference_scope.competitive_background_state
        is not CompetitiveBackgroundState.RECEIPT_VERIFIED_COMPLETE
    ):
        hold_reasons.add("COMPETITIVE_BACKGROUND_MISSING")
    for row in identity_rows:
        if row["effective_identity_state"] != IdentityState.EXACT.value:
            hold_reasons.add("MEMBER_IDENTITY_NOT_EXACT")
    for row in reference_rows:
        if row["reference_state"] != ReferenceState.MEMBER_DISCRIMINATOR_PRESENT.value:
            hold_reasons.add("MEMBER_REFERENCE_NOT_DISCRIMINATING")
    accepted = {
        QuantitativeResolution.MEMBER_EXACT.value,
        QuantitativeResolution.MEMBER_BOUNDED.value,
    }
    for observation in observation_rows:
        if observation["independence_state"] != IndependenceState.RECEIPT_VERIFIED.value:
            hold_reasons.add("OBSERVATION_INDEPENDENCE_NOT_VERIFIED")
        for bounds in observation["member_bounds"]:
            if bounds["quantitative_resolution"] not in accepted:
                hold_reasons.add("MEMBER_LEVEL_OBSERVATION_NOT_ESTABLISHED")
            if bounds["technical_observed_state"] == ObservedState.NO_COMPATIBLE_FRAGMENTS.value:
                hold_reasons.add("NO_COMPATIBLE_FRAGMENTS_IS_NOT_ABSENCE")
    observation_count = len(study.observation_units)
    biological_unit_count = len(
        {observation.biological_unit_id for observation in study.observation_units}
    )
    if biological_unit_count < observation_count:
        hold_reasons.add("BIOLOGICAL_UNIT_REUSED_ACROSS_OBSERVATIONS")
    if any(
        item.verification_state is not ReceiptVerificationState.RECEIPT_VERIFIED
        for item in study.source_receipts
    ):
        hold_reasons.add("SOURCE_RECEIPT_NOT_VERIFIED")
    if hold_reasons:
        return ProducerStatus.HOLD, sorted(hold_reasons)
    return ProducerStatus.COMPILED_FOR_INDEPENDENT_REVIEW, []


def _condition_unit_counts(study: Study) -> list[dict[str, Any]]:
    by_condition: dict[str, set[str]] = defaultdict(set)
    receipt_claimed_by_condition: dict[str, set[str]] = defaultdict(set)
    for observation in study.observation_units:
        by_condition[observation.condition_id].add(observation.biological_unit_id)
        if (
            observation.independence_state is IndependenceState.RECEIPT_VERIFIED
            and observation.independence_receipt_id is not None
        ):
            receipt_claimed_by_condition[observation.condition_id].add(
                observation.biological_unit_id
            )
    return [
        {
            "condition_id": condition,
            "externally_verified_independent_biological_unit_count": 0,
            "receipt_claimed_independent_biological_unit_count": len(
                receipt_claimed_by_condition[condition]
            ),
            "technical_distinct_biological_unit_count": len(unit_ids),
        }
        for condition, unit_ids in sorted(by_condition.items())
    ]


def _study_lock(study: Study) -> dict[str, Any]:
    normalized = study.to_dict()
    transcript_commitments = [
        {
            "member_id": transcript.member_id,
            "sequence_length": len(transcript.sequence),
            "sequence_sha256": _commit_text(transcript.sequence),
            "source_record_sha256": _commit_text(transcript.source_record),
            "source_version_sha256": _commit_text(transcript.source_version),
            "transcript_id": transcript.transcript_id,
        }
        for transcript in sorted(study.transcripts, key=lambda item: item.transcript_id)
    ]
    graph = [
        {
            "biological_unit_id": observation.biological_unit_id,
            "condition_id": observation.condition_id,
            "independence_state": observation.independence_state.value,
            "observation_id": observation.observation_id,
            "parent_observation_id": observation.parent_observation_id,
        }
        for observation in sorted(study.observation_units, key=lambda item: item.observation_id)
    ]
    return {
        "bound_memory_head_sha256": study.bound_memory_head_sha256,
        "input_sha256": sha256_bytes(canonical_json_bytes(normalized)),
        "observation_unit_graph": graph,
        "producer_authority": "IDENTIFIABILITY_EVIDENCE_ONLY",
        "reference_scope": {
            "competitive_background_state": (
                study.reference_scope.competitive_background_state.value
            ),
            "competitive_member_ids": sorted(study.reference_scope.competitive_member_ids),
            "family_id": study.reference_scope.family_id,
            "family_member_ids": sorted(study.reference_scope.family_member_ids),
            "kmer_size": study.reference_scope.kmer_size,
            "scope_receipt_commitments": sorted(
                _commit_text(item) for item in study.reference_scope.scope_receipt_ids
            ),
        },
        "schema_version": "phytoparalog.study-lock.v0.1",
        "species": study.species,
        "source_receipt_commitments": [
            {
                "receipt_id_sha256": _commit_text(receipt.receipt_id),
                "record_id_sha256": _commit_text(receipt.record_id),
                "receipt_type": receipt.receipt_type.value,
                "artifact_sha256": receipt.artifact_sha256,
                "issuer_sha256": _commit_text(receipt.issuer),
                "subject_sha256": receipt.subject_sha256,
                "source_version_sha256": _commit_text(receipt.source_version),
                "verification_method": receipt.verification_method.value,
                "verification_state": receipt.verification_state.value,
            }
            for receipt in sorted(study.source_receipts, key=lambda item: item.receipt_id)
        ],
        "stock_id_sha256": _commit_text(study.stock_id),
        "study_id": study.study_id,
        "target_selection": dict(TARGET_SELECTION),
        "tool_version": TOOL_VERSION,
        "transcript_commitments": transcript_commitments,
    }


def _worst_resolution(
    rows: Iterable[Mapping[str, Any]],
    member_id: str,
    *,
    field: str = "quantitative_resolution",
) -> str:
    order = {
        QuantitativeResolution.NONE.value: 0,
        QuantitativeResolution.FAMILY_SUM.value: 1,
        QuantitativeResolution.SUBGROUP.value: 2,
        QuantitativeResolution.MEMBER_BOUNDED.value: 3,
        QuantitativeResolution.MEMBER_EXACT.value: 4,
    }
    values = [
        bounds[field]
        for row in rows
        for bounds in row["member_bounds"]
        if bounds["member_id"] == member_id
    ]
    return min(values, key=order.__getitem__) if values else QuantitativeResolution.NONE.value


def _candidate_evidence(
    study: Study,
    lock: Mapping[str, Any],
    status: ProducerStatus,
    hold_reasons: list[str],
    identity_rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
    observation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    identity = {row["member_id"]: row for row in identity_rows}
    reference = {row["member_id"]: row for row in reference_rows}
    evidence = []
    for member_id in sorted(study.reference_scope.family_member_ids):
        limitations = [
            "IDENTIFIABILITY_DOES_NOT_ESTABLISH_FUNCTION_OR_CAUSALITY",
            "EXPRESSION_EVIDENCE_DOES_NOT_ESTABLISH_PHENOTYPIC_EFFECT",
        ]
        if any(
            bound["technical_observed_state"] == ObservedState.NO_COMPATIBLE_FRAGMENTS.value
            for row in observation_rows
            for bound in row["member_bounds"]
            if bound["member_id"] == member_id
        ):
            limitations.append("NO_COMPATIBLE_FRAGMENTS_IS_NOT_BIOLOGICAL_ABSENCE")
        evidence.append(
            {
                "candidate_evidence_id": f"identifiability:{member_id}",
                "declared_identity_state": identity[member_id]["declared_identity_state"],
                "effective_identity_state": identity[member_id]["effective_identity_state"],
                "external_authority_established": False,
                "evidence_document": "identifiability.json",
                "limitations": sorted(limitations),
                "member_id": member_id,
                "proposed_only": True,
                "quantitative_resolution": _worst_resolution(observation_rows, member_id),
                "reference_state": reference[member_id]["reference_state"],
                "technical_identity_state": identity[member_id]["technical_identity_state"],
                "technical_quantitative_resolution": _worst_resolution(
                    observation_rows, member_id, field="technical_quantitative_resolution"
                ),
                "technical_reference_state": reference[member_id]["technical_reference_state"],
            }
        )
    return {
        "authority": "CANDIDATE_EVIDENCE_ONLY_NO_GATE_CLOSURE",
        "candidate_evidence": evidence,
        "hold_reasons": hold_reasons,
        "producer_status": status.value,
        "prohibited_claims": [
            "BIOLOGICAL_FUNCTION_PROVEN",
            "CAUSAL_EFFECT_PROVEN",
            "PHENOTYPIC_BENEFIT_PROVEN",
            "RIGHTS_OR_HUMAN_AUTHORITY_ESTABLISHED",
            "WET_LAB_READINESS_ESTABLISHED",
        ],
        "schema_version": "phytoparalog.pec-candidate-evidence.v0.1",
        "study_id": study.study_id,
        "study_lock_sha256": sha256_bytes(canonical_json_bytes(lock)),
        "target_selection": dict(TARGET_SELECTION),
    }


def _event_id(event_type: str, payload: Mapping[str, Any]) -> str:
    digest = sha256_bytes(canonical_json_bytes({"event_type": event_type, "payload": payload}))
    return f"ppe_{digest[:24]}"


def _proposed_events(
    study: Study,
    lock: Mapping[str, Any],
    status: ProducerStatus,
    hold_reasons: list[str],
    observation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    compiled_payload = {
        "bound_memory_head_sha256": study.bound_memory_head_sha256,
        "hold_reasons": hold_reasons,
        "producer_status": status.value,
        "study_id": study.study_id,
        "study_lock_sha256": sha256_bytes(canonical_json_bytes(lock)),
    }
    events.append(
        {
            "event_type": "paralog_identifiability_compiled",
            "payload": compiled_payload,
            "proposed_event_id": _event_id("paralog_identifiability_compiled", compiled_payload),
        }
    )
    for member_id in sorted(study.reference_scope.family_member_ids):
        resolution = _worst_resolution(observation_rows, member_id)
        payload = {
            "bound_memory_head_sha256": study.bound_memory_head_sha256,
            "member_id": member_id,
            "quantitative_resolution": resolution,
            "study_id": study.study_id,
        }
        event_type = "member_identifiability_observed"
        events.append(
            {
                "event_type": event_type,
                "payload": payload,
                "proposed_event_id": _event_id(event_type, payload),
            }
        )
    return {
        "append_authority": "PHYTORESOLVE_ONLY",
        "append_precondition": {
            "expected_memory_head_sha256": study.bound_memory_head_sha256,
            "on_mismatch": "REFUSE_APPEND_STALE_HEAD",
        },
        "bound_memory_head_sha256": study.bound_memory_head_sha256,
        "events": events,
        "producer_wrote_persistent_state": False,
        "proposal_status": "PROPOSAL_ONLY",
        "schema_version": "phytoparalog.phytoresolve-proposed-events.v0.1",
        "study_id": study.study_id,
        "target_selection": dict(TARGET_SELECTION),
    }


def compile_study(value: Study | Mapping[str, Any]) -> CompiledStudy:
    """Compile a validated study without writing files or persistent state."""

    # Frozen dataclasses are still directly constructible and replaceable.  Run
    # the canonical closed-schema and relation validation for every public call.
    study = Study.from_dict(value.to_dict()) if isinstance(value, Study) else Study.from_dict(value)
    lock = _study_lock(study)
    identity_rows, effective, collapsed_groups = _effective_identities(study)
    reference_rows, _, reference_subgroups = _reference_analysis(study)
    subgroup_sets = set(reference_subgroups) | collapsed_groups
    observation_rows, member_set_rows, subgroup_rows = _observation_analysis(
        study, effective, reference_rows, subgroup_sets
    )
    status, hold_reasons = _producer_status(study, identity_rows, reference_rows, observation_rows)
    identifiability = {
        "condition_unit_counts": _condition_unit_counts(study),
        "hold_reasons": hold_reasons,
        "identity": identity_rows,
        "member_set_counts": member_set_rows,
        "observations": observation_rows,
        "producer_status": status.value,
        "reference_diagnostics": {
            "competitive_background_state": (
                study.reference_scope.competitive_background_state.value
            ),
            "kmer_size": study.reference_scope.kmer_size,
            "members": reference_rows,
        },
        "schema_version": "phytoparalog.identifiability.v0.1",
        "study_id": study.study_id,
        "subgroups": subgroup_rows,
        "target_selection": dict(TARGET_SELECTION),
        "warnings": [
            "NO_COMPATIBLE_FRAGMENTS_MUST_NOT_BE_INTERPRETED_AS_BIOLOGICAL_ABSENCE",
            "CALLER_RECEIPT_ASSERTIONS_REQUIRE_INDEPENDENT_AUTHORITY_VALIDATION",
        ],
    }
    pec = _candidate_evidence(
        study,
        lock,
        status,
        hold_reasons,
        identity_rows,
        reference_rows,
        observation_rows,
    )
    events = _proposed_events(study, lock, status, hold_reasons, observation_rows)
    return CompiledStudy(
        study_lock=lock,
        identifiability=identifiability,
        pec_candidate_evidence=pec,
        phytoresolve_proposed_events=events,
    )
