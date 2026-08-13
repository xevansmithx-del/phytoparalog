# Input and output schema

The authoritative behavior is implemented by the closed Python model and validated by the test
suite. This page is a field-level guide for `phytoparalog.study.v0.1` and the capsule formats.

Unknown fields are rejected at every closed object boundary. Identifiers are opaque strings; the
compiler does not infer semantics from naming conventions.

## Study object

Required top-level fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | string | Exactly `phytoparalog.study.v0.1` |
| `study_id` | nonempty string | Stable study identifier |
| `species` | nonempty string | Declared organism label |
| `stock_id` | nonempty string | Biological stock or source label; committed in output |
| `bound_memory_head_sha256` | SHA-256 or null | Optional append-only memory head bound at compilation |
| `source_receipts` | array | Every receipt used by another object, with no unbound extras |
| `members` | array | At least two biological members |
| `transcripts` | array | Transcript-to-member assignments and sequence evidence |
| `reference_scope` | object | Family, competitive set, background state, and k-mer size |
| `observation_units` | array | Biological-origin and condition structure |
| `equivalence_classes` | array | Compatible transcript sets and integer counts |
| `target_selection` | object | Exactly `{"allowed": false, "status": "PROHIBITED"}` |

## Source receipt

Each receipt has `receipt_id`, `record_id`, `source_version`, lowercase `subject_sha256` and
`artifact_sha256`, `receipt_type`, `verification_method`, `issuer`, and `verification_state`.
Verification state is `RECEIPT_VERIFIED` or `DECLARED_NOT_VERIFIED`. These values are caller
assertions; the compiler validates their structure and bindings but cannot authenticate an issuer,
signature, archive, or external authority.

Receipt type and subject digest are checked against the object that binds each receipt. Sequence
receipt record and version must match the transcript declaration, and its subject digest must equal
the SHA-256 of the normalized DNA sequence. Member, reference-scope, observation, and
equivalence-class receipts bind canonical closed objects.

Every receipt must be referenced, and every referenced receipt must exist.

## Member and transcript

A member contains `member_id`, `locus_id`, `identity_state`, and a nonempty array of
`identity_receipt_ids`.

A transcript contains `transcript_id`, `member_id`, `sequence`, `source_record`, `source_version`,
and `sequence_receipt_id`. RNA `U` is normalized to DNA `T`; only `A`, `C`, `G`, `T`, `U`, and `N`
are accepted. Every competitive member needs at least one transcript, and each transcript must be
at least as long as the declared k-mer size.

## Reference scope

`reference_scope` contains:

- `family_id`
- `family_member_ids`
- `competitive_member_ids`
- `competitive_background_state`
- `kmer_size` from 3 through 101
- `scope_receipt_ids`

The family must be a subset of the competitive set. All named members must exist.

## Observation unit

An observation contains `observation_id`, `biological_unit_id`, nullable
`parent_observation_id`, `condition_id`, `independence_state`, and nullable
`independence_receipt_id`. Receipt-verified independence requires a receipt. Parent references must
exist, cannot point to self, and cannot form a cycle.

## Equivalence class

An equivalence class contains `ec_id`, one or more `transcript_ids`, a `counts` object, and one or
more `evidence_receipt_ids`. Counts are non-negative integers and must name every observation
exactly once. All transcript and receipt identifiers must resolve.

## Technical and admissible output fields

Caller evidence is never promoted merely because its hashes are internally consistent. Derived
identity, reference, observation, count, independence, and resolution calculations are labeled
with `technical_*` fields (or `receipt_claimed_*` counts). The corresponding admissible values stay
`UNRESOLVED`, `NOT_ASSESSED`, `NONE`, zero, or null, and each compilation retains
`EXTERNAL_RECEIPT_AUTHORITY_NOT_ESTABLISHED` on hold.

There is no preregistered minimum replicate count in `phytoparalog.study.v0.1`. The compiler audits
the unit graph and reports technical and caller-claimed unit cardinalities without declaring a
sample size scientifically adequate.

## Evidence capsule

The capsule contains exactly:

| File | Schema family | Purpose |
| --- | --- | --- |
| `study_lock.json` | `phytoparalog.study-lock.v0.1` | Input, reference, receipt, and sequence commitments |
| `identifiability.json` | `phytoparalog.identifiability.v0.1` | Derived identity, reference, and observed resolution |
| `pec_candidate_evidence.json` | `phytoparalog.pec-candidate-evidence.v0.1` | Candidate evidence with prohibited claims |
| `phytoresolve_proposed_events.json` | `phytoparalog.phytoresolve-proposed-events.v0.1` | Proposal-only append events |
| `manifest.json` | `phytoparalog.manifest.v0.1` | Size and digest commitments for the four documents |

All JSON is canonical and all five documents prohibit target selection. Validation rejects extra
files so an uncommitted sidecar cannot be mistaken for part of the capsule.

An unanchored validation reports `INTEGRITY_ONLY`. That mode proves self-consistency, not that the
documents are compiler output for an accepted study. `STUDY_RECOMPUTED` performs full
byte-for-byte recomputation from the original study; `EXTERNAL_DIGEST_ANCHORED` compares against a
digest stored outside the capsule. Only `STUDY_RECOMPUTED` authenticates compiler semantics.
External-digest anchoring authenticates the exact capsule bytes but does not establish that the
documents' scientific meaning is correct.

## Compatibility policy

Schema versions are explicit. A minor software release may add validation that rejects previously
ambiguous or unsafe input, but it will not silently reinterpret an existing schema version. A
field or semantic change requires a new schema version and migration note.
