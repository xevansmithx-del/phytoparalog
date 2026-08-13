# Scientific boundaries

PhytoParalog answers an evidence-resolution question. It does not answer which gene should be
edited, whether a gene causes a phenotype, or whether an experiment is ready to execute.

## Diagnostics the compiler may report

Given structurally valid inputs and caller receipt claims, the compiler may report:

- technical identity calculations and conservative copy-collapse conflicts;
- technical member- or subgroup-discriminating sequence diagnostics;
- technical observed-fragment compatibility states;
- technical lower and upper compatibility counts for members, subgroups, and the family;
- the stated biological-independence graph and caller-claimed receipt bindings;
- which explicit hold reasons prevent member-level interpretation;
- deterministic commitments that allow a capsule to be independently revalidated.

Those `technical_*` diagnostics are not admissible scientific evidence. Positive identity,
reference, observation, independence, and count fields remain unresolved, not assessed, zero, or
null until an external authority authenticates the receipts and independently adjudicates them.

## Claims the compiler must not make

PhytoParalog must not claim or imply:

- paralog function from similarity, orthology, annotation, or expression;
- causality from association or differential expression;
- biological absence from zero compatible fragments;
- assay specificity from a family-only reference;
- biological replication from lanes, reruns, or technical replicates;
- phenotype, agronomic value, efficacy, safety, or regulatory acceptability;
- freedom to operate, ownership, consent, or the right to publish data;
- wet-lab readiness or closure of another system's evidence gate;
- a selected, best, top, winning, scored, or recommended biological target.

The CLI, Python API, JSON schemas, ToolUniverse tools, examples, and event proposals are all
designed to enforce this boundary.

## How ambiguity is preserved

An ambiguous equivalence class contributes to every compatible member's upper bound and to no
member's exact lower bound unless the biological member set collapses to one member. No
expectation-maximization allocation is accepted as member-specific evidence for ranking.

The bounds are not uncertainty intervals from a sampling model. They describe feasible allocation
under the declared compatibility relation. Sampling uncertainty, batch effects, and differential
expression belong in downstream analyses with their own assumptions and receipts.

## How null observations are handled

`NO_COMPATIBLE_FRAGMENTS` describes an assay result under a particular reference, library, and
processing workflow. It is never converted to an absence claim. Relevant alternatives include
insufficient depth, tissue mismatch, stage mismatch, degradation, annotation gaps, sequence
divergence, or preprocessing choices.

## How reference evidence is limited

A k-mer unique within the supplied family can still occur elsewhere in the transcriptome, genome,
contaminants, or decoys. Member-discriminator claims therefore require a biologically complete
competitive background and external receipt adjudication that this producer does not perform.
Even then, a discriminator is an opportunity for measurement, not proof that it was observed or
that the member is functional.

## What independent review must still examine

Reviewers should check the biological completeness of the family, reference build and decoys,
source record versions, sample provenance, independence graph, preprocessing and quantifier
settings, equivalence-class extraction, count integrity, tissue and developmental-stage relevance,
and whether the study can legally and ethically be shared.

No software can infer those facts merely because the input is syntactically valid.
