# Reproducibility

PhytoParalog separates deterministic compilation from evidence acquisition. It does not fetch
references, infer sample metadata, run a read mapper, or append persistent memory. Those upstream
steps must supply versioned receipts and equivalence classes.

## Canonical serialization

All committed JSON uses UTF-8, lexicographically sorted keys, compact separators, no non-finite
numbers, and one trailing newline. SHA-256 is computed over those exact bytes.

## Determinism contract

For the same normalized study object and software version, compilation produces the same four
evidence documents and manifest on every supported platform. Input list order does not alter
semantic output where identifiers define ordering.

## Dependency policy

The scientific core uses only the Python standard library. Development and optional integration
dependencies are declared separately. The committed lock file records the tested resolution, while
the package metadata states the supported ranges.

## Evidence receipts

A receipt records a stable record identifier, source version, content digest, and verification
state. A digest demonstrates byte identity; it does not prove that the source is scientifically
complete, correctly annotated, redistributable, or appropriate for the biological question.

## Persistent memory

An optional memory-head digest can be bound into the study lock and proposed events. This provides
lineage without granting write authority. The append bridge requires the original study, fully
recomputes the proposal byte-for-byte, verifies the exact bound head inside one write transaction,
and maps every candidate event to an `artifact`, never an accepted biological fact. A stale head,
different project, changed payload, or rehashed forgery is refused before any write. Re-running the
compiler itself never mutates the ledger.
