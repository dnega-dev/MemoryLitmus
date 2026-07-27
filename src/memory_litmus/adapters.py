"""Bundled reference and intentionally broken adapters.

The reference adapter is executable specification material, not a production
memory database. It favors deterministic, inspectable behavior over scale.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .models import (
    AdapterMetadata,
    AuditEvent,
    Capability,
    DeleteCascade,
    DeleteMode,
    DeleteRequest,
    DeleteResult,
    MemoryRecord,
    PutRequest,
    QueryRequest,
    QueryResponse,
    RecordStatus,
    RetentionClass,
    Scope,
    SearchHit,
    ensure_aware,
    isoformat,
    utc_now,
)


_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*[^\s,;]+"),
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_RETENTION_TTLS = {
    RetentionClass.EPHEMERAL: timedelta(hours=1),
    RetentionClass.WORKING: timedelta(days=30),
    RetentionClass.DURABLE: None,
}


def scrub_text(value: str) -> str:
    """Redact common credential shapes without external detectors."""
    result = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups:
            result = pattern.sub(lambda match: "%s=[REDACTED]" % match.group(1), result)
        else:
            result = pattern.sub("[REDACTED]", result)
    return result


def scrub_value(value: Any) -> Any:
    """Recursively scrub strings in JSON-like metadata."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, Mapping):
        return {str(key): scrub_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(scrub_value(item) for item in value)
    if isinstance(value, list):
        return [scrub_value(item) for item in value]
    if isinstance(value, set):
        return sorted(scrub_value(item) for item in value)
    return copy.deepcopy(value)


class InMemoryAdapter:
    """Deterministic reference implementation of all declared capabilities."""

    adapter_name = "reference"
    description = "Bundled deterministic in-memory executable reference semantics."

    def __init__(self) -> None:
        self.reset()

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            name=self.adapter_name,
            version="1.0",
            capabilities=frozenset(Capability),
            description=self.description,
        )

    def reset(self) -> None:
        self._records: Dict[str, MemoryRecord] = {}
        self._event_fingerprints: Dict[str, Tuple[str, str]] = {}
        self._put_events: Dict[str, Tuple[str, Optional[MemoryRecord]]] = {}
        self._delete_events: Dict[str, Tuple[str, DeleteResult]] = {}
        self._audit: List[AuditEvent] = []
        self._next_id = 1
        self._next_audit_id = 1

    def put(self, request: PutRequest, now: Optional[datetime] = None) -> MemoryRecord:
        clock = self._clock(now)
        fingerprint = self._fingerprint_put(request)
        self._validate_event_id(request.event_id, "put", fingerprint)
        replay = self._put_events.get(request.event_id)
        if replay is not None:
            if replay[0] != fingerprint:
                raise ValueError("event_id %r was reused with a different put payload" % request.event_id)
            record = replay[1]
            if record is None:
                raise KeyError("the replay result was removed by hard deletion")
            if record.expires_at is not None and clock >= record.expires_at:
                self._put_events[request.event_id] = (fingerprint, None)
                raise KeyError("the replay result is unavailable after hard TTL expiry")
            self._append_audit(
                request.event_id,
                "put",
                clock,
                (record.id,),
                request.scope,
                "replayed",
                {"fact_key": request.fact_key},
            )
            return record

        value = self._scrub_text(request.value)
        metadata = self._scrub_value(request.metadata)
        observed_at = request.observed_at or clock
        ensure_aware(observed_at, "observed_at")
        self._validate_links(request.links, request.scope)

        if request.supersedes_id is not None:
            previous = self._records.get(request.supersedes_id)
            if previous is None:
                raise KeyError("superseded record %r does not exist" % request.supersedes_id)
            if not self._scope_matches(previous.scope, request.scope):
                raise PermissionError("cannot supersede a record outside the exact scope")
            if previous.status is not RecordStatus.ACTIVE:
                raise ValueError("only an active record can be superseded")
            if previous.fact_key != request.fact_key:
                raise ValueError("a correction must preserve fact_key")
            record_id = self._new_id()
            record = MemoryRecord(
                id=record_id,
                lineage_id=previous.lineage_id,
                version=previous.version + 1,
                scope=request.scope,
                fact_key=request.fact_key,
                value=value,
                status=RecordStatus.ACTIVE,
                created_at=clock,
                valid_from=observed_at,
                valid_to=None,
                expires_at=self._expiry(observed_at, request.retention, request.ttl_seconds),
                retention=request.retention,
                supersedes_id=previous.id,
                superseded_by_id=None,
                links=tuple(request.links),
                metadata=metadata,
                source_event_id=request.event_id,
            )
            self._records[previous.id] = replace(
                previous,
                status=RecordStatus.SUPERSEDED,
                valid_to=observed_at,
                superseded_by_id=record.id,
            )
            self._records[record.id] = record
            outcome = "superseded"
        else:
            duplicate = self._find_duplicate(request.scope, request.fact_key, value, clock)
            if duplicate is not None:
                self._bind_event_id(request.event_id, "put", fingerprint)
                self._put_events[request.event_id] = (fingerprint, duplicate)
                self._append_audit(
                    request.event_id,
                    "put",
                    clock,
                    (duplicate.id,),
                    request.scope,
                    "deduplicated",
                    {"fact_key": request.fact_key},
                )
                return duplicate
            record_id = self._new_id()
            record = MemoryRecord(
                id=record_id,
                lineage_id=record_id,
                version=1,
                scope=request.scope,
                fact_key=request.fact_key,
                value=value,
                status=RecordStatus.ACTIVE,
                created_at=clock,
                valid_from=observed_at,
                valid_to=None,
                expires_at=self._expiry(observed_at, request.retention, request.ttl_seconds),
                retention=request.retention,
                supersedes_id=None,
                superseded_by_id=None,
                links=tuple(request.links),
                metadata=metadata,
                source_event_id=request.event_id,
            )
            self._records[record.id] = record
            outcome = "created"

        self._bind_event_id(request.event_id, "put", fingerprint)
        self._put_events[request.event_id] = (fingerprint, record)
        self._append_audit(
            request.event_id,
            "put",
            clock,
            (record.id,),
            request.scope,
            outcome,
            {
                "fact_key": request.fact_key,
                "lineage_id": record.lineage_id,
                "version": record.version,
                "retention": request.retention.value,
                "ttl_seconds": request.ttl_seconds,
            },
        )
        return record

    def query(self, request: QueryRequest, now: Optional[datetime] = None) -> QueryResponse:
        clock = self._clock(now)
        instant = request.as_of or clock
        eligible = [
            record
            for record in self._records.values()
            if self._scope_matches(record.scope, request.scope)
            and (request.fact_key is None or record.fact_key == request.fact_key)
            and self._eligible(
                record,
                instant,
                historical=request.as_of is not None,
                query_clock=clock,
            )
        ]
        eligible.sort(key=lambda record: (record.valid_from, record.id), reverse=True)

        failed = tuple(sorted(set(request.streams).intersection(request.fail_streams)))
        available = [name for name in request.streams if name not in request.fail_streams]
        stream_rankings: Dict[str, List[Tuple[str, float]]] = {}
        for stream in available:
            stream_rankings[stream] = self._rank_stream(stream, eligible, request.text, instant)

        if request.fail_fusion and stream_rankings:
            fused = self._simple_fallback(stream_rankings)
            fusion_fallback = True
        else:
            fused = self._reciprocal_rank_fusion(stream_rankings)
            fusion_fallback = False

        reranker_fallback = False
        if request.use_reranker:
            if request.fail_reranker:
                reranker_fallback = True
            else:
                fused = self._rerank(fused, request.text)

        by_id = {record.id: record for record in eligible}
        hits: List[SearchHit] = []
        for memory_id, score, streams in fused[: request.limit]:
            record = by_id.get(memory_id)
            if record is not None:
                hits.append(SearchHit(record=record, score=score, streams=tuple(sorted(streams))))
        response = QueryResponse(
            hits=tuple(hits),
            degraded_streams=failed,
            fusion_fallback=fusion_fallback,
            reranker_fallback=reranker_fallback,
        )
        self._append_audit(
            "query-%06d" % self._next_audit_id,
            "query",
            clock,
            tuple(hit.record.id for hit in response.hits),
            request.scope,
            "returned",
            {
                "count": len(response.hits),
                "fact_key": request.fact_key,
                "historical": request.as_of is not None,
                "streams": list(request.streams),
                "degraded_streams": list(response.degraded_streams),
                "fusion_fallback": response.fusion_fallback,
                "reranker_fallback": response.reranker_fallback,
            },
        )
        return response

    def history(self, memory_id: str, scope: Scope) -> Sequence[MemoryRecord]:
        anchor = self._records.get(memory_id)
        if anchor is None or not self._scope_matches(anchor.scope, scope):
            self._append_audit(
                "history-%06d" % self._next_audit_id,
                "history",
                utc_now(),
                (),
                scope,
                "not_found",
                {},
            )
            return ()
        rows = [
            record
            for record in self._records.values()
            if record.lineage_id == anchor.lineage_id and self._scope_matches(record.scope, scope)
        ]
        result = tuple(sorted(rows, key=lambda record: (record.version, record.created_at, record.id)))
        self._append_audit(
            "history-%06d" % self._next_audit_id,
            "history",
            utc_now(),
            tuple(record.id for record in result),
            scope,
            "returned",
            {"count": len(result)},
        )
        return result

    def delete(self, request: DeleteRequest, now: Optional[datetime] = None) -> DeleteResult:
        clock = self._clock(request.deleted_at or now)
        fingerprint = self._fingerprint_delete(request)
        self._validate_event_id(request.event_id, "delete", fingerprint)
        replay = self._delete_events.get(request.event_id)
        if replay is not None:
            if replay[0] != fingerprint:
                raise ValueError("event_id %r was reused with a different delete payload" % request.event_id)
            prior = replay[1]
            result = DeleteResult(deleted_ids=prior.deleted_ids, mode=prior.mode, replayed=True)
            self._append_audit(
                request.event_id,
                "delete",
                clock,
                prior.deleted_ids,
                request.scope,
                "replayed",
                {"mode": request.mode.value, "cascade": request.cascade.value},
            )
            return result

        anchor = self._records.get(request.memory_id)
        if anchor is None:
            result = DeleteResult(deleted_ids=(), mode=request.mode)
            self._bind_event_id(request.event_id, "delete", fingerprint)
            self._delete_events[request.event_id] = (fingerprint, result)
            self._append_audit(
                request.event_id,
                "delete",
                clock,
                (),
                request.scope,
                "not_found",
                {"mode": request.mode.value, "cascade": request.cascade.value},
            )
            return result
        if not self._scope_matches(anchor.scope, request.scope):
            raise PermissionError("cannot delete a record outside the exact scope")

        targets = self._delete_targets(anchor, request.scope, request.cascade)
        target_ids = tuple(sorted(record.id for record in targets))
        if request.mode is DeleteMode.HARD:
            self._erase_put_replay_results(set(target_ids))
            for memory_id in target_ids:
                self._records.pop(memory_id, None)
        else:
            for record in targets:
                self._records[record.id] = replace(
                    record,
                    status=RecordStatus.DELETED,
                    deleted_at=clock,
                    valid_to=record.valid_to or clock,
                )
        result = DeleteResult(deleted_ids=target_ids, mode=request.mode)
        self._bind_event_id(request.event_id, "delete", fingerprint)
        self._delete_events[request.event_id] = (fingerprint, result)
        self._append_audit(
            request.event_id,
            "delete",
            clock,
            target_ids,
            request.scope,
            "deleted",
            {"mode": request.mode.value, "cascade": request.cascade.value},
        )
        return result

    def audit_log(self, scope: Optional[Scope] = None) -> Sequence[AuditEvent]:
        if scope is None:
            return tuple(self._audit)
        return tuple(event for event in self._audit if self._scope_matches(event.scope, scope))

    def purge_expired(self, now: Optional[datetime] = None) -> Sequence[str]:
        clock = self._clock(now)
        expired = [
            record
            for record in self._records.values()
            if record.expires_at is not None and clock >= record.expires_at
        ]
        expired.sort(key=lambda record: record.id)
        self._erase_put_replay_results({record.id for record in expired})
        for record in expired:
            self._records.pop(record.id, None)
            self._append_audit(
                "purge-%06d" % self._next_audit_id,
                "purge",
                clock,
                (record.id,),
                record.scope,
                "hard_deleted",
                {"reason": "ttl", "retention": record.retention.value},
            )
        return tuple(record.id for record in expired)

    # -- extension hooks used by the intentionally broken demonstrators --

    def _scope_matches(self, left: Scope, right: Scope) -> bool:
        return left == right

    def _scrub_text(self, value: str) -> str:
        return scrub_text(value)

    def _scrub_value(self, value: Any) -> Any:
        return scrub_value(value)

    def _find_duplicate(
        self, scope: Scope, fact_key: str, value: str, instant: datetime
    ) -> Optional[MemoryRecord]:
        candidates = [
            record
            for record in self._records.values()
            if self._scope_matches(record.scope, scope)
            and record.fact_key == fact_key
            and record.value == value
            and self._eligible(record, instant, historical=False)
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda record: (record.created_at, record.id))[0]

    def _eligible(
        self,
        record: MemoryRecord,
        instant: datetime,
        historical: bool,
        query_clock: Optional[datetime] = None,
    ) -> bool:
        if instant < record.valid_from:
            return False
        clock = query_clock or instant
        if record.expires_at is not None and (
            instant >= record.expires_at or clock >= record.expires_at
        ):
            return False
        if record.deleted_at is not None and instant >= record.deleted_at:
            return False
        if historical:
            return record.valid_to is None or instant < record.valid_to
        return record.status is RecordStatus.ACTIVE

    # -- internal helpers --

    def _clock(self, value: Optional[datetime]) -> datetime:
        clock = value or utc_now()
        ensure_aware(clock, "now")
        return clock.astimezone(timezone.utc)

    def _new_id(self) -> str:
        memory_id = "mem-%06d" % self._next_id
        self._next_id += 1
        return memory_id

    def _expiry(
        self, valid_from: datetime, retention: RetentionClass, ttl_seconds: Optional[int]
    ) -> Optional[datetime]:
        if ttl_seconds is not None:
            return valid_from + timedelta(seconds=ttl_seconds)
        duration = _RETENTION_TTLS[retention]
        return None if duration is None else valid_from + duration

    def _validate_links(self, links: Sequence[str], scope: Scope) -> None:
        for memory_id in links:
            linked = self._records.get(memory_id)
            if linked is None:
                raise KeyError("linked record %r does not exist" % memory_id)
            if not self._scope_matches(linked.scope, scope):
                raise PermissionError("links cannot cross an exact scope boundary")

    def _delete_targets(
        self, anchor: MemoryRecord, scope: Scope, cascade: DeleteCascade
    ) -> List[MemoryRecord]:
        in_scope = [
            record for record in self._records.values() if self._scope_matches(record.scope, scope)
        ]
        if cascade is DeleteCascade.SELF:
            return [anchor]
        lineages: Set[str] = {anchor.lineage_id}
        if cascade is DeleteCascade.LINKED_LINEAGE:
            changed = True
            while changed:
                changed = False
                selected_ids = {record.id for record in in_scope if record.lineage_id in lineages}
                for record in in_scope:
                    if record.lineage_id in lineages or selected_ids.intersection(record.links):
                        linked_lineages = {
                            candidate.lineage_id
                            for candidate in in_scope
                            if candidate.id in record.links or record.id in candidate.links
                        }
                        linked_lineages.add(record.lineage_id)
                        if not linked_lineages.issubset(lineages):
                            lineages.update(linked_lineages)
                            changed = True
        return [record for record in in_scope if record.lineage_id in lineages]

    def _rank_stream(
        self, stream: str, records: Sequence[MemoryRecord], text: str, instant: datetime
    ) -> List[Tuple[str, float]]:
        query_tokens = set(_tokens(text))
        if not text.strip():
            return [(record.id, 1.0) for record in records]
        direct_scores: Dict[str, float] = {}
        for record in records:
            haystack = "%s %s" % (record.fact_key, record.value)
            tokens = set(_tokens(haystack))
            if stream == "lexical":
                score = _lexical_score(text, haystack, query_tokens, tokens)
            elif stream == "vector":
                score = _jaccard(query_tokens, tokens)
            elif stream == "graph":
                score = _lexical_score(text, haystack, query_tokens, tokens)
            else:  # guarded by QueryRequest validation
                score = 0.0
            if score > 0:
                direct_scores[record.id] = score

        if stream == "graph" and direct_scores:
            active_ids = {record.id for record in records}
            by_id = {record.id: record for record in records}
            propagated = dict(direct_scores)
            for source_id, source_score in direct_scores.items():
                source = by_id[source_id]
                for linked_id in source.links:
                    if linked_id in active_ids:
                        propagated[linked_id] = max(propagated.get(linked_id, 0.0), source_score * 0.5)
                for candidate in records:
                    if source_id in candidate.links:
                        propagated[candidate.id] = max(
                            propagated.get(candidate.id, 0.0), source_score * 0.5
                        )
            direct_scores = propagated
        return sorted(direct_scores.items(), key=lambda item: (-item[1], item[0]))

    def _reciprocal_rank_fusion(
        self, rankings: Mapping[str, Sequence[Tuple[str, float]]]
    ) -> List[Tuple[str, float, Set[str]]]:
        totals: Dict[str, float] = {}
        sources: Dict[str, Set[str]] = {}
        for stream, ranking in rankings.items():
            for rank, (memory_id, _score) in enumerate(ranking, 1):
                totals[memory_id] = totals.get(memory_id, 0.0) + 1.0 / (60.0 + rank)
                sources.setdefault(memory_id, set()).add(stream)
        return [
            (memory_id, score, sources[memory_id])
            for memory_id, score in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _simple_fallback(
        self, rankings: Mapping[str, Sequence[Tuple[str, float]]]
    ) -> List[Tuple[str, float, Set[str]]]:
        scores: Dict[str, float] = {}
        sources: Dict[str, Set[str]] = {}
        for stream, ranking in rankings.items():
            for memory_id, score in ranking:
                scores[memory_id] = max(scores.get(memory_id, 0.0), score)
                sources.setdefault(memory_id, set()).add(stream)
        return [
            (memory_id, score, sources[memory_id])
            for memory_id, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _rerank(
        self, fused: Sequence[Tuple[str, float, Set[str]]], text: str
    ) -> List[Tuple[str, float, Set[str]]]:
        needle = text.strip().lower()
        rescored = []
        for memory_id, score, streams in fused:
            record = self._records[memory_id]
            exact_boost = 1.0 if needle and needle in record.value.lower() else 0.0
            rescored.append((memory_id, score + exact_boost, streams))
        return sorted(rescored, key=lambda item: (-item[1], item[0]))

    def _append_audit(
        self,
        event_id: str,
        operation: str,
        timestamp: datetime,
        subject_ids: Tuple[str, ...],
        scope: Scope,
        outcome: str,
        details: Mapping[str, Any],
    ) -> None:
        event = AuditEvent(
            event_id=event_id,
            operation=operation,
            timestamp=timestamp,
            subject_ids=tuple(subject_ids),
            scope=scope,
            outcome=outcome,
            details=self._scrub_value(details),
        )
        self._audit.append(event)
        self._next_audit_id += 1

    def _validate_event_id(self, event_id: str, operation: str, fingerprint: str) -> None:
        existing = self._event_fingerprints.get(event_id)
        if existing is not None and existing != (operation, fingerprint):
            raise ValueError(
                "event_id %r was reused for a different mutation payload" % event_id
            )

    def _bind_event_id(self, event_id: str, operation: str, fingerprint: str) -> None:
        self._event_fingerprints[event_id] = (operation, fingerprint)

    def _erase_put_replay_results(self, memory_ids: Set[str]) -> None:
        for event_id, (fingerprint, record) in tuple(self._put_events.items()):
            if record is not None and record.id in memory_ids:
                self._put_events[event_id] = (fingerprint, None)

    def _fingerprint_put(self, request: PutRequest) -> str:
        payload = {
            "scope": request.scope.to_dict(),
            "fact_key": request.fact_key,
            "value": request.value,
            "observed_at": isoformat(request.observed_at),
            "supersedes_id": request.supersedes_id,
            "links": list(request.links),
            "retention": request.retention.value,
            "ttl_seconds": request.ttl_seconds,
            "metadata": request.metadata,
        }
        return _fingerprint(payload)

    def _fingerprint_delete(self, request: DeleteRequest) -> str:
        return _fingerprint(
            {
                "scope": request.scope.to_dict(),
                "memory_id": request.memory_id,
                "mode": request.mode.value,
                "cascade": request.cascade.value,
                "deleted_at": isoformat(request.deleted_at),
            }
        )


class BrokenDedupAdapter(InMemoryAdapter):
    adapter_name = "broken-dedup"
    description = "Intentionally creates duplicate records for repeated facts."

    def _find_duplicate(
        self, scope: Scope, fact_key: str, value: str, instant: datetime
    ) -> Optional[MemoryRecord]:
        return None


class BrokenIsolationAdapter(InMemoryAdapter):
    adapter_name = "broken-isolation"
    description = "Intentionally treats every tenant/session scope as equivalent."

    def _scope_matches(self, left: Scope, right: Scope) -> bool:
        return True


class BrokenSecretAdapter(InMemoryAdapter):
    adapter_name = "broken-secret-scrubbing"
    description = "Intentionally persists raw credentials."

    def _scrub_text(self, value: str) -> str:
        return value

    def _scrub_value(self, value: Any) -> Any:
        return copy.deepcopy(value)


class BrokenHardDeleteAdapter(InMemoryAdapter):
    adapter_name = "broken-hard-delete"
    description = "Intentionally turns hard deletion into a recoverable soft tombstone."

    def delete(self, request: DeleteRequest, now: Optional[datetime] = None) -> DeleteResult:
        if request.mode is DeleteMode.HARD:
            request = DeleteRequest(
                event_id=request.event_id,
                scope=request.scope,
                memory_id=request.memory_id,
                mode=DeleteMode.SOFT,
                cascade=request.cascade,
                deleted_at=request.deleted_at,
            )
        return super().delete(request, now=now)


class BrokenStaleGraphAdapter(InMemoryAdapter):
    adapter_name = "broken-stale-graph"
    description = "Intentionally lets superseded graph nodes participate in current retrieval."

    def _eligible(
        self,
        record: MemoryRecord,
        instant: datetime,
        historical: bool,
        query_clock: Optional[datetime] = None,
    ) -> bool:
        if historical:
            return super()._eligible(record, instant, historical, query_clock=query_clock)
        clock = query_clock or instant
        if record.expires_at is not None and clock >= record.expires_at:
            return False
        return record.deleted_at is None


BUILTIN_ADAPTERS = {
    "reference": InMemoryAdapter,
    "broken-dedup": BrokenDedupAdapter,
    "broken-isolation": BrokenIsolationAdapter,
    "broken-secret-scrubbing": BrokenSecretAdapter,
    "broken-hard-delete": BrokenHardDeleteAdapter,
    "broken-stale-graph": BrokenStaleGraphAdapter,
}


def _tokens(value: str) -> Tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(value.lower()))


def _lexical_score(
    query: str, haystack: str, query_tokens: Set[str], value_tokens: Set[str]
) -> float:
    if query.lower() in haystack.lower():
        return 1.0
    if not query_tokens:
        return 0.0
    return len(query_tokens.intersection(value_tokens)) / float(len(query_tokens))


def _jaccard(left: Set[str], right: Set[str]) -> float:
    union = left.union(right)
    return len(left.intersection(right)) / float(len(union)) if union else 0.0


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
