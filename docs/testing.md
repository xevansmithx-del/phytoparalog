# Testing and release evidence

PhytoParalog uses layered tests because a working Python class does not prove that a packaged CLI,
capsule, or ToolUniverse plugin is discoverable.

## Local checks

```bash
uv sync --frozen --extra dev
uv run --frozen --no-sync pre-commit install
uv run --frozen --no-sync pre-commit run --all-files
uv run --frozen --no-sync ruff check .
uv run --frozen --no-sync ruff format --check .
uv run --frozen --no-sync pytest \
  --cov=phytoparalog --cov=phytoparalog_tu --cov-report=term-missing
uv run --frozen --no-sync python scripts/privacy_scan.py .
uv run --frozen --no-sync python -m build --no-isolation
uv run --frozen --no-sync python -m twine check dist/*
```

Run integration checks in an environment with the optional dependency:

```bash
uv sync --frozen --extra dev --extra tooluniverse --group integrations
uv run --frozen --no-sync pytest tests/test_tooluniverse_plugin.py
uv run --frozen --no-sync pytest tests/test_integration_contracts.py
```

## Test layers

### Core model

- valid closed-schema parsing;
- unknown, missing, malformed, and inconsistent fields;
- exact receipt binding and sequence checksums;
- reference-family and competitive-set relations;
- observation parent cycles and independence receipts;
- equivalence-class identifier and count coverage.

### Compiler

- exact, bounded, subgroup, family-only, and null observed states;
- cross-member exact sequence collapse;
- missing or unverified competitive background;
- compatible outsiders retained in upper bounds;
- declared biological-unit reuse and external-authority holds;
- deterministic output under input reordering;
- no target-selection or scientific-gate authority.

### Capsule

- canonical round trip;
- altered bytes, wrong digest, missing file, and unexpected file;
- repeated compilation byte identity;
- failure before partial output is accepted as a capsule.
- unanchored validation labeled `INTEGRITY_ONLY`, never semantic validation;
- original-study and expected-digest anchoring;
- refreshed-manifest forgery rejected by study recomputation and the original external digest;
- external-digest success explicitly labeled exact-byte integrity only.
- post-validation path changes cannot alter the ToolUniverse summary.

### ToolUniverse

- direct class execution;
- external entry-point registration;
- packaged JSON config loading;
- generated `tu.tools` callables;
- valid fixture calls and structured invalid-input errors;
- schemas with explicit success and error branches;
- names no longer than 55 characters;
- adapter-owned closed validation behind a transport-permissive ToolUniverse parameter schema;
- malformed types, unknown keys, caller operations, and bad digests retain the adapter envelope;
- unanchored external-capsule validation refused;
- fixture validation performed by full-study recomputation.

### Evidence-system contracts

- a real Plant Evidence Compiler `ProjectSpec` produces `NO_RELEASE` with a descriptive ceiling;
- biological identity, function, causal, readiness, and target-selection gates remain on hold;
- a PhytoResolve append requires the original study and exact bound head;
- stale heads, wrong projects, malformed proposals, and rehashed semantic forgeries produce no
  writes;
- all accepted proposal records remain `artifact` events with scientific gates open.

### Public-release hygiene

- no home-directory paths or file URLs;
- no POSIX, Windows, or UNC private paths;
- no high-confidence secret formats, signed credential URLs, or private keys;
- no archive or database accessions in public fixtures;
- no contiguous, wrapped, or grouped biological sequence payloads;
- no symbolic links, undecodable bytes, or binary control content;
- configurable forbidden internal terms;
- source and wheel contain only the intended files.

## Continuous integration

CI runs on supported Python versions with least-privilege workflow permissions. Action versions are
pinned to full commit hashes, uv is pinned to 0.11.20, and dependencies come from the frozen lock.
Separate jobs exercise ToolUniverse 1.4.1 and the immutable Plant Evidence Compiler and
PhytoResolve revisions. Build artifacts are rebuilt twice, compared byte for byte, inspected, and
tested before upload.

## Release policy

Only the `v0.1.0` tag activates the initial release workflow. Its read-only verification job
rebuilds twice from the frozen lock, runs the complete suite, scans public contents, checks package
metadata, installs the wheel into a clean environment, validates the synthetic fixture, and records
SHA-256 checksums. A separate minimal `contents: write` job verifies those checksums and creates the
GitHub release. This workflow deliberately does not publish to PyPI; package-index publication needs
an independently verified trusted-publisher configuration and a later explicit owner decision.

Do not release if a scientific invariant is weakened, a fixture contains real or controlled data,
the ToolUniverse clean-install test is skipped, or the capsule is not byte-deterministic.
