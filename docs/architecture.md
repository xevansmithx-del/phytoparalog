# Architecture

PhytoParalog is a deterministic evidence compiler with a deliberately narrow authority. It accepts
a closed study object, validates relational and provenance constraints, evaluates sequence and
observational identifiability, and emits an immutable capsule for independent review.

## Data flow

```text
receipt-bound study
        |
        v
closed-schema + relation validation
        |
        +--> identity analysis
        +--> competitive-reference analysis
        +--> equivalence-class compatibility bounds
        +--> biological-independence audit
        |
        v
four evidence documents
        |
        v
hash-committed manifest
```

Compilation is pure until the capsule writer is called. It performs no network requests, database
lookups, target ranking, statistical imputation, or persistent-memory writes.

## Identity layer

Each biological member binds a declared locus, identity state, and one or more caller-supplied
receipt claims. The compiler reports the caller-derived calculation as a `technical_*` diagnostic
but keeps the admissible state unresolved unless an independent authority adjudicates the receipt:

- `EXACT`
- `UNRESOLVED`
- `COPY_COLLAPSED`
- `CONFLICT`
- `NOT_ASSESSED`

If identical transcript sequence is assigned to multiple family members, each affected member is
forced to `COPY_COLLAPSED`, a conservative structural conflict that does not require trusting a
positive claim. Otherwise, a caller-declared exact identity remains technically recorded but the
effective state is `UNRESOLVED`.

## Reference layer

Canonical k-mers are evaluated across the declared competitive set, not just inside the family.
Technical reference diagnostics use these states:

- `MEMBER_DISCRIMINATOR_PRESENT`
- `SUBGROUP_DISCRIMINATOR_ONLY`
- `NO_MEMBER_DISCRIMINATOR`
- `COMPETITIVE_BACKGROUND_MISSING`
- `NOT_ASSESSED`
- `FAILED`

A family-only comparison is structurally incapable of demonstrating competitive member
specificity. Even a caller-declared complete background cannot create an admissible discriminator:
the current producer has no external reference authority, so positive technical states remain
`NOT_ASSESSED` in the admissible layer.

Unique k-mers are structural opportunities, not proof that a particular assay observed a member.

## Observation layer

Input counts are equivalence-class counts: each class names every transcript compatible with its
fragments. Transcript labels collapse to biological member sets while retaining compatible
members outside the focal family.

The technical diagnostic for member `m` in observation `o` is:

```text
lower(m,o) = sum counts for classes whose biological member set is exactly {m}
upper(m,o) = sum counts for every class whose biological member set contains m
```

The technical diagnostic for family `F` is:

```text
lower(F,o) = sum counts for nonempty classes wholly contained in F
upper(F,o) = sum counts for classes intersecting F
```

These are allocation or compatibility bounds, not confidence intervals. The compiler never
silently divides an ambiguous class among members. Counts derived from caller evidence are emitted
only as `technical_*` values. Admissible count fields remain null until external receipt authority
is established.

Technical observed states are `EXACT_MEMBER_COUNTS`, `BOUNDED_MEMBER_COUNTS`, `SUBGROUP_ONLY`,
`FAMILY_ONLY`, `NO_COMPATIBLE_FRAGMENTS`, `NOT_ASSESSED`, and `FAILED`.

The technical quantitative resolution is the weakest supported level among `MEMBER_EXACT`,
`MEMBER_BOUNDED`, `SUBGROUP`, `FAMILY_SUM`, and `NONE`. The admissible resolution is currently
`NONE` because caller receipt assertions are not independently authenticated.

## Independence layer

An observation binds a biological-unit identifier and may point to a parent observation. This
supports a biological-origin graph such as biological source to specimen, extraction, library,
and lane. Multiple lanes or reruns from one biological unit remain one independent unit.

Input independence states are `RECEIPT_VERIFIED`, `DECLARED_NOT_VERIFIED`, `TECHNICAL_ONLY`, and
`MISSING`, but `RECEIPT_VERIFIED` is a caller claim, not an external judgment. The compiler reports
technical and receipt-claimed unit counts separately while the externally verified count remains
zero. The schema does not encode or enforce a minimum biological-unit threshold.

## Producer status

The producer emits only:

- `COMPILED_FOR_INDEPENDENT_REVIEW`
- `HOLD`
- `INVALID`

The first means that the evidence capsule was compiled and is ready to be reviewed. It is not a
scientific PASS and does not close a study gate.

## Capsule boundary

The capsule has exactly five JSON files. Four evidence documents are serialized canonically. The
manifest binds their filenames, byte sizes, and SHA-256 digests. Validation rejects missing,
unknown, altered, or non-canonical files.

`phytoresolve_proposed_events.json` contains proposal-only events. PhytoParalog never appends to a
persistent ledger. A separate authority may independently review and append accepted events.

`pec_candidate_evidence.json` is a generic candidate-evidence fragment, not a complete or directly
consumable Plant Evidence Compiler project. It never claims function, phenotype, rights, or
experimental readiness. Use `pec_project_spec(...)` to construct the tested conservative consumer
contract.

## Optional integration

The `phytoparalog_tu` package is an adapter, not a second scientific engine. ToolUniverse discovers
it through an installed entry point and loads one registered class plus three JSON configurations.
The adapter imports the core lazily, returns structured errors, and does not perform network calls.
