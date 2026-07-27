# Security policy

## Supported versions

MemoryLitmus is an initial MVP. Security fixes are applied to the latest released 0.1.x version and the current development branch. Older snapshots are not maintained.

## Reporting a vulnerability

Use the project's private security-reporting channel where this source is hosted. If no private channel is available, contact the maintainers privately before publishing technical details. Do not place live credentials, personal data, tenant identifiers, production memory exports, or exploit payloads in a public issue.

A useful report contains:

- affected MemoryLitmus version and Python version;
- the adapter/profile/check involved;
- a minimal reproduction using synthetic data;
- security impact and boundary crossed;
- whether the issue also affects the reference adapter;
- suggested mitigation, if known.

Maintainers should acknowledge a complete report within seven days, establish a remediation plan, and coordinate disclosure after a fix. Response timing can vary because this project has no guaranteed commercial support SLA.

## Threat model and limitations

MemoryLitmus tests observable adapter semantics in an isolated test namespace. It is not a sandbox, DLP product, authorization service, cryptographic erasure verifier, or production privacy certification.

Important boundaries:

1. **Adapters are trusted code.** A `module:factory` adapter imports and runs with the invoking Python process's permissions. Only run adapters you trust, in a disposable environment, with least-privilege test credentials.
2. **Never target production state.** `reset()` is destructive by contract. Use an isolated account, database, schema, or namespace created specifically for conformance runs.
3. **Failure messages are report content.** Adapter exceptions can include sensitive backend details. Treat text, JSON, JUnit, and SARIF outputs as potentially sensitive until reviewed.
4. **Fixture secrets are synthetic.** Bundled secret-shaped values are fake. The intentionally broken secret adapter retains them in process so detection can be demonstrated. Never substitute real keys.
5. **Scrubbing is deliberately bounded.** The reference regexes cover fixture patterns; they are not comprehensive secret discovery. Production systems need layered secret detection, encryption, access control, and logging policy.
6. **Hard deletion is an API-level assertion.** The suite checks query/history observability after deletion. It cannot inspect replicas, backups, caches, vendor logs, storage media, or legal-hold systems.
7. **Exact-scope tests are not an authorization audit.** Passing isolation checks does not prove every production endpoint or operator path is isolated.
8. **Report files may reveal topology.** Adapter names, versions, capability declarations, failure text, and check timing can aid reconnaissance.

## Safe test operation

- pin and review external adapter code before import;
- use synthetic fixture data only;
- provision short-lived, least-privilege test credentials;
- deny production network access where possible;
- store reports with restricted access;
- remove isolated test state after the run;
- inspect intentionally broken adapter code before using demonstrations in shared environments.
