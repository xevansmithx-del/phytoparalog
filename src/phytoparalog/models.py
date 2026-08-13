"""Strict, dependency-free input model for PhytoParalog studies."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

STUDY_SCHEMA = "phytoparalog.study.v0.1"


class ValidationError(ValueError):
    """Raised when an input or capsule violates a closed schema."""


class IdentityState(str, Enum):
    EXACT = "EXACT"
    UNRESOLVED = "UNRESOLVED"
    COPY_COLLAPSED = "COPY_COLLAPSED"
    CONFLICT = "CONFLICT"
    NOT_ASSESSED = "NOT_ASSESSED"


class ReferenceState(str, Enum):
    MEMBER_DISCRIMINATOR_PRESENT = "MEMBER_DISCRIMINATOR_PRESENT"
    SUBGROUP_DISCRIMINATOR_ONLY = "SUBGROUP_DISCRIMINATOR_ONLY"
    NO_MEMBER_DISCRIMINATOR = "NO_MEMBER_DISCRIMINATOR"
    COMPETITIVE_BACKGROUND_MISSING = "COMPETITIVE_BACKGROUND_MISSING"
    NOT_ASSESSED = "NOT_ASSESSED"
    FAILED = "FAILED"


class ObservedState(str, Enum):
    EXACT_MEMBER_COUNTS = "EXACT_MEMBER_COUNTS"
    BOUNDED_MEMBER_COUNTS = "BOUNDED_MEMBER_COUNTS"
    SUBGROUP_ONLY = "SUBGROUP_ONLY"
    FAMILY_ONLY = "FAMILY_ONLY"
    NO_COMPATIBLE_FRAGMENTS = "NO_COMPATIBLE_FRAGMENTS"
    NOT_ASSESSED = "NOT_ASSESSED"
    FAILED = "FAILED"


class QuantitativeResolution(str, Enum):
    MEMBER_EXACT = "MEMBER_EXACT"
    MEMBER_BOUNDED = "MEMBER_BOUNDED"
    SUBGROUP = "SUBGROUP"
    FAMILY_SUM = "FAMILY_SUM"
    NONE = "NONE"


class IndependenceState(str, Enum):
    RECEIPT_VERIFIED = "RECEIPT_VERIFIED"
    DECLARED_NOT_VERIFIED = "DECLARED_NOT_VERIFIED"
    TECHNICAL_ONLY = "TECHNICAL_ONLY"
    MISSING = "MISSING"


class ProducerStatus(str, Enum):
    COMPILED_FOR_INDEPENDENT_REVIEW = "COMPILED_FOR_INDEPENDENT_REVIEW"
    HOLD = "HOLD"
    INVALID = "INVALID"


class ReceiptVerificationState(str, Enum):
    RECEIPT_VERIFIED = "RECEIPT_VERIFIED"
    DECLARED_NOT_VERIFIED = "DECLARED_NOT_VERIFIED"


class ReceiptType(str, Enum):
    MEMBER_IDENTITY = "MEMBER_IDENTITY"
    TRANSCRIPT_SEQUENCE = "TRANSCRIPT_SEQUENCE"
    REFERENCE_SCOPE = "REFERENCE_SCOPE"
    OBSERVATION_UNIT = "OBSERVATION_UNIT"
    EQUIVALENCE_CLASS = "EQUIVALENCE_CLASS"


class VerificationMethod(str, Enum):
    SHA256_RECALCULATED = "SHA256_RECALCULATED"
    DIGITAL_SIGNATURE_VERIFIED = "DIGITAL_SIGNATURE_VERIFIED"
    ARCHIVE_RECEIPT_VERIFIED = "ARCHIVE_RECEIPT_VERIFIED"


class CompetitiveBackgroundState(str, Enum):
    RECEIPT_VERIFIED_COMPLETE = "RECEIPT_VERIFIED_COMPLETE"
    DECLARED_COMPLETE = "DECLARED_COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    NOT_ASSESSED = "NOT_ASSESSED"


E = TypeVar("E", bound=Enum)


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{path}: expected object")
    if not all(isinstance(key, str) for key in value):
        raise ValidationError(f"{path}: object keys must be strings")
    return value


def _exact_fields(value: dict[str, Any], expected: set[str], path: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if unknown:
            details.append(f"unknown={unknown}")
        raise ValidationError(f"{path}: closed-schema field mismatch ({', '.join(details)})")


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{path}: expected non-empty string")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValidationError(f"{path}: contains non-Unicode-scalar code point")
    if value != value.strip():
        raise ValidationError(f"{path}: surrounding whitespace is not allowed")
    return value


def _nullable_text(value: Any, path: str) -> str | None:
    if value is None:
        return None
    return _text(value, path)


def _enum(enum_type: type[E], value: Any, path: str) -> E:
    if not isinstance(value, str):
        raise ValidationError(f"{path}: expected enum string")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = [item.value for item in enum_type]
        raise ValidationError(f"{path}: expected one of {allowed}") from exc


def _string_list(value: Any, path: str, *, minimum: int = 0) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValidationError(f"{path}: expected array")
    result = tuple(_text(item, f"{path}[{index}]") for index, item in enumerate(value))
    if len(result) < minimum:
        raise ValidationError(f"{path}: expected at least {minimum} item(s)")
    if len(set(result)) != len(result):
        raise ValidationError(f"{path}: duplicate values are not allowed")
    return result


@dataclass(frozen=True, slots=True)
class SourceReceipt:
    receipt_id: str
    record_id: str
    source_version: str
    subject_sha256: str
    artifact_sha256: str
    receipt_type: ReceiptType
    verification_method: VerificationMethod
    issuer: str
    verification_state: ReceiptVerificationState

    @classmethod
    def from_dict(cls, value: Any, path: str) -> SourceReceipt:
        data = _object(value, path)
        _exact_fields(
            data,
            {
                "receipt_id",
                "record_id",
                "source_version",
                "subject_sha256",
                "artifact_sha256",
                "receipt_type",
                "verification_method",
                "issuer",
                "verification_state",
            },
            path,
        )
        subject_digest = _text(data["subject_sha256"], f"{path}.subject_sha256")
        artifact_digest = _text(data["artifact_sha256"], f"{path}.artifact_sha256")
        for field, digest in (
            ("subject_sha256", subject_digest),
            ("artifact_sha256", artifact_digest),
        ):
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValidationError(f"{path}.{field}: expected lowercase SHA-256")
        return cls(
            receipt_id=_text(data["receipt_id"], f"{path}.receipt_id"),
            record_id=_text(data["record_id"], f"{path}.record_id"),
            source_version=_text(data["source_version"], f"{path}.source_version"),
            subject_sha256=subject_digest,
            artifact_sha256=artifact_digest,
            receipt_type=_enum(ReceiptType, data["receipt_type"], f"{path}.receipt_type"),
            verification_method=_enum(
                VerificationMethod,
                data["verification_method"],
                f"{path}.verification_method",
            ),
            issuer=_text(data["issuer"], f"{path}.issuer"),
            verification_state=_enum(
                ReceiptVerificationState,
                data["verification_state"],
                f"{path}.verification_state",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "record_id": self.record_id,
            "subject_sha256": self.subject_sha256,
            "artifact_sha256": self.artifact_sha256,
            "receipt_type": self.receipt_type.value,
            "verification_method": self.verification_method.value,
            "issuer": self.issuer,
            "source_version": self.source_version,
            "verification_state": self.verification_state.value,
        }


@dataclass(frozen=True, slots=True)
class Member:
    member_id: str
    locus_id: str
    identity_state: IdentityState
    identity_receipt_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any, path: str) -> Member:
        data = _object(value, path)
        _exact_fields(
            data,
            {"member_id", "locus_id", "identity_state", "identity_receipt_ids"},
            path,
        )
        return cls(
            member_id=_text(data["member_id"], f"{path}.member_id"),
            locus_id=_text(data["locus_id"], f"{path}.locus_id"),
            identity_state=_enum(IdentityState, data["identity_state"], f"{path}.identity_state"),
            identity_receipt_ids=_string_list(
                data["identity_receipt_ids"], f"{path}.identity_receipt_ids", minimum=1
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_state": self.identity_state.value,
            "identity_receipt_ids": sorted(self.identity_receipt_ids),
            "locus_id": self.locus_id,
            "member_id": self.member_id,
        }


@dataclass(frozen=True, slots=True)
class Transcript:
    transcript_id: str
    member_id: str
    sequence: str
    source_record: str
    source_version: str
    sequence_receipt_id: str

    @classmethod
    def from_dict(cls, value: Any, path: str) -> Transcript:
        data = _object(value, path)
        _exact_fields(
            data,
            {
                "transcript_id",
                "member_id",
                "sequence",
                "source_record",
                "source_version",
                "sequence_receipt_id",
            },
            path,
        )
        sequence = _text(data["sequence"], f"{path}.sequence").upper()
        if any(base not in "ACGTUN" for base in sequence):
            raise ValidationError(f"{path}.sequence: only A,C,G,T,U,N are allowed")
        sequence = sequence.replace("U", "T")
        return cls(
            transcript_id=_text(data["transcript_id"], f"{path}.transcript_id"),
            member_id=_text(data["member_id"], f"{path}.member_id"),
            sequence=sequence,
            source_record=_text(data["source_record"], f"{path}.source_record"),
            source_version=_text(data["source_version"], f"{path}.source_version"),
            sequence_receipt_id=_text(data["sequence_receipt_id"], f"{path}.sequence_receipt_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "sequence": self.sequence,
            "sequence_receipt_id": self.sequence_receipt_id,
            "source_record": self.source_record,
            "source_version": self.source_version,
            "transcript_id": self.transcript_id,
        }


@dataclass(frozen=True, slots=True)
class ReferenceScope:
    family_id: str
    family_member_ids: tuple[str, ...]
    competitive_member_ids: tuple[str, ...]
    competitive_background_state: CompetitiveBackgroundState
    scope_receipt_ids: tuple[str, ...]
    kmer_size: int

    @classmethod
    def from_dict(cls, value: Any, path: str) -> ReferenceScope:
        data = _object(value, path)
        _exact_fields(
            data,
            {
                "family_id",
                "family_member_ids",
                "competitive_member_ids",
                "competitive_background_state",
                "kmer_size",
                "scope_receipt_ids",
            },
            path,
        )
        kmer_size = data["kmer_size"]
        if isinstance(kmer_size, bool) or not isinstance(kmer_size, int):
            raise ValidationError(f"{path}.kmer_size: expected integer")
        if not 3 <= kmer_size <= 101:
            raise ValidationError(f"{path}.kmer_size: expected value from 3 through 101")
        return cls(
            family_id=_text(data["family_id"], f"{path}.family_id"),
            family_member_ids=_string_list(
                data["family_member_ids"], f"{path}.family_member_ids", minimum=2
            ),
            competitive_member_ids=_string_list(
                data["competitive_member_ids"], f"{path}.competitive_member_ids", minimum=2
            ),
            competitive_background_state=_enum(
                CompetitiveBackgroundState,
                data["competitive_background_state"],
                f"{path}.competitive_background_state",
            ),
            kmer_size=kmer_size,
            scope_receipt_ids=_string_list(
                data["scope_receipt_ids"], f"{path}.scope_receipt_ids", minimum=1
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "competitive_background_state": self.competitive_background_state.value,
            "competitive_member_ids": sorted(self.competitive_member_ids),
            "family_id": self.family_id,
            "family_member_ids": sorted(self.family_member_ids),
            "kmer_size": self.kmer_size,
            "scope_receipt_ids": sorted(self.scope_receipt_ids),
        }


@dataclass(frozen=True, slots=True)
class ObservationUnit:
    observation_id: str
    biological_unit_id: str
    parent_observation_id: str | None
    condition_id: str
    independence_state: IndependenceState
    independence_receipt_id: str | None

    @classmethod
    def from_dict(cls, value: Any, path: str) -> ObservationUnit:
        data = _object(value, path)
        _exact_fields(
            data,
            {
                "observation_id",
                "biological_unit_id",
                "parent_observation_id",
                "condition_id",
                "independence_state",
                "independence_receipt_id",
            },
            path,
        )
        state = _enum(IndependenceState, data["independence_state"], f"{path}.independence_state")
        receipt = _nullable_text(data["independence_receipt_id"], f"{path}.independence_receipt_id")
        if state is IndependenceState.RECEIPT_VERIFIED and receipt is None:
            raise ValidationError(f"{path}.independence_receipt_id: required for RECEIPT_VERIFIED")
        return cls(
            observation_id=_text(data["observation_id"], f"{path}.observation_id"),
            biological_unit_id=_text(data["biological_unit_id"], f"{path}.biological_unit_id"),
            parent_observation_id=_nullable_text(
                data["parent_observation_id"], f"{path}.parent_observation_id"
            ),
            condition_id=_text(data["condition_id"], f"{path}.condition_id"),
            independence_state=state,
            independence_receipt_id=receipt,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "biological_unit_id": self.biological_unit_id,
            "condition_id": self.condition_id,
            "independence_receipt_id": self.independence_receipt_id,
            "independence_state": self.independence_state.value,
            "observation_id": self.observation_id,
            "parent_observation_id": self.parent_observation_id,
        }


@dataclass(frozen=True, slots=True)
class EquivalenceClass:
    ec_id: str
    transcript_ids: tuple[str, ...]
    counts: dict[str, int]
    evidence_receipt_ids: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: Any, path: str) -> EquivalenceClass:
        data = _object(value, path)
        _exact_fields(data, {"ec_id", "transcript_ids", "counts", "evidence_receipt_ids"}, path)
        raw_counts = _object(data["counts"], f"{path}.counts")
        counts: dict[str, int] = {}
        for observation_id, count in raw_counts.items():
            _text(observation_id, f"{path}.counts key")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValidationError(
                    f"{path}.counts.{observation_id}: expected non-negative integer"
                )
            counts[observation_id] = count
        return cls(
            ec_id=_text(data["ec_id"], f"{path}.ec_id"),
            transcript_ids=_string_list(
                data["transcript_ids"], f"{path}.transcript_ids", minimum=1
            ),
            counts=counts,
            evidence_receipt_ids=_string_list(
                data["evidence_receipt_ids"], f"{path}.evidence_receipt_ids", minimum=1
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": dict(sorted(self.counts.items())),
            "ec_id": self.ec_id,
            "evidence_receipt_ids": sorted(self.evidence_receipt_ids),
            "transcript_ids": sorted(self.transcript_ids),
        }


@dataclass(frozen=True, slots=True)
class Study:
    schema_version: str
    study_id: str
    species: str
    stock_id: str
    bound_memory_head_sha256: str | None
    source_receipts: tuple[SourceReceipt, ...]
    members: tuple[Member, ...]
    transcripts: tuple[Transcript, ...]
    reference_scope: ReferenceScope
    observation_units: tuple[ObservationUnit, ...]
    equivalence_classes: tuple[EquivalenceClass, ...]

    @classmethod
    def from_dict(cls, value: Any) -> Study:
        data = _object(value, "study")
        _exact_fields(
            data,
            {
                "schema_version",
                "study_id",
                "species",
                "stock_id",
                "bound_memory_head_sha256",
                "source_receipts",
                "members",
                "transcripts",
                "reference_scope",
                "observation_units",
                "equivalence_classes",
                "target_selection",
            },
            "study",
        )
        if data["schema_version"] != STUDY_SCHEMA:
            raise ValidationError(f"study.schema_version: expected {STUDY_SCHEMA!r}")
        selection = _object(data["target_selection"], "study.target_selection")
        _exact_fields(selection, {"allowed", "status"}, "study.target_selection")
        if selection["allowed"] is not False or selection["status"] != "PROHIBITED":
            raise ValidationError(
                "study.target_selection: must be {'allowed': false, 'status': 'PROHIBITED'}"
            )
        memory_head = data["bound_memory_head_sha256"]
        if memory_head is not None:
            memory_head = _text(memory_head, "study.bound_memory_head_sha256")
            if len(memory_head) != 64 or any(
                character not in "0123456789abcdef" for character in memory_head
            ):
                raise ValidationError(
                    "study.bound_memory_head_sha256: expected lowercase SHA-256 or null"
                )
        if not isinstance(data["members"], list):
            raise ValidationError("study.members: expected array")
        if not isinstance(data["transcripts"], list):
            raise ValidationError("study.transcripts: expected array")
        if not isinstance(data["observation_units"], list):
            raise ValidationError("study.observation_units: expected array")
        if not isinstance(data["equivalence_classes"], list):
            raise ValidationError("study.equivalence_classes: expected array")
        if not isinstance(data["source_receipts"], list):
            raise ValidationError("study.source_receipts: expected array")
        receipts = tuple(
            SourceReceipt.from_dict(item, f"study.source_receipts[{index}]")
            for index, item in enumerate(data["source_receipts"])
        )
        members = tuple(
            Member.from_dict(item, f"study.members[{index}]")
            for index, item in enumerate(data["members"])
        )
        transcripts = tuple(
            Transcript.from_dict(item, f"study.transcripts[{index}]")
            for index, item in enumerate(data["transcripts"])
        )
        observations = tuple(
            ObservationUnit.from_dict(item, f"study.observation_units[{index}]")
            for index, item in enumerate(data["observation_units"])
        )
        ecs = tuple(
            EquivalenceClass.from_dict(item, f"study.equivalence_classes[{index}]")
            for index, item in enumerate(data["equivalence_classes"])
        )
        study = cls(
            schema_version=STUDY_SCHEMA,
            study_id=_text(data["study_id"], "study.study_id"),
            species=_text(data["species"], "study.species"),
            stock_id=_text(data["stock_id"], "study.stock_id"),
            bound_memory_head_sha256=memory_head,
            source_receipts=receipts,
            members=members,
            transcripts=transcripts,
            reference_scope=ReferenceScope.from_dict(
                data["reference_scope"], "study.reference_scope"
            ),
            observation_units=observations,
            equivalence_classes=ecs,
        )
        study._validate_relations()
        return study

    def _validate_relations(self) -> None:
        if len(self.members) < 2:
            raise ValidationError("study.members: expected at least two members")
        member_ids = [item.member_id for item in self.members]
        locus_ids = [item.locus_id for item in self.members]
        transcript_ids = [item.transcript_id for item in self.transcripts]
        observation_ids = [item.observation_id for item in self.observation_units]
        ec_ids = [item.ec_id for item in self.equivalence_classes]
        receipt_ids = [item.receipt_id for item in self.source_receipts]
        for values, path in (
            (member_ids, "study.members.member_id"),
            (locus_ids, "study.members.locus_id"),
            (transcript_ids, "study.transcripts.transcript_id"),
            (observation_ids, "study.observation_units.observation_id"),
            (ec_ids, "study.equivalence_classes.ec_id"),
            (receipt_ids, "study.source_receipts.receipt_id"),
        ):
            if len(set(values)) != len(values):
                raise ValidationError(f"{path}: duplicate values are not allowed")
        known_members = set(member_ids)
        family = set(self.reference_scope.family_member_ids)
        competitive = set(self.reference_scope.competitive_member_ids)
        if not family <= known_members:
            raise ValidationError("study.reference_scope.family_member_ids: unknown member")
        if not competitive <= known_members:
            raise ValidationError("study.reference_scope.competitive_member_ids: unknown member")
        if not family <= competitive:
            raise ValidationError(
                "study.reference_scope: family members must be in competitive_member_ids"
            )
        transcript_members = {item.member_id for item in self.transcripts}
        if not competitive <= transcript_members:
            raise ValidationError(
                "study.transcripts: every competitive member requires at least one transcript"
            )
        if any(item.member_id not in known_members for item in self.transcripts):
            raise ValidationError("study.transcripts.member_id: unknown member")
        if transcript_members != competitive:
            raise ValidationError(
                "study.transcripts: every transcript member must be in competitive_member_ids"
            )
        if any(len(item.sequence) < self.reference_scope.kmer_size for item in self.transcripts):
            raise ValidationError("study.transcripts.sequence: shorter than reference kmer_size")
        known_transcripts = set(transcript_ids)
        known_observations = set(observation_ids)
        known_receipts = set(receipt_ids)
        referenced_receipts: set[str] = set(self.reference_scope.scope_receipt_ids)
        for member in self.members:
            referenced_receipts.update(member.identity_receipt_ids)
        for transcript in self.transcripts:
            referenced_receipts.add(transcript.sequence_receipt_id)
        for observation in self.observation_units:
            if observation.independence_receipt_id is not None:
                referenced_receipts.add(observation.independence_receipt_id)
        for ec in self.equivalence_classes:
            referenced_receipts.update(ec.evidence_receipt_ids)
        if not referenced_receipts <= known_receipts:
            raise ValidationError("study: one or more bound source receipt IDs are unknown")
        if referenced_receipts != known_receipts:
            raise ValidationError("study.source_receipts: unbound receipts are not allowed")
        receipt_by_id = {item.receipt_id: item for item in self.source_receipts}

        def subject_sha(value: Any) -> str:
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

        for member in self.members:
            expected = subject_sha({"locus_id": member.locus_id, "member_id": member.member_id})
            for receipt_id in member.identity_receipt_ids:
                receipt = receipt_by_id[receipt_id]
                if receipt.receipt_type is not ReceiptType.MEMBER_IDENTITY:
                    raise ValidationError(
                        f"study.members.{member.member_id}: receipt type mismatch"
                    )
                if receipt.subject_sha256 != expected:
                    raise ValidationError(
                        f"study.members.{member.member_id}: identity receipt checksum mismatch"
                    )
        for transcript in self.transcripts:
            receipt = receipt_by_id[transcript.sequence_receipt_id]
            if receipt.receipt_type is not ReceiptType.TRANSCRIPT_SEQUENCE:
                raise ValidationError(
                    f"study.transcripts.{transcript.transcript_id}: receipt type mismatch"
                )
            if receipt.record_id != transcript.source_record:
                raise ValidationError(
                    f"study.transcripts.{transcript.transcript_id}: receipt record mismatch"
                )
            if receipt.source_version != transcript.source_version:
                raise ValidationError(
                    f"study.transcripts.{transcript.transcript_id}: receipt version mismatch"
                )
            sequence_sha256 = hashlib.sha256(transcript.sequence.encode("utf-8")).hexdigest()
            if receipt.subject_sha256 != sequence_sha256:
                raise ValidationError(
                    f"study.transcripts.{transcript.transcript_id}: sequence checksum mismatch"
                )
        scope_expected = subject_sha(
            {
                "competitive_background_state": (
                    self.reference_scope.competitive_background_state.value
                ),
                "competitive_member_ids": sorted(self.reference_scope.competitive_member_ids),
                "family_id": self.reference_scope.family_id,
                "family_member_ids": sorted(self.reference_scope.family_member_ids),
                "kmer_size": self.reference_scope.kmer_size,
            }
        )
        for receipt_id in self.reference_scope.scope_receipt_ids:
            receipt = receipt_by_id[receipt_id]
            if receipt.receipt_type is not ReceiptType.REFERENCE_SCOPE:
                raise ValidationError("study.reference_scope: receipt type mismatch")
            if receipt.subject_sha256 != scope_expected:
                raise ValidationError("study.reference_scope: receipt checksum mismatch")
        for observation in self.observation_units:
            if observation.independence_receipt_id is None:
                continue
            receipt = receipt_by_id[observation.independence_receipt_id]
            expected = subject_sha(
                {
                    "biological_unit_id": observation.biological_unit_id,
                    "condition_id": observation.condition_id,
                    "observation_id": observation.observation_id,
                    "parent_observation_id": observation.parent_observation_id,
                }
            )
            if receipt.receipt_type is not ReceiptType.OBSERVATION_UNIT:
                raise ValidationError(
                    f"study.observation_units.{observation.observation_id}: receipt type mismatch"
                )
            if receipt.subject_sha256 != expected:
                raise ValidationError(
                    "study.observation_units."
                    f"{observation.observation_id}: receipt checksum mismatch"
                )
        for ec in self.equivalence_classes:
            expected = subject_sha(
                {
                    "counts": dict(sorted(ec.counts.items())),
                    "ec_id": ec.ec_id,
                    "transcript_ids": sorted(ec.transcript_ids),
                }
            )
            for receipt_id in ec.evidence_receipt_ids:
                receipt = receipt_by_id[receipt_id]
                if receipt.receipt_type is not ReceiptType.EQUIVALENCE_CLASS:
                    raise ValidationError(
                        f"study.equivalence_classes.{ec.ec_id}: receipt type mismatch"
                    )
                if receipt.subject_sha256 != expected:
                    raise ValidationError(
                        f"study.equivalence_classes.{ec.ec_id}: receipt checksum mismatch"
                    )
        for ec in self.equivalence_classes:
            if not set(ec.transcript_ids) <= known_transcripts:
                raise ValidationError(f"study.equivalence_classes.{ec.ec_id}: unknown transcript")
            ec_member_ids = {
                transcript.member_id
                for transcript in self.transcripts
                if transcript.transcript_id in ec.transcript_ids
            }
            if not ec_member_ids <= competitive:
                raise ValidationError(
                    f"study.equivalence_classes.{ec.ec_id}: transcript outside competitive scope"
                )
            if set(ec.counts) != known_observations:
                raise ValidationError(
                    f"study.equivalence_classes.{ec.ec_id}.counts: must name every observation"
                )
        parents = {
            item.observation_id: item.parent_observation_id for item in self.observation_units
        }
        for observation_id, parent in parents.items():
            if parent is not None and parent not in parents:
                raise ValidationError(
                    f"study.observation_units.{observation_id}: unknown parent_observation_id"
                )
            if parent == observation_id:
                raise ValidationError(
                    f"study.observation_units.{observation_id}: self-parent cycle"
                )
            seen = {observation_id}
            cursor = parent
            while cursor is not None:
                if cursor in seen:
                    raise ValidationError("study.observation_units: parent cycle detected")
                seen.add(cursor)
                cursor = parents[cursor]
        observations_by_id = {item.observation_id: item for item in self.observation_units}
        for observation in self.observation_units:
            parent_id = observation.parent_observation_id
            if parent_id is None:
                continue
            parent = observations_by_id[parent_id]
            if observation.biological_unit_id != parent.biological_unit_id:
                raise ValidationError(
                    "study.observation_units."
                    f"{observation.observation_id}: derived observations must share the "
                    "parent biological_unit_id"
                )
            if observation.independence_state is IndependenceState.RECEIPT_VERIFIED:
                raise ValidationError(
                    "study.observation_units."
                    f"{observation.observation_id}: a derived observation cannot be an "
                    "independently verified biological unit"
                )
        conditions_by_unit: dict[str, set[str]] = {}
        for observation in self.observation_units:
            conditions_by_unit.setdefault(observation.biological_unit_id, set()).add(
                observation.condition_id
            )
        if any(len(conditions) > 1 for conditions in conditions_by_unit.values()):
            raise ValidationError(
                "study.observation_units: a biological_unit_id cannot span multiple conditions"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "bound_memory_head_sha256": self.bound_memory_head_sha256,
            "equivalence_classes": [
                item.to_dict()
                for item in sorted(self.equivalence_classes, key=lambda item: item.ec_id)
            ],
            "members": [
                item.to_dict() for item in sorted(self.members, key=lambda item: item.member_id)
            ],
            "observation_units": [
                item.to_dict()
                for item in sorted(self.observation_units, key=lambda item: item.observation_id)
            ],
            "reference_scope": self.reference_scope.to_dict(),
            "schema_version": self.schema_version,
            "source_receipts": [
                item.to_dict()
                for item in sorted(self.source_receipts, key=lambda item: item.receipt_id)
            ],
            "species": self.species,
            "stock_id": self.stock_id,
            "study_id": self.study_id,
            "target_selection": {"allowed": False, "status": "PROHIBITED"},
            "transcripts": [
                item.to_dict()
                for item in sorted(self.transcripts, key=lambda item: item.transcript_id)
            ],
        }
