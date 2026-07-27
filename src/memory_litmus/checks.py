"""Executable conformance checks.

Checks intentionally describe observable behavior and avoid prescribing storage
internals. Each check receives a fresh adapter instance from the runner.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Dict, Mapping, Tuple, Type

from .fixtures import (
    BASE_TIME,
    OTHER_AGENT_SCOPE,
    OTHER_PROJECT_SCOPE,
    OTHER_SESSION_SCOPE,
    OTHER_USER_SCOPE,
    PRIMARY_SCOPE,
    at,
)
from .models import (
    Capability,
    DeleteCascade,
    DeleteMode,
    DeleteRequest,
    PutRequest,
    QueryRequest,
    RecordStatus,
    RetentionClass,
    Scope,
)
from .protocol import MemoryAdapter


CheckFunction = Callable[[MemoryAdapter], None]


@dataclass(frozen=True)
class ConformanceCheck:
    id: str
    title: str
    capability: Capability
    fixture: str
    function: CheckFunction

    def to_dict(self) -> Dict[str, str]:
        return {
            "id": self.id,
            "title": self.title,
            "capability": self.capability.value,
            "fixture": self.fixture,
        }


def _put(
    adapter: MemoryAdapter,
    event_id: str,
    key: str,
    value: str,
    *,
    scope: Scope = PRIMARY_SCOPE,
    now=BASE_TIME,
    observed_at=None,
    supersedes_id=None,
    links=(),
    retention=RetentionClass.DURABLE,
    ttl_seconds=None,
    metadata=None,
):
    return adapter.put(
        PutRequest(
            event_id=event_id,
            scope=scope,
            fact_key=key,
            value=value,
            observed_at=observed_at,
            supersedes_id=supersedes_id,
            links=tuple(links),
            retention=retention,
            ttl_seconds=ttl_seconds,
            metadata=metadata or {},
        ),
        now=now,
    )


def _ids(response) -> Tuple[str, ...]:
    return tuple(hit.record.id for hit in response.hits)


def _query(adapter: MemoryAdapter, *, scope=PRIMARY_SCOPE, now=BASE_TIME, **kwargs):
    return adapter.query(QueryRequest(scope=scope, **kwargs), now=now)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _expect_raises(error_type: Type[BaseException], operation: Callable[[], object], message: str) -> None:
    try:
        operation()
    except error_type:
        return
    except Exception as error:
        raise AssertionError("%s; got %s instead" % (message, type(error).__name__))
    raise AssertionError(message)


def dedup_returns_stable_identity(adapter: MemoryAdapter) -> None:
    first = _put(adapter, "dedup-1", "timezone", "UTC")
    second = _put(adapter, "dedup-2", "timezone", "UTC", now=at(seconds=1))
    _require(first.id == second.id, "repeated fact must resolve to one stable record identity")


def dedup_keeps_one_active_result(adapter: MemoryAdapter) -> None:
    _put(adapter, "dedup-count-1", "language", "Python")
    _put(adapter, "dedup-count-2", "language", "Python", now=at(seconds=1))
    response = _query(adapter, fact_key="language", now=at(seconds=2))
    _require(len(response.hits) == 1, "repeated fact must not create duplicate active hits")


def dedup_does_not_cross_scope(adapter: MemoryAdapter) -> None:
    first = _put(adapter, "dedup-scope-1", "timezone", "UTC")
    second = _put(
        adapter,
        "dedup-scope-2",
        "timezone",
        "UTC",
        scope=OTHER_USER_SCOPE,
        now=at(seconds=1),
    )
    _require(first.id != second.id, "deduplication must not merge records across scopes")


def supersession_links_both_directions(adapter: MemoryAdapter) -> None:
    first = _put(adapter, "correct-1", "city", "Paris")
    second = _put(
        adapter,
        "correct-2",
        "city",
        "Lyon",
        now=at(hours=1),
        observed_at=at(hours=1),
        supersedes_id=first.id,
    )
    history = adapter.history(second.id, PRIMARY_SCOPE)
    by_id = {record.id: record for record in history}
    _require(second.supersedes_id == first.id, "new version must point to superseded record")
    _require(by_id[first.id].superseded_by_id == second.id, "old version must point to correction")


def supersession_increments_version(adapter: MemoryAdapter) -> None:
    first = _put(adapter, "version-1", "city", "Paris")
    second = _put(
        adapter,
        "version-2",
        "city",
        "Lyon",
        now=at(hours=1),
        observed_at=at(hours=1),
        supersedes_id=first.id,
    )
    _require(first.lineage_id == second.lineage_id, "correction must retain lineage identity")
    _require(second.version == first.version + 1, "correction must increment lineage version")


def superseded_fact_excluded_from_current_query(adapter: MemoryAdapter) -> None:
    first = _put(adapter, "stale-current-1", "city", "Paris")
    second = _put(
        adapter,
        "stale-current-2",
        "city",
        "Lyon",
        now=at(hours=1),
        observed_at=at(hours=1),
        supersedes_id=first.id,
    )
    response = _query(adapter, fact_key="city", now=at(hours=2))
    _require(_ids(response) == (second.id,), "current query must exclude superseded version")


def supersession_rejects_cross_scope_target(adapter: MemoryAdapter) -> None:
    first = _put(adapter, "cross-correction-1", "city", "Paris")
    _expect_raises(
        (PermissionError, ValueError),
        lambda: _put(
            adapter,
            "cross-correction-2",
            "city",
            "Lyon",
            scope=OTHER_USER_SCOPE,
            supersedes_id=first.id,
        ),
        "correction must not cross scope",
    )


def conflicting_values_coexist_without_explicit_correction(adapter: MemoryAdapter) -> None:
    first = _put(adapter, "conflict-1", "favorite_color", "blue")
    second = _put(adapter, "conflict-2", "favorite_color", "green", now=at(seconds=1))
    response = _query(adapter, fact_key="favorite_color", now=at(seconds=2))
    _require(set(_ids(response)) == {first.id, second.id}, "unlinked conflicting facts must coexist")


def conflicts_are_partitioned_by_scope(adapter: MemoryAdapter) -> None:
    _put(adapter, "conflict-scope-1", "timezone", "UTC")
    other = _put(
        adapter,
        "conflict-scope-2",
        "timezone",
        "PST",
        scope=OTHER_PROJECT_SCOPE,
    )
    primary = _query(adapter, fact_key="timezone")
    secondary = _query(adapter, fact_key="timezone", scope=OTHER_PROJECT_SCOPE)
    _require(len(primary.hits) == 1, "primary scope must see only its own conflict member")
    _require(_ids(secondary) == (other.id,), "other scope must see only its own conflict member")


def _isolation_axis(adapter: MemoryAdapter, other_scope: Scope, label: str) -> None:
    own = _put(adapter, "isolation-%s-own" % label, "marker", "own")
    other = _put(
        adapter,
        "isolation-%s-other" % label,
        "marker",
        "other",
        scope=other_scope,
        now=at(seconds=1),
    )
    own_ids = set(_ids(_query(adapter, fact_key="marker", now=at(seconds=2))))
    other_ids = set(
        _ids(_query(adapter, fact_key="marker", scope=other_scope, now=at(seconds=2)))
    )
    _require(own_ids == {own.id}, "%s isolation leaked into primary scope" % label)
    _require(other_ids == {other.id}, "%s isolation leaked into alternate scope" % label)


def user_isolation(adapter: MemoryAdapter) -> None:
    _isolation_axis(adapter, OTHER_USER_SCOPE, "user")


def agent_isolation(adapter: MemoryAdapter) -> None:
    _isolation_axis(adapter, OTHER_AGENT_SCOPE, "agent")


def project_isolation(adapter: MemoryAdapter) -> None:
    _isolation_axis(adapter, OTHER_PROJECT_SCOPE, "project")


def session_isolation(adapter: MemoryAdapter) -> None:
    _isolation_axis(adapter, OTHER_SESSION_SCOPE, "session")


def history_is_scope_isolated(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "history-isolation", "marker", "own")
    _require(
        tuple(adapter.history(record.id, OTHER_SESSION_SCOPE)) == (),
        "history lookup must not expose a record across scope",
    )


def history_orders_complete_version_chain(adapter: MemoryAdapter) -> None:
    one = _put(adapter, "history-1", "office", "A", observed_at=BASE_TIME)
    two = _put(
        adapter,
        "history-2",
        "office",
        "B",
        now=at(hours=1),
        observed_at=at(hours=1),
        supersedes_id=one.id,
    )
    three = _put(
        adapter,
        "history-3",
        "office",
        "C",
        now=at(hours=2),
        observed_at=at(hours=2),
        supersedes_id=two.id,
    )
    history = adapter.history(three.id, PRIMARY_SCOPE)
    _require([record.id for record in history] == [one.id, two.id, three.id], "history incomplete")
    _require([record.version for record in history] == [1, 2, 3], "history not version ordered")


def history_preserves_status_transitions(adapter: MemoryAdapter) -> None:
    one = _put(adapter, "history-status-1", "office", "A")
    two = _put(
        adapter,
        "history-status-2",
        "office",
        "B",
        now=at(hours=1),
        observed_at=at(hours=1),
        supersedes_id=one.id,
    )
    history = adapter.history(two.id, PRIMARY_SCOPE)
    _require(history[0].status is RecordStatus.SUPERSEDED, "old history row must be superseded")
    _require(history[1].status is RecordStatus.ACTIVE, "latest history row must be active")


def lineage_delete_removes_every_version(adapter: MemoryAdapter) -> None:
    one = _put(adapter, "lineage-delete-1", "office", "A")
    two = _put(
        adapter,
        "lineage-delete-2",
        "office",
        "B",
        now=at(hours=1),
        observed_at=at(hours=1),
        supersedes_id=one.id,
    )
    result = adapter.delete(
        DeleteRequest(
            event_id="lineage-delete-event",
            scope=PRIMARY_SCOPE,
            memory_id=one.id,
            mode=DeleteMode.HARD,
            cascade=DeleteCascade.LINEAGE,
        ),
        now=at(hours=2),
    )
    _require(set(result.deleted_ids) == {one.id, two.id}, "lineage delete must erase every version")
    _require(tuple(adapter.history(two.id, PRIMARY_SCOPE)) == (), "hard-erased lineage remained in history")


def linked_lineage_delete_traverses_links(adapter: MemoryAdapter) -> None:
    one = _put(adapter, "linked-delete-1", "person", "Ada")
    two = _put(
        adapter,
        "linked-delete-2",
        "person",
        "Ada Lovelace",
        now=at(hours=1),
        observed_at=at(hours=1),
        supersedes_id=one.id,
    )
    linked_one = _put(adapter, "linked-delete-3", "project", "Engine", links=(two.id,))
    linked_two = _put(
        adapter,
        "linked-delete-4",
        "project",
        "Analytical Engine",
        now=at(hours=2),
        observed_at=at(hours=2),
        supersedes_id=linked_one.id,
    )
    result = adapter.delete(
        DeleteRequest(
            event_id="linked-delete-event",
            scope=PRIMARY_SCOPE,
            memory_id=one.id,
            mode=DeleteMode.HARD,
            cascade=DeleteCascade.LINKED_LINEAGE,
        ),
        now=at(hours=3),
    )
    _require(
        set(result.deleted_ids) == {one.id, two.id, linked_one.id, linked_two.id},
        "linked-lineage delete must traverse links and include all versions",
    )


def lineage_delete_does_not_follow_links(adapter: MemoryAdapter) -> None:
    root = _put(adapter, "lineage-only-1", "person", "Ada")
    linked = _put(adapter, "lineage-only-2", "project", "Engine", links=(root.id,))
    adapter.delete(
        DeleteRequest(
            event_id="lineage-only-delete",
            scope=PRIMARY_SCOPE,
            memory_id=root.id,
            mode=DeleteMode.HARD,
            cascade=DeleteCascade.LINEAGE,
        ),
        now=at(hours=1),
    )
    _require(_ids(_query(adapter, fact_key="project", now=at(hours=2))) == (linked.id,), "lineage-only delete followed a graph link")


def links_cannot_cross_scope(adapter: MemoryAdapter) -> None:
    other = _put(adapter, "cross-link-1", "other", "value", scope=OTHER_USER_SCOPE)
    _expect_raises(
        (PermissionError, ValueError),
        lambda: _put(adapter, "cross-link-2", "own", "value", links=(other.id,)),
        "link creation must not cross exact scope",
    )


def hard_delete_removes_query_and_history(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "hard-delete-1", "erase", "me")
    adapter.delete(
        DeleteRequest("hard-delete-event", PRIMARY_SCOPE, record.id, DeleteMode.HARD),
        now=at(minutes=1),
    )
    _require(not _query(adapter, fact_key="erase", now=at(minutes=2)).hits, "hard-deleted record is queryable")
    _require(not adapter.history(record.id, PRIMARY_SCOPE), "hard-deleted record is recoverable via history")


def hard_delete_prevents_replay_recovery(adapter: MemoryAdapter) -> None:
    request = PutRequest(
        "hard-delete-replay-put",
        PRIMARY_SCOPE,
        "erase",
        "sensitive value",
        retention=RetentionClass.DURABLE,
    )
    record = adapter.put(request, now=BASE_TIME)
    adapter.delete(
        DeleteRequest(
            "hard-delete-replay-event",
            PRIMARY_SCOPE,
            record.id,
            DeleteMode.HARD,
        ),
        now=at(minutes=1),
    )
    _expect_raises(
        KeyError,
        lambda: adapter.put(request, now=at(minutes=2)),
        "idempotent replay must not recover a hard-deleted put result",
    )


def soft_delete_retains_tombstoned_history(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "soft-delete-1", "erase", "later")
    adapter.delete(
        DeleteRequest("soft-delete-event", PRIMARY_SCOPE, record.id, DeleteMode.SOFT),
        now=at(minutes=1),
    )
    history = adapter.history(record.id, PRIMARY_SCOPE)
    _require(len(history) == 1 and history[0].status is RecordStatus.DELETED, "soft delete must retain tombstone")
    _require(not _query(adapter, fact_key="erase", now=at(minutes=2)).hits, "soft tombstone must not be current")


def delete_rejects_cross_scope_target(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "cross-delete-1", "erase", "no")
    _expect_raises(
        (PermissionError, ValueError),
        lambda: adapter.delete(
            DeleteRequest("cross-delete-event", OTHER_PROJECT_SCOPE, record.id, DeleteMode.HARD),
            now=at(minutes=1),
        ),
        "deletion must not cross scope",
    )


def historical_query_selects_pre_correction_version(adapter: MemoryAdapter) -> None:
    one = _put(adapter, "asof-before-1", "city", "Paris", observed_at=BASE_TIME)
    _put(
        adapter,
        "asof-before-2",
        "city",
        "Lyon",
        now=at(hours=2),
        observed_at=at(hours=2),
        supersedes_id=one.id,
    )
    response = _query(adapter, fact_key="city", as_of=at(hours=1), now=at(hours=3))
    _require(_ids(response) == (one.id,), "historical query before correction must return old version")


def historical_query_selects_post_correction_version(adapter: MemoryAdapter) -> None:
    one = _put(adapter, "asof-after-1", "city", "Paris", observed_at=BASE_TIME)
    two = _put(
        adapter,
        "asof-after-2",
        "city",
        "Lyon",
        now=at(hours=2),
        observed_at=at(hours=2),
        supersedes_id=one.id,
    )
    response = _query(adapter, fact_key="city", as_of=at(hours=3), now=at(hours=4))
    _require(_ids(response) == (two.id,), "historical query after correction must return new version")


def correction_boundary_is_half_open(adapter: MemoryAdapter) -> None:
    one = _put(adapter, "asof-boundary-1", "city", "Paris", observed_at=BASE_TIME)
    two = _put(
        adapter,
        "asof-boundary-2",
        "city",
        "Lyon",
        now=at(hours=2),
        observed_at=at(hours=2),
        supersedes_id=one.id,
    )
    response = _query(adapter, fact_key="city", as_of=at(hours=2), now=at(hours=3))
    _require(_ids(response) == (two.id,), "correction boundary must select successor, not both versions")


def future_observation_is_not_yet_visible(adapter: MemoryAdapter) -> None:
    record = _put(
        adapter,
        "future-1",
        "appointment",
        "tomorrow",
        observed_at=at(days=1),
    )
    before = _query(adapter, fact_key="appointment", now=BASE_TIME)
    after = _query(adapter, fact_key="appointment", now=at(days=2))
    _require(record.id not in _ids(before), "future-valid fact appeared early")
    _require(record.id in _ids(after), "future-valid fact did not appear after valid_from")


def stale_graph_nodes_are_excluded(adapter: MemoryAdapter) -> None:
    stale = _put(adapter, "stale-graph-1", "codename", "orion", observed_at=BASE_TIME)
    _put(adapter, "stale-graph-link", "neighbor", "unrelated", links=(stale.id,))
    _put(
        adapter,
        "stale-graph-2",
        "codename",
        "apollo",
        now=at(hours=1),
        observed_at=at(hours=1),
        supersedes_id=stale.id,
    )
    response = _query(adapter, text="orion", streams=("graph",), now=at(hours=2))
    _require(stale.id not in _ids(response), "superseded graph node appeared in current retrieval")
    _require(not response.hits, "stale graph node propagated relevance to active neighbors")


def _stream_degrades(adapter: MemoryAdapter, failed: str) -> None:
    record = _put(adapter, "stream-%s" % failed, "launch", "alpha target")
    response = _query(
        adapter,
        text="alpha",
        fail_streams=frozenset({failed}),
        now=at(minutes=1),
    )
    _require(response.degraded_streams == (failed,), "%s failure was not reported" % failed)
    _require(record.id in _ids(response), "%s failure prevented healthy streams from answering" % failed)


def lexical_stream_failure_degrades(adapter: MemoryAdapter) -> None:
    _stream_degrades(adapter, "lexical")


def vector_stream_failure_degrades(adapter: MemoryAdapter) -> None:
    _stream_degrades(adapter, "vector")


def graph_stream_failure_degrades(adapter: MemoryAdapter) -> None:
    _stream_degrades(adapter, "graph")


def all_streams_failure_is_explicit(adapter: MemoryAdapter) -> None:
    _put(adapter, "all-streams", "launch", "alpha target")
    response = _query(
        adapter,
        text="alpha",
        fail_streams=frozenset({"lexical", "vector", "graph"}),
        now=at(minutes=1),
    )
    _require(not response.hits, "all failed streams must not fabricate results")
    _require(set(response.degraded_streams) == {"lexical", "vector", "graph"}, "degradation incomplete")


def rank_fusion_records_contributing_streams(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "fusion-normal", "launch", "alpha target")
    response = _query(adapter, text="alpha", now=at(minutes=1))
    _require(record.id in _ids(response), "rank fusion lost matching record")
    hit = next(hit for hit in response.hits if hit.record.id == record.id)
    _require(set(hit.streams) == {"lexical", "vector", "graph"}, "fusion omitted stream provenance")
    _require(not response.fusion_fallback, "normal fusion incorrectly marked fallback")


def rank_fusion_failure_falls_back(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "fusion-fallback", "launch", "alpha target")
    response = _query(adapter, text="alpha", fail_fusion=True, now=at(minutes=1))
    _require(response.fusion_fallback, "fusion failure did not activate fallback")
    _require(record.id in _ids(response), "fusion fallback failed to return healthy-stream candidate")


def reranker_failure_preserves_candidates(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "reranker-fallback", "launch", "alpha target")
    response = _query(
        adapter,
        text="alpha",
        use_reranker=True,
        fail_reranker=True,
        now=at(minutes=1),
    )
    _require(response.reranker_fallback, "reranker failure did not activate fallback")
    _require(record.id in _ids(response), "reranker failure discarded fused candidates")


def healthy_reranker_does_not_mark_fallback(adapter: MemoryAdapter) -> None:
    _put(adapter, "reranker-healthy", "launch", "alpha target")
    response = _query(adapter, text="alpha", use_reranker=True, now=at(minutes=1))
    _require(not response.reranker_fallback, "healthy reranker incorrectly marked fallback")
    _require(bool(response.hits), "healthy reranker discarded candidates")


def secret_scrubbing_redacts_record_value(adapter: MemoryAdapter) -> None:
    secret = "sk-abcdefgh12345678"
    record = _put(adapter, "secret-value", "note", "credential %s" % secret)
    _require(secret not in record.value, "credential persisted in record value")
    _require("[REDACTED]" in record.value, "redaction marker missing from record value")


def secret_scrubbing_redacts_nested_metadata(adapter: MemoryAdapter) -> None:
    secret = "Bearer abcdefghijklmnop"
    record = _put(
        adapter,
        "secret-metadata",
        "note",
        "safe",
        metadata={"nested": {"authorization": secret}, "password": "password=hunter2"},
    )
    encoded = json.dumps(record.metadata, sort_keys=True)
    _require("abcdefghijklmnop" not in encoded and "hunter2" not in encoded, "metadata leaked a secret")
    _require("[REDACTED]" in encoded, "metadata lacks redaction marker")


def audit_covers_lifecycle_mutations(adapter: MemoryAdapter) -> None:
    first = _put(adapter, "audit-create", "city", "Paris")
    _put(adapter, "audit-dedup", "city", "Paris", now=at(seconds=1))
    corrected = _put(
        adapter,
        "audit-correct",
        "city",
        "Lyon",
        now=at(hours=1),
        observed_at=at(hours=1),
        supersedes_id=first.id,
    )
    adapter.delete(
        DeleteRequest("audit-delete", PRIMARY_SCOPE, corrected.id, DeleteMode.SOFT),
        now=at(hours=2),
    )
    _put(
        adapter,
        "audit-ttl",
        "temporary",
        "soon gone",
        now=at(hours=2),
        observed_at=at(hours=2),
        ttl_seconds=1,
    )
    adapter.purge_expired(now=at(hours=2, seconds=2))
    events = adapter.audit_log(PRIMARY_SCOPE)
    outcomes = {(event.operation, event.outcome) for event in events}
    expected = {
        ("put", "created"),
        ("put", "deduplicated"),
        ("put", "superseded"),
        ("delete", "deleted"),
        ("purge", "hard_deleted"),
    }
    _require(expected.issubset(outcomes), "audit log does not cover the full mutation lifecycle")
    _require(all(event.event_id and event.timestamp and event.scope for event in events), "audit fields incomplete")


def audit_covers_read_and_history_operations(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "audit-read-record", "marker", "own")
    _query(adapter, fact_key="marker", now=at(seconds=1))
    adapter.history(record.id, PRIMARY_SCOPE)
    events = adapter.audit_log(PRIMARY_SCOPE)
    operations = {event.operation for event in events}
    _require({"put", "query", "history"}.issubset(operations), "audit log omitted read/history operations")
    _require(
        any(record.id in event.subject_ids for event in events if event.operation in {"query", "history"}),
        "read/history audit events omitted returned subject identity",
    )


def audit_is_scope_isolated(adapter: MemoryAdapter) -> None:
    _put(adapter, "audit-scope-own", "marker", "own")
    _put(adapter, "audit-scope-other", "marker", "other", scope=OTHER_AGENT_SCOPE)
    own_events = adapter.audit_log(PRIMARY_SCOPE)
    _require({event.event_id for event in own_events} == {"audit-scope-own"}, "audit log crossed scope")


def audit_does_not_leak_secret_material(adapter: MemoryAdapter) -> None:
    secret = "sk-abcdefgh12345678"
    _put(adapter, "audit-secret", "note", "credential %s" % secret, metadata={"raw": secret})
    encoded = json.dumps([event.to_dict() for event in adapter.audit_log()], sort_keys=True)
    _require(secret not in encoded, "audit log leaked secret material")


def retention_classes_have_graded_horizons(adapter: MemoryAdapter) -> None:
    ephemeral = _put(adapter, "retention-e", "grade", "ephemeral", retention=RetentionClass.EPHEMERAL)
    working = _put(adapter, "retention-w", "grade", "working", retention=RetentionClass.WORKING)
    durable = _put(adapter, "retention-d", "grade", "durable", retention=RetentionClass.DURABLE)
    _require(ephemeral.expires_at == at(hours=1), "ephemeral default horizon must be one hour")
    _require(working.expires_at == at(days=30), "working default horizon must be thirty days")
    _require(durable.expires_at is None, "durable retention must have no implicit expiry")


def retention_grades_affect_visibility(adapter: MemoryAdapter) -> None:
    ephemeral = _put(adapter, "retention-visible-e", "grade", "ephemeral", retention=RetentionClass.EPHEMERAL)
    working = _put(adapter, "retention-visible-w", "grade", "working", retention=RetentionClass.WORKING)
    durable = _put(adapter, "retention-visible-d", "grade", "durable", retention=RetentionClass.DURABLE)
    two_hours = set(_ids(_query(adapter, fact_key="grade", now=at(hours=2))))
    thirty_one_days = set(_ids(_query(adapter, fact_key="grade", now=at(days=31))))
    _require(ephemeral.id not in two_hours, "ephemeral record exceeded default horizon")
    _require({working.id, durable.id}.issubset(two_hours), "longer retention disappeared too early")
    _require(thirty_one_days == {durable.id}, "only durable record should remain after thirty days")


def hard_ttl_uses_half_open_expiry_boundary(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "ttl-boundary", "temporary", "value", ttl_seconds=10)
    before = _query(adapter, fact_key="temporary", now=at(seconds=9))
    at_boundary = _query(adapter, fact_key="temporary", now=at(seconds=10))
    _require(record.id in _ids(before), "TTL record disappeared before expiry")
    _require(record.id not in _ids(at_boundary), "TTL record remained visible at expiry")


def purge_expired_hard_deletes_record(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "ttl-purge", "temporary", "value", ttl_seconds=10)
    purged = adapter.purge_expired(now=at(seconds=10))
    _require(record.id in purged, "purge did not report expired record")
    _require(not adapter.history(record.id, PRIMARY_SCOPE), "TTL purge did not hard-delete history")


def hard_ttl_cannot_be_bypassed_by_historical_query(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "ttl-asof", "temporary", "value", ttl_seconds=10)
    response = _query(
        adapter,
        fact_key="temporary",
        as_of=at(seconds=5),
        now=at(seconds=20),
    )
    _require(
        record.id not in _ids(response),
        "historical query resurrected a record after hard TTL expiry",
    )


def hard_ttl_cannot_be_bypassed_by_put_replay(adapter: MemoryAdapter) -> None:
    request = PutRequest(
        "ttl-replay",
        PRIMARY_SCOPE,
        "temporary",
        "sensitive value",
        retention=RetentionClass.DURABLE,
        ttl_seconds=5,
    )
    adapter.put(request, now=BASE_TIME)
    _expect_raises(
        KeyError,
        lambda: adapter.put(request, now=at(seconds=5)),
        "put replay recovered content after hard TTL expiry",
    )


def explicit_ttl_overrides_retention_default(adapter: MemoryAdapter) -> None:
    record = _put(
        adapter,
        "ttl-override",
        "temporary",
        "value",
        retention=RetentionClass.DURABLE,
        ttl_seconds=5,
    )
    _require(record.expires_at == at(seconds=5), "explicit TTL must override durable default")
    _require(not _query(adapter, fact_key="temporary", now=at(seconds=5)).hits, "TTL override ignored")


def idempotent_put_replay_returns_same_result(adapter: MemoryAdapter) -> None:
    request = PutRequest("replay-put", PRIMARY_SCOPE, "city", "Paris", retention=RetentionClass.DURABLE)
    first = adapter.put(request, now=BASE_TIME)
    second = adapter.put(request, now=at(seconds=1))
    _require(first == second, "identical put replay must return original result")
    _require(len(_query(adapter, fact_key="city", now=at(seconds=2)).hits) == 1, "put replay mutated state twice")


def reused_put_event_with_different_payload_is_rejected(adapter: MemoryAdapter) -> None:
    _put(adapter, "replay-collision", "city", "Paris")
    _expect_raises(
        ValueError,
        lambda: _put(adapter, "replay-collision", "city", "Lyon", now=at(seconds=1)),
        "event id collision with different payload must fail",
    )


def idempotent_delete_replay_is_stable(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "replay-delete-record", "erase", "me")
    request = DeleteRequest("replay-delete", PRIMARY_SCOPE, record.id, DeleteMode.HARD)
    first = adapter.delete(request, now=at(seconds=1))
    second = adapter.delete(request, now=at(seconds=2))
    _require(first.deleted_ids == second.deleted_ids, "delete replay changed affected identities")
    _require(second.replayed, "delete replay was not identified")


def reused_delete_event_with_different_payload_is_rejected(adapter: MemoryAdapter) -> None:
    first = _put(adapter, "delete-collision-r1", "erase", "one")
    second = _put(adapter, "delete-collision-r2", "erase", "two")
    adapter.delete(DeleteRequest("delete-collision", PRIMARY_SCOPE, first.id, DeleteMode.HARD))
    _expect_raises(
        ValueError,
        lambda: adapter.delete(DeleteRequest("delete-collision", PRIMARY_SCOPE, second.id, DeleteMode.HARD)),
        "delete event id collision with different payload must fail",
    )


def event_id_cannot_be_reused_across_operations(adapter: MemoryAdapter) -> None:
    record = _put(adapter, "cross-operation-event", "erase", "one")
    _expect_raises(
        ValueError,
        lambda: adapter.delete(
            DeleteRequest(
                "cross-operation-event",
                PRIMARY_SCOPE,
                record.id,
                DeleteMode.HARD,
            )
        ),
        "one event id must not identify both a put and a delete",
    )


CHECKS: Tuple[ConformanceCheck, ...] = (
    ConformanceCheck("dedup.stable_identity", "Repeated fact returns stable identity", Capability.DEDUPLICATION, "repeated-fact", dedup_returns_stable_identity),
    ConformanceCheck("dedup.one_active", "Repeated fact has one active result", Capability.DEDUPLICATION, "repeated-fact", dedup_keeps_one_active_result),
    ConformanceCheck("dedup.scope_boundary", "Dedup does not cross scope", Capability.DEDUPLICATION, "repeated-fact", dedup_does_not_cross_scope),
    ConformanceCheck("supersession.bidirectional", "Correction links both directions", Capability.SUPERSESSION, "explicit-correction", supersession_links_both_directions),
    ConformanceCheck("supersession.version", "Correction increments version", Capability.SUPERSESSION, "explicit-correction", supersession_increments_version),
    ConformanceCheck("supersession.current", "Superseded fact is not current", Capability.SUPERSESSION, "explicit-correction", superseded_fact_excluded_from_current_query),
    ConformanceCheck("supersession.scope_boundary", "Correction cannot cross scope", Capability.SUPERSESSION, "explicit-correction", supersession_rejects_cross_scope_target),
    ConformanceCheck("conflict.coexist", "Unlinked conflicts coexist", Capability.SCOPED_CONFLICTS, "scoped-conflict", conflicting_values_coexist_without_explicit_correction),
    ConformanceCheck("conflict.partition", "Conflicts partition by scope", Capability.SCOPED_CONFLICTS, "scoped-conflict", conflicts_are_partitioned_by_scope),
    ConformanceCheck("isolation.user", "User isolation", Capability.ISOLATION, "four-axis-isolation", user_isolation),
    ConformanceCheck("isolation.agent", "Agent isolation", Capability.ISOLATION, "four-axis-isolation", agent_isolation),
    ConformanceCheck("isolation.project", "Project isolation", Capability.ISOLATION, "four-axis-isolation", project_isolation),
    ConformanceCheck("isolation.session", "Session isolation", Capability.ISOLATION, "four-axis-isolation", session_isolation),
    ConformanceCheck("isolation.history", "History isolation", Capability.ISOLATION, "four-axis-isolation", history_is_scope_isolated),
    ConformanceCheck("history.complete", "Complete ordered version history", Capability.VERSION_HISTORY, "version-chain", history_orders_complete_version_chain),
    ConformanceCheck("history.status", "History preserves status transitions", Capability.VERSION_HISTORY, "version-chain", history_preserves_status_transitions),
    ConformanceCheck("delete.lineage", "Lineage deletion removes every version", Capability.LINKED_LINEAGE_DELETE, "linked-lineages", lineage_delete_removes_every_version),
    ConformanceCheck("delete.linked_lineage", "Linked-lineage deletion traverses links", Capability.LINKED_LINEAGE_DELETE, "linked-lineages", linked_lineage_delete_traverses_links),
    ConformanceCheck("delete.lineage_only", "Lineage-only deletion does not traverse links", Capability.LINKED_LINEAGE_DELETE, "linked-lineages", lineage_delete_does_not_follow_links),
    ConformanceCheck("delete.link_scope", "Links cannot cross scope", Capability.LINKED_LINEAGE_DELETE, "linked-lineages", links_cannot_cross_scope),
    ConformanceCheck("delete.hard", "Hard deletion removes query and history", Capability.HARD_DELETE, "hard-erasure", hard_delete_removes_query_and_history),
    ConformanceCheck("delete.hard_replay", "Hard deletion prevents replay recovery", Capability.HARD_DELETE, "hard-erasure", hard_delete_prevents_replay_recovery),
    ConformanceCheck("delete.soft", "Soft deletion retains tombstone", Capability.HARD_DELETE, "hard-erasure", soft_delete_retains_tombstoned_history),
    ConformanceCheck("delete.scope_boundary", "Deletion cannot cross scope", Capability.HARD_DELETE, "hard-erasure", delete_rejects_cross_scope_target),
    ConformanceCheck("time.before_correction", "Historical read before correction", Capability.TIME_AWARE_QUERY, "historical-read", historical_query_selects_pre_correction_version),
    ConformanceCheck("time.after_correction", "Historical read after correction", Capability.TIME_AWARE_QUERY, "historical-read", historical_query_selects_post_correction_version),
    ConformanceCheck("time.boundary", "Correction boundary is half-open", Capability.TIME_AWARE_QUERY, "historical-read", correction_boundary_is_half_open),
    ConformanceCheck("time.future", "Future observation is not visible early", Capability.TIME_AWARE_QUERY, "historical-read", future_observation_is_not_yet_visible),
    ConformanceCheck("retrieval.stale_graph", "Stale graph nodes are excluded", Capability.MULTI_STREAM_SEARCH, "stale-graph", stale_graph_nodes_are_excluded),
    ConformanceCheck("retrieval.lexical_degrade", "Lexical stream failure degrades", Capability.MULTI_STREAM_SEARCH, "stream-outage", lexical_stream_failure_degrades),
    ConformanceCheck("retrieval.vector_degrade", "Vector stream failure degrades", Capability.MULTI_STREAM_SEARCH, "stream-outage", vector_stream_failure_degrades),
    ConformanceCheck("retrieval.graph_degrade", "Graph stream failure degrades", Capability.MULTI_STREAM_SEARCH, "stream-outage", graph_stream_failure_degrades),
    ConformanceCheck("retrieval.all_degrade", "All stream failures are explicit", Capability.MULTI_STREAM_SEARCH, "stream-outage", all_streams_failure_is_explicit),
    ConformanceCheck("fusion.provenance", "Rank fusion records contributors", Capability.RANK_FUSION, "fusion-outage", rank_fusion_records_contributing_streams),
    ConformanceCheck("fusion.fallback", "Rank fusion failure falls back", Capability.RANK_FUSION, "fusion-outage", rank_fusion_failure_falls_back),
    ConformanceCheck("reranker.fallback", "Reranker failure preserves candidates", Capability.RERANKER_FALLBACK, "reranker-outage", reranker_failure_preserves_candidates),
    ConformanceCheck("reranker.healthy", "Healthy reranker avoids fallback", Capability.RERANKER_FALLBACK, "reranker-outage", healthy_reranker_does_not_mark_fallback),
    ConformanceCheck("secret.value", "Secret scrubbing covers values", Capability.SECRET_SCRUBBING, "credential-shaped-text", secret_scrubbing_redacts_record_value),
    ConformanceCheck("secret.metadata", "Secret scrubbing covers nested metadata", Capability.SECRET_SCRUBBING, "credential-shaped-text", secret_scrubbing_redacts_nested_metadata),
    ConformanceCheck("audit.lifecycle", "Audit covers mutation lifecycle", Capability.AUDIT, "audit-lifecycle", audit_covers_lifecycle_mutations),
    ConformanceCheck("audit.reads", "Audit covers reads and history", Capability.AUDIT, "audit-lifecycle", audit_covers_read_and_history_operations),
    ConformanceCheck("audit.scope", "Audit is scope isolated", Capability.AUDIT, "audit-lifecycle", audit_is_scope_isolated),
    ConformanceCheck("audit.secret", "Audit does not leak secrets", Capability.AUDIT, "audit-lifecycle", audit_does_not_leak_secret_material),
    ConformanceCheck("retention.horizons", "Retention classes have graded horizons", Capability.GRADED_RETENTION, "retention-grades", retention_classes_have_graded_horizons),
    ConformanceCheck("retention.visibility", "Retention grades affect visibility", Capability.GRADED_RETENTION, "retention-grades", retention_grades_affect_visibility),
    ConformanceCheck("ttl.boundary", "Hard TTL uses half-open boundary", Capability.HARD_TTL, "ttl-boundary", hard_ttl_uses_half_open_expiry_boundary),
    ConformanceCheck("ttl.purge", "TTL purge hard-deletes", Capability.HARD_TTL, "ttl-boundary", purge_expired_hard_deletes_record),
    ConformanceCheck("ttl.no_resurrection", "Historical reads cannot bypass hard TTL", Capability.HARD_TTL, "ttl-boundary", hard_ttl_cannot_be_bypassed_by_historical_query),
    ConformanceCheck("ttl.no_replay", "Put replay cannot bypass hard TTL", Capability.HARD_TTL, "ttl-boundary", hard_ttl_cannot_be_bypassed_by_put_replay),
    ConformanceCheck("ttl.override", "Explicit TTL overrides retention", Capability.HARD_TTL, "ttl-boundary", explicit_ttl_overrides_retention_default),
    ConformanceCheck("replay.put", "Put replay is idempotent", Capability.IDEMPOTENT_REPLAY, "event-replay", idempotent_put_replay_returns_same_result),
    ConformanceCheck("replay.put_collision", "Put event collision is rejected", Capability.IDEMPOTENT_REPLAY, "event-replay", reused_put_event_with_different_payload_is_rejected),
    ConformanceCheck("replay.delete", "Delete replay is idempotent", Capability.IDEMPOTENT_REPLAY, "event-replay", idempotent_delete_replay_is_stable),
    ConformanceCheck("replay.delete_collision", "Delete event collision is rejected", Capability.IDEMPOTENT_REPLAY, "event-replay", reused_delete_event_with_different_payload_is_rejected),
    ConformanceCheck("replay.cross_operation", "Event IDs cannot cross mutation operations", Capability.IDEMPOTENT_REPLAY, "event-replay", event_id_cannot_be_reused_across_operations),
)

CHECK_BY_ID: Mapping[str, ConformanceCheck] = {check.id: check for check in CHECKS}
