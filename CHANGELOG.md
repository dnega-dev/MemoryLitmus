# Changelog

All notable changes to MemoryLitmus are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and released versions use semantic versioning.

## [Unreleased]

No changes yet.

## [0.1.0]

### Added

- Initial zero-dependency Python 3.9+ MVP.
- Runtime-checkable adapter protocol and serializable boundary dataclasses.
- Required/optional capability profiles: core, privacy, resilience, and full.
- Fifty-five deterministic conformance checks spanning identity, lifecycle, isolation, retrieval resilience, privacy, retention, and replay semantics.
- Bundled deterministic in-memory reference adapter.
- Five intentionally broken adapters for deduplication, isolation, secret scrubbing, hard deletion, and stale-graph detection demonstrations.
- CLI commands `adapters list`, `run`, `profile show`, and `fixtures list`.
- Text, JSON, JUnit XML, and SARIF 2.1.0 reports.
- Ninety-eight standard-library `unittest` tests, including one test per semantic check.
- Adapter-contract documentation, external factory example, project policy files, and `ci/check.sh`.

### Security

- Recursive scrubbing of bundled credential shapes before the reference representation is stored or returned.
- Scope-filtered audit access and synthetic-only security fixtures.
- Explicit documentation of trusted-code, destructive-reset, report-content, and API-level deletion boundaries.
