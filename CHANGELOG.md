# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Fail-closed study validation and deterministic paralog identifiability compilation.
- Five-document evidence capsules with SHA-256 commitments.
- Compatibility bounds for ambiguous equivalence classes.
- Optional ToolUniverse plugin with preflight, compile, and capsule-validation tools.
- Synthetic public fixture, privacy scanner, continuous integration, and release checks.

## [0.1.1] - 2026-08-13

### Fixed

- Corrected ToolUniverse 1.4.1 `return_schema` definitions to describe the inner success `data`
  payload, so `tu test` validates all three plugin tools without changing adapter error envelopes
  or scientific compiler behavior.

## [0.1.0] - 2026-08-13

- Initial alpha release candidate.

[Unreleased]: https://github.com/xevansmithx-del/phytoparalog/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/xevansmithx-del/phytoparalog/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/xevansmithx-del/phytoparalog/releases/tag/v0.1.0
