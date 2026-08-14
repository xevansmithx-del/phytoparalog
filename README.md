# PhytoParalog

PhytoParalog is a fail-closed compiler for a deceptively hard question in plant transcriptomics:
**does the available reference and observed read evidence actually distinguish each paralog?**

It converts a closed, caller-supplied study description into deterministic evidence documents. It
checks receipt syntax and content bindings without authenticating the receipt authority, preserves
ambiguity as technical compatibility bounds, audits declared independence, records reference
scope, and emits only proposals for independent review. It never chooses, scores, or recommends a
gene.

> **Alpha software.** PhytoParalog supports evidence auditing and experiment design. It does not
> establish biological function, causality, phenotype, safety, intellectual-property freedom, or
> wet-lab readiness.

## Why it exists

Closely related genes can share transcript sequence. Short reads may then be compatible with more
than one family member, and multiple abundance allocations can fit the same observations. A point
estimate can hide that non-identifiability. PhytoParalog retains the compatible set and reports
member, subgroup, and family bounds instead.

The result is useful before target-specific wet-lab work: it shows what the evidence resolves,
what it only bounds, and which missing receipts or reference features still block interpretation.

## Core guarantees

- Closed input schemas reject unknown and missing fields.
- Source, reference-scope, sequence, and independence receipt claims are bound explicitly but not
  externally authenticated.
- Exact duplicate transcripts across members force copy-collapsed identity.
- Positive technical member-discriminator diagnostics require a caller-claimed, receipt-bound
  complete competitive background; admissible discrimination still requires external authority.
- Ambiguous equivalence-class counts remain ambiguous; no EM split is used for ranking.
- Biological-unit declarations are separated from lanes and technical reruns; independently
  verified replication remains zero until an external authority adjudicates it.
- Every document carries `target_selection: {"allowed": false, "status": "PROHIBITED"}`.
- Output status is `COMPILED_FOR_INDEPENDENT_REVIEW`, `HOLD`, or `INVALID`—never scientific PASS.

## Install

Download the wheel from the
[`v0.1.1` GitHub release](https://github.com/xevansmithx-del/phytoparalog/releases/tag/v0.1.1),
then install that reviewed artifact:

```bash
python -m pip install ./phytoparalog-0.1.1-py3-none-any.whl
```

For the optional ToolUniverse plugin:

```bash
python -m pip install 'tooluniverse==1.4.1' ./phytoparalog-0.1.1-py3-none-any.whl
```

The release workflow publishes GitHub artifacts only. It does not claim that a package
with this name is available from PyPI.

## Quick start

Validate and compile a study into a five-file capsule:

```bash
phytoparalog validate study.json
phytoparalog compile study.json evidence-capsule
phytoparalog validate-capsule evidence-capsule --study study.json
```

The capsule contains:

- `study_lock.json` — normalized input and provenance commitments;
- `identifiability.json` — identity, reference, observation, and resolution states;
- `pec_candidate_evidence.json` — candidate evidence with explicit limitations;
- `phytoresolve_proposed_events.json` — append-only event proposals, never direct memory writes;
- `manifest.json` — canonical SHA-256 commitments for the other four files.

The repository includes one fully synthetic fixture. It demonstrates the schema and a deliberate
family-only fail-closed case without publishing a real organism, accession, study label, raw real
sequence, or local path. See `examples/synthetic/README.md` before reusing it.

## ToolUniverse

Installing the optional extra exposes three local tools through ToolUniverse's plugin discovery:

- `PhytoParalog_preflight`
- `PhytoParalog_compile`
- `PhytoParalog_validate_capsule`

Each returns a structured success or error envelope, refuses target selection, and can run against
the packaged synthetic setup fixture, which intentionally remains on hold. See
`docs/tooluniverse.md`.

## Documentation

- [Architecture](docs/architecture.md)
- [Scientific boundaries](docs/scientific-boundaries.md)
- [Input and output schema](docs/schema.md)
- [ToolUniverse integration](docs/tooluniverse.md)
- [Plant Evidence Compiler and PhytoResolve](docs/integrations.md)
- [Testing and release evidence](docs/testing.md)
- [Contributing](CONTRIBUTING.md)
- [Security and data handling](SECURITY.md)

## Reproducibility

Canonical JSON uses sorted keys, UTF-8, no NaN values, compact separators, and a single trailing
newline. Capsule validation recomputes all committed hashes. A self-authored manifest proves only
internal consistency. Use `--study` for full semantic recomputation or `--expected-digest` to
authenticate exact bytes against an externally stored digest. The core has no runtime dependencies;
the optional integration is tested against ToolUniverse 1.4.1 exactly.

## License

Apache-2.0. See [LICENSE](LICENSE).
