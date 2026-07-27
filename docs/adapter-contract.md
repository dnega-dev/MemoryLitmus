# MemoryLitmus adapter contract v1.0

This document defines the synchronous contract consumed by MemoryLitmus 0.1.x. It specifies observable behavior for a declared conformance profile. It does **not** require a particular database, index, graph representation, embedding model, ranking algorithm, or internal memory ontology.

## 1. Loading and lifecycle

The CLI accepts either a bundled adapter name or `module:attribute`. The attribute must be a zero-argument class/factory returning a fresh adapter:

```python
def create_adapter() -> MemoryAdapter:
    return MyAdapter(test_namespace="memory-litmus")
```

The runner creates a probe for metadata and a fresh instance per check, then calls `reset()` before the fixture. `reset()` must remove all state in the adapter's isolated test namespace. Do not point the suite at production data.

Factories must return stable metadata. Changing name or capabilities between calls is a conformance failure.

## 2. Protocol

The runtime-checkable protocol is `memory_litmus.protocol.MemoryAdapter`:

```python
class MemoryAdapter(Protocol):
    def metadata(self) -> AdapterMetadata: ...
    def reset(self) -> None: ...
    def put(self, request: PutRequest, now: Optional[datetime] = None) -> MemoryRecord: ...
    def query(self, request: QueryRequest, now: Optional[datetime] = None) -> QueryResponse: ...
    def history(self, memory_id: str, scope: Scope) -> Sequence[MemoryRecord]: ...
    def delete(self, request: DeleteRequest, now: Optional[datetime] = None) -> DeleteResult: ...
    def audit_log(self, scope: Optional[Scope] = None) -> Sequence[AuditEvent]: ...
    def purge_expired(self, now: Optional[datetime] = None) -> Sequence[str]: ...
```

All methods complete synchronously. An adapter around async or remote infrastructure may block inside this test boundary.

### Clock injection

`now` is a deterministic fixture clock, not user content. If omitted, adapters may use current UTC. If supplied, it must govern current visibility, deletion time, replay audit time, and TTL purge behavior. All datetimes crossing the contract are timezone-aware; naive values must be rejected rather than interpreted in a machine-local zone.

## 3. Metadata and capability levels

`metadata()` returns:

- `name`: non-empty stable adapter identifier;
- `version`: non-empty adapter contract/implementation version;
- `capabilities`: `frozenset[Capability]`;
- `description`: human-readable summary.

Profiles apply three levels:

1. **required**: the capability must be declared and all checks must pass;
2. **optional**: an undeclared capability is skipped; a declared capability is tested normally;
3. **unsupported/outside profile**: checks are not evaluated in that profile.

A capability declaration is a behavioral promise. Do not advertise a feature merely because a backing service has a similarly named API.

| Capability | Required observable behavior |
| --- | --- |
| `deduplication` | Repeating identical key/value in exact scope resolves to one active record and stable ID; scopes never merge. |
| `supersession` | Explicit correction preserves lineage, increments version, links both directions, and excludes predecessor from current reads. |
| `scoped_conflicts` | Different values without explicit correction coexist, partitioned by exact scope. |
| `isolation` | User, agent, project, and session boundaries apply to all relevant operations. |
| `version_history` | Complete lineage is returned in version order with lifecycle status. |
| `linked_lineage_delete` | `SELF`, `LINEAGE`, and `LINKED_LINEAGE` have distinct, deterministic reach. |
| `hard_delete` | Hard-erased content is absent from retrieval and history; soft deletion retains a tombstone. |
| `time_aware_query` | `as_of` reads select the version valid at a half-open time interval. |
| `multi_stream_search` | Lexical/vector/graph outages are reported while healthy streams continue; stale graph nodes cannot contribute. |
| `rank_fusion` | Stream provenance is retained; fusion failure uses deterministic candidate fallback. |
| `reranker_fallback` | A failed reranker preserves fused candidates and reports fallback. |
| `secret_scrubbing` | Credential-shaped strings in values and nested metadata are redacted before persistence/return. |
| `audit` | Mutation lifecycle, scope, subject IDs, outcome, and time are recorded without raw secrets. |
| `graded_retention` | Retention classes produce ordered, explicit horizons. |
| `hard_ttl` | Expiry is enforced at the boundary; purge physically removes expired history. |
| `idempotent_replay` | Same event and payload returns prior result without a second mutation; event/payload collision is rejected. |

## 4. Exact scope

`Scope` contains four required strings:

```text
(user_id, agent_id, project_id, session_id)
```

The v1 reference profile uses exact equality. Deduplication, linking, correction, reads, history, deletion, and filtered audits cannot cross any dimension. A product with hierarchical or inherited memory should map that policy into a test-specific exact-scope view. The suite does not claim exact scopes are the only valid production access model; they are the isolation contract tested here.

A cross-scope correction/link/delete should raise `PermissionError` or `ValueError`. A cross-scope history lookup must return an empty sequence rather than reveal existence.

## 5. Write semantics

`PutRequest` fields:

- `event_id`: required idempotency key;
- `scope`: exact boundary;
- `fact_key`, `value`: fact payload;
- `observed_at`: validity start, defaults to injected `now`;
- `supersedes_id`: optional explicit predecessor;
- `links`: zero or more in-scope memory IDs;
- `retention`: `EPHEMERAL`, `WORKING`, or `DURABLE`;
- `ttl_seconds`: optional non-negative hard TTL override;
- `metadata`: JSON-like auxiliary fields.

### Deduplication

Without `supersedes_id`, an active record with the same scrubbed `fact_key`, scrubbed `value`, and exact scope is a duplicate. Return the existing `MemoryRecord`; do not create another version or lineage. A distinct `event_id` can still deduplicate by fact identity.

### Conflicts

A different value is not automatically a correction. It remains a separate active lineage unless the request explicitly names `supersedes_id`. This prevents chronology alone from silently destroying potentially valid conflicting evidence.

### Correction

The predecessor must exist, be active, be in exact scope, and have the same `fact_key`. The successor:

- retains `lineage_id`;
- has `version = predecessor.version + 1`;
- sets `supersedes_id` to the predecessor;
- causes the predecessor to set `superseded_by_id`, `status=SUPERSEDED`, and `valid_to=successor.valid_from`.

Intervals are half-open: predecessor validity ends exactly where successor validity begins.

## 6. Query and retrieval resilience

`QueryRequest` can filter `fact_key`, search `text`, select `streams`, request `as_of`, and cap `limit`. The failure flags are deterministic injection points for the conformance fixture:

- `fail_streams`: named stream outages;
- `fail_fusion`: rank-fusion outage;
- `use_reranker` / `fail_reranker`: reranking path and outage.

A production shim may translate these flags to controlled fake clients or test hooks. It must not trigger real service disruption.

`QueryResponse` includes:

- ordered `SearchHit` values;
- `degraded_streams`;
- `fusion_fallback`;
- `reranker_fallback`.

Each hit names contributing streams. If all requested streams fail, return zero hits and list every degraded stream; do not invent candidates.

Current queries only admit `ACTIVE` records whose validity has started, deletion has not occurred, and TTL has not expired. Historical queries select the retained record valid at `as_of`; hard TTL is still evaluated against the query clock, so an old `as_of` cannot resurrect expired data. A superseded graph node is ineligible before both direct scoring and graph propagation, preventing stale relevance from leaking through an active neighbor.

The bundled lexical/token-overlap/graph algorithms are deterministic fixture machinery, not a quality benchmark for production retrieval.

## 7. History and deletion

`history(memory_id, scope)` returns all currently retained versions in one lineage, ascending by version. Soft-deleted rows remain with `status=DELETED`; hard-deleted rows do not.

`DeleteRequest` has its own idempotent `event_id` and two axes:

- mode: `SOFT` or `HARD`;
- cascade: `SELF`, `LINEAGE`, or `LINKED_LINEAGE`.

`LINEAGE` includes every version sharing the anchor lineage but does not follow general links. `LINKED_LINEAGE` computes the in-scope connected closure across links, then includes every version in each selected lineage. Link traversal never crosses exact scope.

Hard deletion means the suite cannot recover content through `query`, `history`, or a replayed original `put`; adapters must erase any cached replay result that contains the record. Backing-service backups and legal retention are deployment concerns outside this in-process contract and should be documented by an implementation.

## 8. Retention and TTL

Reference fixture defaults are:

| Retention class | Default expiry |
| --- | --- |
| `EPHEMERAL` | `valid_from + 1 hour` |
| `WORKING` | `valid_from + 30 days` |
| `DURABLE` | none |

Explicit `ttl_seconds` overrides the class default, including for durable records. Visibility uses `[valid_from, expires_at)`: a row is unavailable exactly at expiry, including through historical query or idempotent put replay. `purge_expired(now)` returns purged IDs and hard-deletes their history.

These numeric horizons are a conformance fixture policy, not a universal memory prescription. An adapter can map product categories to this profile inside an isolated conformance namespace.

## 9. Secret scrubbing

Scrubbing occurs before the returned/persisted representation is created. It recursively handles strings in nested metadata and covers at least the bundled credential patterns:

- `sk-...` key shapes;
- AWS access-key IDs (`AKIA...`);
- bearer tokens;
- assignments to password, API-key, access-token, and secret labels.

The reference scrubber is intentionally small and deterministic; it is not a substitute for a production DLP system. Audit serialization must not contain original secret material.

## 10. Audit

Audit events include:

- the input mutation `event_id`, or a generated read/purge ID;
- operation (`put`, `query`, `history`, `delete`, or `purge`);
- timezone-aware timestamp;
- affected or returned subject IDs;
- exact scope;
- outcome (`created`, `deduplicated`, `superseded`, `returned`, `deleted`, `hard_deleted`, `replayed`, or `not_found`);
- scrubbed operational details.

`audit_log(scope)` returns only exact-scope events. `audit_log(None)` returns all events in the adapter's isolated namespace.

## 11. Idempotent replay

An event ID binds to a canonical mutation payload. Repeating the same payload:

- returns the original put record or deleted-ID set while that result remains retention-eligible;
- does not create/delete state twice;
- may add a `replayed` audit outcome;
- marks replayed delete results with `replayed=True`.

A replayed put whose result was hard-deleted or reached hard TTL raises `KeyError` rather than disclosing erased content. Event IDs share one mutation namespace: an ID used for `put` cannot later identify `delete`, or vice versa. Reusing an event ID with a different operation or semantic payload raises `ValueError`, even if the first target has since been hard-deleted.

## 12. Error and serialization expectations

- Invalid model inputs raise `ValueError`.
- Missing referenced IDs raise `KeyError`.
- Cross-scope mutation attempts raise `PermissionError` or `ValueError`.
- Injected retrieval component failures are represented as degradation/fallback, not raised through `query`.
- Public result objects are dataclasses with deterministic `to_dict()` conversion.

The runner catches adapter/check exceptions and records their type and message as a failed result. It never treats an exception as a skip.

## 13. Minimal validation loop

```sh
PYTHONPATH=src python3 -m memory_litmus adapters list
PYTHONPATH=src python3 -m memory_litmus run your_module:create_adapter --profile core
PYTHONPATH=src python3 -m memory_litmus run your_module:create_adapter --profile full --format junit --output report.xml
```

Start by advertising only capabilities actually implemented. Optional undeclared capabilities skip; declared but incorrect capabilities fail.
