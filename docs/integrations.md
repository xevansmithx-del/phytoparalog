# Evidence-system integrations

PhytoParalog produces review inputs; it does not inherit the authority of a downstream evidence
system. The optional adapters preserve that boundary and deliberately refuse to turn
identifiability into identity, function, causality, readiness, or target selection.

## Plant Evidence Compiler

`pec_project_spec(...)` compiles a study, digests the canonical study-lock and identifiability
documents, and returns a real `plant_evidence.models.ProjectSpec`. It does not pass the generic
`pec_candidate_evidence.json` fragment through as though that fragment were a complete PEC input.

```python
from phytoparalog_integrations import pec_project_spec
from plant_evidence.engine import preflight_project

spec = pec_project_spec(study)
decision = preflight_project(spec)
```

The adapter is intentionally conservative:

- the project is nonpublic and contains no original study or stock identifier;
- its maximum claim level is descriptive;
- canonical fixity is diagnostic candidate evidence, so input provenance also remains on hold;
- biological identity, member function, causal interpretation, wet-lab readiness, target
  selection, rights, reproducibility, contradiction review, and manifest review remain on hold;
- the Plant Evidence Compiler remains the authority for its own gate decision.

The tested PEC result is `NO_RELEASE` with a descriptive ceiling. This is a successful safety
contract, not a scientific failure.

## PhytoResolve

PhytoParalog emits proposal-only events bound to the memory head declared by the original study.
Appending requires the original study as well as an explicitly authorized project and actor:

```python
from phytoparalog import compile_study
from phytoparalog_integrations import append_phytoresolve_proposal

proposal = compile_study(study).phytoresolve_proposed_events
result = append_phytoresolve_proposal(
    store,
    proposal,
    study=study,
    expected_project_id="declared-memory-project",
    actor="independent-reviewer",
)
```

Before writing, the helper:

1. recompiles the complete supplied study and requires a byte-for-byte proposal match;
2. validates the proposal's closed schema, event identifiers, and bindings;
3. verifies that the open store has the explicitly named project identifier;
4. verifies the exact bound head and event count;
5. runs the store privacy policy on every proposed event;
6. rechecks the head inside one write transaction; and
7. appends the validated batch atomically.

Any stale head, wrong project, malformed event, or rehashed semantic forgery is refused before a
write. Both compilation summaries and member-level observations are appended as `artifact`
events, never accepted `fact` events. Each event states that scientific gates remain open and no
target was selected.

The helper intentionally uses a narrow portion of the PhytoResolve store API, including its
transaction boundary. Pin and test a supported PhytoResolve revision before release.

## Optional dependencies

The adapters import their independent consumers only when called. Core compilation therefore has
no Plant Evidence Compiler or PhytoResolve runtime dependency. If a consumer is absent,
`pec_project_spec(...)` raises `IntegrationDependencyError`; the proposal validator remains usable
without PhytoResolve, while the append helper requires a compatible store object.
