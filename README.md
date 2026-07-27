# MemoryLitmus

MemoryLitmus is a zero-runtime-dependency Python 3.9+ conformance suite for **agent-memory semantics**. It is a test harness and executable contract—not a memory store, vector database, or recommendation that every agent use one memory model.

Memory systems make different, legitimate product choices. MemoryLitmus therefore grades adapters against explicit capability profiles. It asks whether an adapter behaves consistently with capabilities it declares; it does not claim that a flat fact model, graph model, event log, or any particular retention policy is universally correct.

## MVP scope

The bundled suite contains 55 deterministic conformance checks (and 98 unit tests) covering:

- repeated-fact deduplication without cross-scope merging;
- explicit correction through bidirectional supersession linkage;
- unlinked conflicting facts, partitioned by exact scope;
- user, agent, project, and session isolation;
- ordered version history and status transitions;
- self, lineage, and linked-lineage deletion;
- unrecoverable hard deletion and recoverable soft tombstones;
- time-aware reads with half-open validity intervals;
- exclusion of superseded nodes from current graph retrieval;
- lexical, vector, and graph stream degradation;
- reciprocal-rank fusion and deterministic fusion fallback;
- reranker failure fallback;
- recursive credential-shaped secret scrubbing;
- scope-filtered lifecycle audit records;
- graded default retention and explicit hard TTL;
- idempotent put/delete replay with event-collision rejection.

The suite also includes an inspectable in-memory reference adapter and intentionally broken adapters that demonstrate detection.

## Requirements and installation

- CPython 3.9 or newer
- no runtime packages outside the Python standard library

From a source checkout:

```sh
python3 -m pip install -e .
memory-litmus run reference --profile full
```

Without installation:

```sh
PYTHONPATH=src python3 -m memory_litmus run reference --profile full
```

A conformant run exits `0`; semantic failures exit `1`; CLI/configuration errors exit `2`.

## CLI

### Discover adapters

```sh
memory-litmus adapters list
memory-litmus adapters list --format json
```

Bundled adapters:

- `reference` — deterministic executable reference;
- `broken-dedup` — creates a record for every repeated fact;
- `broken-isolation` — treats every exact scope as equivalent;
- `broken-secret-scrubbing` — stores credential material verbatim;
- `broken-hard-delete` — silently substitutes soft deletion;
- `broken-stale-graph` — allows superseded graph nodes into current retrieval.

The broken adapters advertise capabilities on purpose. Their non-conformance proves the checks can distinguish a declaration from behavior.

### Run a profile

```sh
memory-litmus run reference --profile core
memory-litmus run reference --profile full --format json
memory-litmus run reference --profile privacy --format junit --output report.xml
memory-litmus run reference --profile resilience --format sarif --output results.sarif
```

External adapters use `module:factory` syntax:

```sh
memory-litmus run my_package.adapter:create_adapter --profile core
```

The target must be a zero-argument class or factory returning an object that implements `memory_litmus.protocol.MemoryAdapter`.

### Inspect profiles and fixtures

```sh
memory-litmus profile show core
memory-litmus profile show full --format json
memory-litmus fixtures list
memory-litmus fixtures list --format json
```

## Capability levels

A profile labels every known capability as:

- **required** — absence is a failure;
- **optional** — absence is a skip, but a declared implementation is tested and can fail;
- **unsupported/outside profile** — not evaluated by that profile.

| Profile | Required emphasis |
| --- | --- |
| `core` | deduplication, supersession, scoped conflicts, four-axis isolation, history, hard deletion, secret scrubbing, idempotent replay |
| `privacy` | isolation, hard deletion, scrubbing, audit, hard TTL |
| `resilience` | time-aware query, multi-stream search, rank fusion, reranker fallback |
| `full` | all 16 capabilities |

Optional does not mean “a failing implementation is acceptable.” It means an adapter may omit the capability. Once advertised in `AdapterMetadata.capabilities`, its checks become normative.

## Reference semantics at a glance

### Exact scope

Every operation carries a `Scope(user_id, agent_id, project_id, session_id)`. The reference adapter requires equality across all four fields for retrieval, history, correction, linking, deletion, deduplication, and scoped audit access.

### Facts, conflicts, and corrections

`fact_key + value + exact scope` identifies a repeated fact for deduplication. A different value for the same key is preserved as an active conflict unless the write explicitly sets `supersedes_id`. Corrections remain in one lineage, increment `version`, and form forward/backward links.

### Time

All boundary datetimes are timezone-aware. Validity and expiry intervals are half-open: a successor is selected at its `valid_from`, and a record is unavailable at its `expires_at`. The supplied `now` argument makes fixtures deterministic; a production adapter may map this to its transaction-time mechanism.

### Retrieval degradation

The reference implementation supplies deterministic lexical, token-overlap “vector,” and link-propagating graph streams. These are fixture engines, not production retrieval algorithms. Healthy streams continue when one stream fails. Reciprocal-rank fusion has a best-score fallback, and reranker failure preserves fused candidates.

### Retention and erasure

Reference defaults are intentionally explicit fixture policy:

- `ephemeral`: one hour;
- `working`: thirty days;
- `durable`: no implicit expiration.

An explicit TTL overrides those defaults. Expired rows are excluded immediately and `purge_expired` physically removes them. Other systems can choose different policy values and expose a compatibility translation in their adapter; MemoryLitmus does not assert these durations are universally optimal.

## Output formats

- `text`: human-oriented pass/fail/skip lines and summary;
- `json`: stable `schema_version: "1.0"` document;
- `junit`: JUnit XML with failures and skipped checks;
- `sarif`: SARIF 2.1.0 rules/results for code-scanning pipelines.

Every result includes the check ID, capability, profile level, fixture, status, duration, and failure message.

## Adapter contract

See [`docs/adapter-contract.md`](docs/adapter-contract.md) for the complete protocol, invariants, failure behavior, replay rules, and a minimal implementation path. A runnable external adapter skeleton is in [`examples/custom_adapter.py`](examples/custom_adapter.py).

Key public types are exported from `memory_litmus`:

```python
from memory_litmus import MemoryAdapter, PutRequest, QueryRequest, Scope
```

Adapters are synchronous in this MVP. Async/network clients should provide a synchronous test shim that makes operations complete before returning.

## Development

Run all local checks:

```sh
./ci/check.sh
```

Or run commands directly:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests examples
PYTHONPATH=src python3 -m memory_litmus run reference --profile full
```

The unit suite materializes every conformance check as its own `unittest` test and verifies CLI, report serialization, profiles, protocol validation, and broken-adapter detection.

## Security and contribution policy

Please read [SECURITY.md](SECURITY.md) before reporting credential-handling or isolation issues. Contributions should follow [CONTRIBUTING.md](CONTRIBUTING.md). Changes are tracked in [CHANGELOG.md](CHANGELOG.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).
