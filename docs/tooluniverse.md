# ToolUniverse integration

PhytoParalog ships an optional, local ToolUniverse plugin. It uses ToolUniverse's external plugin
entry point and does not patch ToolUniverse source or its default configuration.

## Install and discover

After downloading the wheel from the `v0.1.1` GitHub release:

```bash
python -m pip install 'tooluniverse==1.4.1' ./phytoparalog-0.1.1-py3-none-any.whl
tu list | grep PhytoParalog
```

In Python:

```python
from tooluniverse import ToolUniverse

tu = ToolUniverse()
tu.load_tools(
    include_tools=[
        "PhytoParalog_preflight",
        "PhytoParalog_compile",
        "PhytoParalog_validate_capsule",
    ]
)
```

The plugin registers one class, `PhytoParalogTool`, and ToolUniverse creates three configured
tools from packaged JSON definitions.

## `PhytoParalog_preflight`

Validates a study's closed schema, caller receipt bindings, identifier relations, sequence
checksums, reference membership, equivalence classes, and observation graph. It does not
authenticate receipt authority. It returns aggregate structure only and makes no identifiability
or biological claim.

Supply exactly one of `study` or `fixture_id`. The packaged fixture identifier is
`synthetic-minimal-v1` and exists only to verify installation. Its compilation intentionally
returns `HOLD` with `EXTERNAL_RECEIPT_AUTHORITY_NOT_ESTABLISHED`.

## `PhytoParalog_compile`

Runs deterministic in-memory compilation and returns producer status, hold reasons, schema names,
and canonical SHA-256 digests for the four evidence documents. It does not write a capsule or
persistent state. Use the CLI when files are required.

Supply exactly one of `study` or `fixture_id`.

## `PhytoParalog_validate_capsule`

Recomputes a capsule's canonical hashes and requires an external anchor. Supply either:

- `fixture_id` alone; or
- `capsule_dir` with exactly one of `study` or `expected_capsule_digest`.

An unanchored capsule is rejected. A refreshed self-authored manifest can make altered bytes
internally consistent, so `INTEGRITY_ONLY` must never be laundered into `capsule_valid: true`. The
packaged fixture is compiled in an isolated directory and byte-for-byte recomputed from its study.
Successful responses include `validation_mode`. Full study recomputation returns
`capsule_semantics_trusted: true`. An external digest authenticates exact bytes only, returns
`capsule_semantics_trusted: false` and `EXTERNALLY_ANCHORED_INTEGRITY_ONLY`, and omits untrusted
producer status and hold reasons. The response's `capsule_digest` identifies the validated
snapshot. The adapter never reopens capsule paths after core validation; study-mode status and
holds come from a fresh in-memory compilation of the supplied study.

## Response contract

Success:

```json
{
  "status": "success",
  "data": {},
  "target_selected": false,
  "target_selection": {"allowed": false, "status": "PROHIBITED"}
}
```

Error:

```json
{
  "status": "error",
  "error": "Actionable message",
  "error_code": "STABLE_CODE",
  "remediation": "How to correct the request",
  "target_selected": false,
  "target_selection": {"allowed": false, "status": "PROHIBITED"}
}
```

The tool class catches invalid input, dependency, filesystem, and validation failures and returns
the error contract instead of raising through ToolUniverse. The operation is fixed in each
installed configuration and is not a caller-settable parameter. The transport parameter schemas
are intentionally permissive because ToolUniverse 1.4.1 otherwise replaces schema-invalid results
with its native error object. `PhytoParalogTool` owns closed allowed-key, type, digest-pattern, and
cross-field validation, so malformed and unknown arguments still receive the same strict public
error envelope—with target selection explicitly prohibited—through the loaded interface.

ToolUniverse 1.4.1 validates `return_schema` against the inner `data` object of a success envelope,
not against the full envelope. The installed schemas therefore describe success data only. The
adapter-owned error envelope remains a separate typed contract because `tu test` treats an error
response as a failed call before return-schema validation.

## Registration verification

The integration test suite verifies three distinct levels:

1. direct construction and execution of `PhytoParalogTool`;
2. class and JSON-config registration after plugin discovery;
3. execution through `tu.tools` after a fresh installed load.

It also validates every JSON Schema, checks names are no longer than 55 characters, exercises
success and error paths (including values ToolUniverse would otherwise pre-reject), and confirms
that no output can select or rank a target. Hostile regressions cover refreshed-manifest semantic
forgery and post-validation path changes: only full study recomputation authenticates semantics,
and the adapter never launders reopened file contents into its response.

## Data handling

All operations are local. The adapter performs no HTTP request. A study passed to ToolUniverse can
still contain sensitive sequence and provenance data, so avoid placing it in model-visible logs and
review the resulting capsule before publication.
