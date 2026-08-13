from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from phytoparalog import compile_study
from phytoparalog_integrations import (
    InvalidProposalError,
    MemoryProjectMismatchError,
    StaleMemoryHeadError,
    append_phytoresolve_proposal,
    pec_project_spec,
    prepare_phytoresolve_events,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _study_document() -> dict[str, Any]:
    return json.loads(
        (PROJECT_ROOT / "examples" / "synthetic" / "study.json").read_text(encoding="utf-8")
    )


def test_actual_plant_evidence_compiler_project_is_conservative() -> None:
    pytest.importorskip(
        "plant_evidence", reason="Plant Evidence Compiler is an optional integration"
    )
    from plant_evidence.engine import preflight_project
    from plant_evidence.models import ClaimLevel, Disposition, ProjectSpec

    raw = _study_document()
    spec = pec_project_spec(raw)
    assert isinstance(spec, ProjectSpec)
    decision = preflight_project(spec)

    assert decision.disposition is Disposition.NO_RELEASE
    assert decision.claim_ceiling is ClaimLevel.DESCRIPTIVE
    gate_results = {gate.id: gate.disposition for gate in decision.gates}
    assert gate_results["identity_lock"] is Disposition.HOLD
    assert gate_results["input_provenance"] is Disposition.HOLD
    assert gate_results["member_identity"] is Disposition.HOLD
    assert gate_results["member_function"] is Disposition.HOLD
    assert gate_results["causal_interpretation"] is Disposition.HOLD
    assert gate_results["wet_lab_readiness"] is Disposition.HOLD
    assert gate_results["target_selection"] is Disposition.HOLD
    assert spec.public_release.data_classification == "non_public"
    serialized = spec.model_dump_json()
    assert raw["study_id"] not in serialized
    assert raw["stock_id"] not in serialized


def test_actual_phytoresolve_exact_head_batch_append(tmp_path: Path) -> None:
    pytest.importorskip("phytoresolve", reason="PhytoResolve is an optional integration")
    from phytoresolve.memory import MemoryStore

    memory_path = tmp_path / "memory.sqlite3"
    with MemoryStore.open(memory_path, project_id="synthetic-paralog-memory") as store:
        pinned_head = store.verify().head_sha256
        raw = _study_document()
        raw["bound_memory_head_sha256"] = pinned_head
        proposal = compile_study(raw).phytoresolve_proposed_events
        prepared = prepare_phytoresolve_events(proposal)

        result = append_phytoresolve_proposal(
            store,
            proposal,
            study=raw,
            expected_project_id="synthetic-paralog-memory",
            actor="integration-test",
            occurred_at="2026-08-13T12:00:00Z",
        )

        assert result["prior_head_sha256"] == pinned_head
        assert result["appended_event_count"] == len(prepared)
        assert result["target_selected"] is False
        assert result["scientific_gate_closure"] is False
        report = store.verify(expected_event_count=len(prepared))
        assert report.head_sha256 == result["final_head_sha256"]
        events = store.events()
        assert {event.event_type for event in events} == {"artifact"}
        assert all(event.payload["scientific_gate_closure"] is False for event in events)
        assert all(event.payload["target_selected"] is False for event in events)


def test_actual_phytoresolve_refuses_stale_head_without_writes(tmp_path: Path) -> None:
    pytest.importorskip("phytoresolve", reason="PhytoResolve is an optional integration")
    from phytoresolve.memory import MemoryStore

    memory_path = tmp_path / "memory.sqlite3"
    with MemoryStore.open(memory_path, project_id="synthetic-paralog-memory") as store:
        original_head = store.verify().head_sha256
        raw = _study_document()
        raw["bound_memory_head_sha256"] = original_head
        proposal = compile_study(raw).phytoresolve_proposed_events
        store.append(
            "fact",
            "intervening-event",
            {"summary": "memory changed"},
            actor="integration-test",
            occurred_at="2026-08-13T13:00:00Z",
        )
        count_before = store.verify().event_count

        with pytest.raises(StaleMemoryHeadError, match="differs"):
            append_phytoresolve_proposal(
                store,
                proposal,
                study=raw,
                expected_project_id="synthetic-paralog-memory",
                actor="integration-test",
                occurred_at="2026-08-13T13:01:00Z",
            )

        assert store.verify().event_count == count_before


def test_actual_phytoresolve_refuses_wrong_project_without_writes(tmp_path: Path) -> None:
    pytest.importorskip("phytoresolve", reason="PhytoResolve is an optional integration")
    from phytoresolve.memory import MemoryStore

    memory_path = tmp_path / "memory.sqlite3"
    with MemoryStore.open(memory_path, project_id="synthetic-paralog-memory") as store:
        raw = _study_document()
        raw["bound_memory_head_sha256"] = store.verify().head_sha256
        proposal = compile_study(raw).phytoresolve_proposed_events

        with pytest.raises(MemoryProjectMismatchError, match="expected_project_id"):
            append_phytoresolve_proposal(
                store,
                proposal,
                study=raw,
                expected_project_id="different-memory-project",
                actor="integration-test",
            )

        assert store.verify().event_count == 0


def test_proposal_validation_precedes_any_memory_write(tmp_path: Path) -> None:
    pytest.importorskip("phytoresolve", reason="PhytoResolve is an optional integration")
    from phytoresolve.memory import MemoryStore

    memory_path = tmp_path / "memory.sqlite3"
    with MemoryStore.open(memory_path, project_id="synthetic-paralog-memory") as store:
        raw = _study_document()
        raw["bound_memory_head_sha256"] = store.verify().head_sha256
        proposal = compile_study(raw).phytoresolve_proposed_events
        proposal["events"][0]["proposed_event_id"] = "ppe_invalid"

        with pytest.raises(InvalidProposalError, match="full recomputation"):
            append_phytoresolve_proposal(
                store,
                proposal,
                study=raw,
                expected_project_id="synthetic-paralog-memory",
                actor="integration-test",
            )

        assert store.verify().event_count == 0


def test_null_memory_head_cannot_be_appended() -> None:
    proposal = compile_study(_study_document()).phytoresolve_proposed_events
    with pytest.raises(InvalidProposalError, match="lowercase SHA-256"):
        prepare_phytoresolve_events(proposal)


def test_prepared_events_do_not_alias_nested_caller_payloads() -> None:
    raw = _study_document()
    raw["bound_memory_head_sha256"] = "a" * 64
    proposal = compile_study(raw).phytoresolve_proposed_events
    expected_reasons = list(proposal["events"][0]["payload"]["hold_reasons"])

    prepared = prepare_phytoresolve_events(proposal)
    prepared_reasons = prepared[0]["payload"]["evidence"]["hold_reasons"]
    assert prepared_reasons == expected_reasons
    assert prepared_reasons is not proposal["events"][0]["payload"]["hold_reasons"]

    proposal["events"][0]["payload"]["hold_reasons"].clear()
    assert prepared_reasons == expected_reasons


def test_actual_append_owns_payload_during_store_verification(tmp_path: Path) -> None:
    pytest.importorskip("phytoresolve", reason="PhytoResolve is an optional integration")
    from phytoresolve.memory import MemoryStore

    memory_path = tmp_path / "memory.sqlite3"
    with MemoryStore.open(memory_path, project_id="synthetic-paralog-memory") as delegate:
        raw = _study_document()
        pinned_head = delegate.verify().head_sha256
        raw["bound_memory_head_sha256"] = pinned_head
        proposal = compile_study(raw).phytoresolve_proposed_events
        expected_reasons = list(proposal["events"][0]["payload"]["hold_reasons"])

        class MutatingStore:
            project_id = delegate.project_id
            privacy_policy = delegate.privacy_policy

            def __init__(self) -> None:
                self.mutated = False

            def verify(self, *args: Any, **kwargs: Any) -> Any:
                if not self.mutated:
                    proposal["events"][0]["payload"]["hold_reasons"].clear()
                    self.mutated = True
                return delegate.verify(*args, **kwargs)

            def _transaction(self, *args: Any, **kwargs: Any) -> Any:
                return delegate._transaction(*args, **kwargs)

            def append(self, *args: Any, **kwargs: Any) -> Any:
                return delegate.append(*args, **kwargs)

        result = append_phytoresolve_proposal(
            MutatingStore(),
            proposal,
            study=raw,
            expected_project_id="synthetic-paralog-memory",
            actor="integration-test",
            occurred_at="2026-08-13T12:30:00Z",
        )

        assert proposal["events"][0]["payload"]["hold_reasons"] == []
        assert result["prior_head_sha256"] == pinned_head
        compiled_event = next(
            event
            for event in delegate.events()
            if event.payload["source_event_type"] == "paralog_identifiability_compiled"
        )
        assert compiled_event.payload["evidence"]["hold_reasons"] == expected_reasons


def test_append_refuses_rehashed_forged_semantics(tmp_path: Path) -> None:
    pytest.importorskip("phytoresolve", reason="PhytoResolve is an optional integration")
    from phytoresolve.memory import MemoryStore

    memory_path = tmp_path / "memory.sqlite3"
    with MemoryStore.open(memory_path, project_id="synthetic-paralog-memory") as store:
        raw = _study_document()
        raw["bound_memory_head_sha256"] = store.verify().head_sha256
        proposal = compile_study(raw).phytoresolve_proposed_events
        proposal["events"][0]["payload"]["producer_status"] = "COMPILED_FOR_INDEPENDENT_REVIEW"
        proposal["events"][0]["payload"]["hold_reasons"] = []
        payload = proposal["events"][0]["payload"]
        digest = hashlib.sha256(
            json.dumps(
                {
                    "event_type": proposal["events"][0]["event_type"],
                    "payload": payload,
                },
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            + b"\n"
        ).hexdigest()
        proposal["events"][0]["proposed_event_id"] = f"ppe_{digest[:24]}"

        with pytest.raises(InvalidProposalError, match="full recomputation"):
            append_phytoresolve_proposal(
                store,
                proposal,
                study=raw,
                expected_project_id="synthetic-paralog-memory",
                actor="integration-test",
            )
        assert store.verify().event_count == 0
