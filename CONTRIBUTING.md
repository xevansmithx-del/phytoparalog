# Contributing

Thank you for helping make paralog-aware evidence more reproducible. Contributions are welcome
for code, schemas, documentation, adversarial fixtures, and independent validation.

## Scientific invariants

Every contribution must preserve these invariants:

- similarity, orthology, expression, and identifiability do not establish function or causality;
- ambiguous fragments are never silently divided among family members;
- zero compatible fragments are not biological absence;
- technical reruns and lanes do not create biological replication;
- a family-only reference cannot support a member-specific claim;
- no command, field, example, or default may select or rank a biological target;
- compiler outputs are evidence proposals for independent review, never scientific gate closure.

Changes that weaken an invariant require a public design discussion and will normally be rejected.

## Development

1. Use Python 3.10 or newer.
2. Install uv 0.11.20 and run `uv sync --frozen --extra dev`.
3. Activate the repository checks with `uv run --frozen --no-sync pre-commit install`.
4. For integration work, also select `--extra tooluniverse --group integrations`.
5. Add tests before changing behavior.
6. Run the checks documented in `docs/testing.md`.
7. Run `uv run --frozen --no-sync pre-commit run --all-files` and the privacy scanner before
   submitting a pull request.

Use only synthetic, redistribution-safe fixtures. Do not submit unpublished studies, controlled
metadata, real raw sequences, credentials, local filesystem paths, or internal project labels.

## Pull requests

Keep changes focused. Describe the behavior, scientific boundary affected, validation performed,
and any compatibility impact. New states or schemas need deterministic fixtures, negative tests,
and a migration note. Generated artifacts must be reproducible from committed sources.

By submitting a contribution, you agree that it is licensed under Apache-2.0 and that you have the
right to contribute it. Please follow `CODE_OF_CONDUCT.md`.
