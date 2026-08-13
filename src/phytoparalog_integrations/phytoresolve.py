"""Exact-head acceptance bridge for PhytoResolve proposal events."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from phytoparalog import Study, compile_study
from phytoparalog.engine import TARGET_SELECTION, canonical_json_bytes, sha256_bytes


class InvalidProposalError(ValueError):
    """The input is not a closed PhytoParalog proposal document."""


class StaleMemoryHeadError(RuntimeError):
    """The proposal was compiled against a different memory head."""


class MemoryProjectMismatchError(RuntimeError):
    """The open memory store is not the explicitly authorized project."""


_EVENT_TYPES = {
    "paralog_identifiability_compiled": "artifact",
    # Candidate member resolutions remain artifacts awaiting independent
    # adjudication.  They must never enter persistent memory as accepted facts.
    "member_identifiability_observed": "artifact",
}
_RESOLUTIONS = {"MEMBER_EXACT", "MEMBER_BOUNDED", "SUBGROUP", "FAMILY_SUM", "NONE"}
_PRODUCER_STATUSES = {"COMPILED_FOR_INDEPENDENT_REVIEW", "HOLD", "INVALID"}


def _object(value: Any, expected: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise InvalidProposalError(f"{path}: closed-schema field mismatch")
    return value


def _digest(value: str, path: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise InvalidProposalError(f"{path}: expected lowercase SHA-256")
    return value


def _event_id(event_type: str, payload: Mapping[str, Any]) -> str:
    digest = sha256_bytes(canonical_json_bytes({"event_type": event_type, "payload": payload}))
    return f"ppe_{digest[:24]}"


def _owned_document(value: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-copy a JSON proposal into bytes owned by this integration boundary."""

    try:
        return json.loads(canonical_json_bytes(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidProposalError("proposal: expected canonical JSON-compatible values") from exc


def prepare_phytoresolve_events(proposal: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Validate a proposal completely and map it to allowed PhytoResolve events.

    This function is pure and performs no ledger mutation. It validates every
    event before the append helper acquires a write transaction.
    """

    document = _object(
        _owned_document(proposal),
        {
            "append_authority",
            "append_precondition",
            "bound_memory_head_sha256",
            "events",
            "producer_wrote_persistent_state",
            "proposal_status",
            "schema_version",
            "study_id",
            "target_selection",
        },
        "proposal",
    )
    if document["schema_version"] != "phytoparalog.phytoresolve-proposed-events.v0.1":
        raise InvalidProposalError("proposal.schema_version: unsupported value")
    if document["proposal_status"] != "PROPOSAL_ONLY":
        raise InvalidProposalError("proposal.proposal_status: expected PROPOSAL_ONLY")
    if document["append_authority"] != "PHYTORESOLVE_ONLY":
        raise InvalidProposalError("proposal.append_authority: expected PHYTORESOLVE_ONLY")
    if document["producer_wrote_persistent_state"] is not False:
        raise InvalidProposalError("proposal: producer must not claim a persistent-state write")
    if document["target_selection"] != TARGET_SELECTION:
        raise InvalidProposalError("proposal.target_selection: target selection must be prohibited")
    head = _digest(document["bound_memory_head_sha256"], "proposal.bound_memory_head_sha256")
    precondition = _object(
        document["append_precondition"],
        {"expected_memory_head_sha256", "on_mismatch"},
        "proposal.append_precondition",
    )
    if precondition["expected_memory_head_sha256"] != head:
        raise InvalidProposalError("proposal.append_precondition: memory head mismatch")
    if precondition["on_mismatch"] != "REFUSE_APPEND_STALE_HEAD":
        raise InvalidProposalError("proposal.append_precondition: unsafe mismatch policy")
    study_id = document["study_id"]
    if not isinstance(study_id, str) or not study_id.strip():
        raise InvalidProposalError("proposal.study_id: expected nonempty string")
    raw_events = document["events"]
    if not isinstance(raw_events, list) or not raw_events:
        raise InvalidProposalError("proposal.events: expected a nonempty array")

    prepared: list[dict[str, Any]] = []
    proposed_ids: set[str] = set()
    for index, raw_event in enumerate(raw_events):
        event = _object(
            raw_event,
            {"event_type", "payload", "proposed_event_id"},
            f"proposal.events[{index}]",
        )
        source_type = event["event_type"]
        if source_type not in _EVENT_TYPES:
            raise InvalidProposalError(f"proposal.events[{index}].event_type: unsupported value")
        payload = event["payload"]
        if source_type == "paralog_identifiability_compiled":
            payload = _object(
                payload,
                {
                    "bound_memory_head_sha256",
                    "hold_reasons",
                    "producer_status",
                    "study_id",
                    "study_lock_sha256",
                },
                f"proposal.events[{index}].payload",
            )
            if payload["producer_status"] not in _PRODUCER_STATUSES:
                raise InvalidProposalError(
                    f"proposal.events[{index}].payload.producer_status: unsupported value"
                )
            if not isinstance(payload["hold_reasons"], list) or any(
                not isinstance(reason, str) or not reason for reason in payload["hold_reasons"]
            ):
                raise InvalidProposalError(
                    f"proposal.events[{index}].payload.hold_reasons: expected strings"
                )
            if len(set(payload["hold_reasons"])) != len(payload["hold_reasons"]):
                raise InvalidProposalError(
                    f"proposal.events[{index}].payload.hold_reasons: duplicates"
                )
            _digest(
                payload["study_lock_sha256"],
                f"proposal.events[{index}].payload.study_lock_sha256",
            )
        else:
            payload = _object(
                payload,
                {
                    "bound_memory_head_sha256",
                    "member_id",
                    "quantitative_resolution",
                    "study_id",
                },
                f"proposal.events[{index}].payload",
            )
            if payload["quantitative_resolution"] not in _RESOLUTIONS:
                raise InvalidProposalError(
                    f"proposal.events[{index}].payload.quantitative_resolution: unsupported value"
                )
            if not isinstance(payload["member_id"], str) or not payload["member_id"].strip():
                raise InvalidProposalError(
                    f"proposal.events[{index}].payload.member_id: expected nonempty string"
                )
        if payload["bound_memory_head_sha256"] != head or payload["study_id"] != study_id:
            raise InvalidProposalError(
                f"proposal.events[{index}].payload: proposal binding mismatch"
            )
        proposed_id = event["proposed_event_id"]
        if proposed_id != _event_id(source_type, payload):
            raise InvalidProposalError(
                f"proposal.events[{index}].proposed_event_id: digest mismatch"
            )
        if proposed_id in proposed_ids:
            raise InvalidProposalError("proposal.events: duplicate proposed_event_id")
        proposed_ids.add(proposed_id)
        prepared.append(
            {
                "event_type": _EVENT_TYPES[source_type],
                "subject": f"phytoparalog-proposal-{proposed_id}",
                "payload": {
                    "acceptance_authority": "PHYTORESOLVE_CALLER",
                    "evidence": _owned_document(payload),
                    "scientific_gate_closure": False,
                    "source_event_type": source_type,
                    "source_proposed_event_id": proposed_id,
                    "target_selected": False,
                },
                "supersedes": (),
                "conflicts_with": (),
            }
        )
    return tuple(prepared)


def append_phytoresolve_proposal(
    store: Any,
    proposal: Mapping[str, Any],
    *,
    study: Study | Mapping[str, Any],
    expected_project_id: str,
    actor: str,
    occurred_at: str | datetime | None = None,
) -> dict[str, Any]:
    """Accept validated proposals only when the exact bound head still matches.

    The caller explicitly names the intended ledger and acceptance actor. The
    helper validates all events and the store privacy policy before opening one
    write transaction, then appends the batch atomically through PhytoResolve.
    """

    frozen_proposal = _owned_document(proposal)
    source_study = study if isinstance(study, Study) else Study.from_dict(study)
    expected_proposal = compile_study(source_study).phytoresolve_proposed_events
    if canonical_json_bytes(frozen_proposal) != canonical_json_bytes(expected_proposal):
        raise InvalidProposalError("proposal differs from full recomputation of the supplied study")
    prepared = prepare_phytoresolve_events(frozen_proposal)
    if store.project_id != expected_project_id:
        raise MemoryProjectMismatchError(
            "the open PhytoResolve store does not match expected_project_id"
        )
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("actor must be a nonempty string")
    expected_head = frozen_proposal["bound_memory_head_sha256"]
    report = store.verify()
    if report.head_sha256 != expected_head:
        raise StaleMemoryHeadError(
            "PhytoResolve memory head differs from the proposal's exact bound head"
        )
    store.verify(
        expected_head_sha256=expected_head,
        expected_event_count=report.event_count,
    )
    for event in prepared:
        store.privacy_policy.validate(
            {
                "actor": actor,
                "subject": event["subject"],
                "payload": event["payload"],
            }
        )

    appended = []
    with store._transaction(write=True):
        locked = store.verify()
        if locked.head_sha256 != expected_head or locked.event_count != report.event_count:
            raise StaleMemoryHeadError(
                "PhytoResolve memory changed before the proposal batch was appended"
            )
        for event in prepared:
            appended.append(
                store.append(
                    event["event_type"],
                    event["subject"],
                    event["payload"],
                    actor=actor,
                    occurred_at=occurred_at,
                    supersedes=event["supersedes"],
                    conflicts_with=event["conflicts_with"],
                )
            )
    final_report = store.verify(expected_event_count=report.event_count + len(prepared))
    return {
        "appended_event_count": len(appended),
        "appended_event_ids": [event.event_id for event in appended],
        "final_head_sha256": final_report.head_sha256,
        "prior_event_count": report.event_count,
        "prior_head_sha256": expected_head,
        "project_id": store.project_id,
        "scientific_gate_closure": False,
        "target_selected": False,
    }
