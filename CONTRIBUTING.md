# Contributing to MemoryLitmus

Thank you for improving MemoryLitmus. Contributions should make memory semantics more explicit, testable, deterministic, and model-neutral.

## Design principles

1. **Conformance suite, not store.** Do not add persistence services or turn the reference adapter into a production database.
2. **No universal-model claims.** Describe behavior as a named capability/profile contract. A different memory ontology can be legitimate.
3. **Zero runtime dependencies.** The package must run on Python 3.9+ using only the standard library.
4. **Observable behavior over implementation.** Tests should not inspect private tables, graph schemas, model prompts, or vendor-specific internals.
5. **Deterministic fixtures.** Inject timezone-aware clocks and controlled failures. Do not require network access, model APIs, or nondeterministic embeddings.
6. **Safe isolation.** External adapters must use disposable test namespaces. No fixture may contain a real credential or personal record.

## Development setup

A local install is optional:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .
```

Run the complete project check:

```sh
./ci/check.sh
```

Its equivalent core commands are:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests examples
PYTHONPATH=src python3 -m memory_litmus run reference --profile full
```

Keep code compatible with Python 3.9: avoid newer-only syntax and standard-library APIs.

## Changing a semantic check

A semantic change should include:

- a focused function in `src/memory_litmus/checks.py`;
- a stable, unique check ID;
- one declared `Capability` and fixture name;
- a deterministic setup using the injected clock;
- an assertion message that explains the violated behavior;
- reference-adapter support;
- at least one intentionally broken behavior or focused unit test proving the check can fail;
- adapter-contract and changelog updates.

Every catalog check is automatically exposed as a distinct `unittest` method by `tests/test_reference_conformance.py`.

Do not weaken a test solely to accommodate one product. If two policies are both useful, introduce separate capability/profile language or document an adapter translation.

## Adding a capability

1. Add the enum member in `models.py`.
2. Define its boundary types without third-party dependencies.
3. Place it in each profile as required, optional, or outside-profile.
4. Add one or more fixtures and substantive conformance checks.
5. Implement reference behavior and, where useful, an intentional break.
6. Update CLI-visible docs, the contract table, README, and changelog.
7. Verify JSON, JUnit, and SARIF remain backwards-consumable. A breaking report-schema change requires a schema-version change.

## Adapter contributions

Bundled production-vendor adapters are out of scope for this MVP. Adapter examples must:

- use a zero-argument class/factory;
- return fresh instances with stable metadata;
- make `reset()` safe and isolated;
- advertise only implemented capabilities;
- avoid network access in the repository test suite;
- document any translation from product policy to fixture policy.

## Style

- Prefer small standard-library modules and explicit dataclasses.
- Use type hints that are valid on Python 3.9.
- Keep public types documented and serializable.
- Avoid timing-sensitive sleeps; use injected datetimes.
- Preserve exit codes: `0` conformant, `1` semantic failure, `2` configuration/CLI error.
- Keep output deterministic apart from measured duration.

## Documentation and changelog

Update `CHANGELOG.md` under **Unreleased** for user-visible behavior. Explain semantic trade-offs and fixture policy, not just code mechanics. Examples must use synthetic values.

## Security reports

Do not disclose vulnerabilities or live secrets in a public contribution. Follow `SECURITY.md`.

## License

By contributing, you agree that your contribution is licensed under the Apache License 2.0.
