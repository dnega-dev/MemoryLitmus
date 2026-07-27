"""Capability-aware conformance runner and adapter discovery."""
from __future__ import annotations

import importlib
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Sequence, Tuple

from .adapters import BUILTIN_ADAPTERS
from .checks import CHECKS, ConformanceCheck
from .models import AdapterMetadata, Capability, CapabilityLevel
from .profiles import CapabilityProfile, get_profile
from .protocol import AdapterFactory


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    title: str
    capability: Capability
    level: CapabilityLevel
    status: CheckStatus
    duration_seconds: float
    message: str = ""
    fixture: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.check_id,
            "title": self.title,
            "capability": self.capability.value,
            "level": self.level.value,
            "status": self.status.value,
            "duration_seconds": round(self.duration_seconds, 6),
            "message": self.message,
            "fixture": self.fixture,
        }


@dataclass(frozen=True)
class RunResult:
    adapter: AdapterMetadata
    profile: CapabilityProfile
    results: Tuple[CheckResult, ...]
    duration_seconds: float

    @property
    def passed(self) -> bool:
        return not any(result.status is CheckStatus.FAIL for result in self.results)

    def counts(self) -> Dict[str, int]:
        return {
            status.value: sum(result.status is status for result in self.results)
            for status in CheckStatus
        }

    def to_dict(self) -> Dict[str, object]:
        return {
            "schema_version": "1.0",
            "tool": "memory-litmus",
            "adapter": self.adapter.to_dict(),
            "profile": self.profile.to_dict(),
            "passed": self.passed,
            "counts": self.counts(),
            "duration_seconds": round(self.duration_seconds, 6),
            "results": [result.to_dict() for result in self.results],
        }


def resolve_adapter_factory(spec: str) -> AdapterFactory:
    """Resolve a bundled name or ``module:attribute`` factory/class."""
    if spec in BUILTIN_ADAPTERS:
        return BUILTIN_ADAPTERS[spec]
    if ":" not in spec:
        raise ValueError(
            "unknown adapter %r; use a built-in name or module:factory" % spec
        )
    module_name, attribute_name = spec.split(":", 1)
    if not module_name or not attribute_name:
        raise ValueError("external adapter must use module:factory syntax")
    module = importlib.import_module(module_name)
    target = getattr(module, attribute_name)
    if not callable(target):
        raise TypeError("adapter target %r is not callable" % spec)
    return target


def validate_adapter(adapter: Any) -> AdapterMetadata:
    missing = [
        name
        for name in ("metadata", "reset", "put", "query", "history", "delete", "audit_log", "purge_expired")
        if not callable(getattr(adapter, name, None))
    ]
    if missing:
        raise TypeError("adapter is missing protocol methods: %s" % ", ".join(missing))
    metadata = adapter.metadata()
    if not isinstance(metadata, AdapterMetadata):
        raise TypeError("metadata() must return AdapterMetadata")
    if not metadata.name.strip() or not metadata.version.strip():
        raise ValueError("adapter metadata name and version must be non-empty")
    invalid = [capability for capability in metadata.capabilities if not isinstance(capability, Capability)]
    if invalid:
        raise TypeError("metadata capabilities must contain Capability values")
    return metadata


def run_conformance(
    factory: AdapterFactory,
    profile: CapabilityProfile,
    checks: Sequence[ConformanceCheck] = CHECKS,
) -> RunResult:
    started = time.perf_counter()
    probe = factory()
    metadata = validate_adapter(probe)
    results = []
    for check in checks:
        level = profile.level(check.capability)
        declared = check.capability in metadata.capabilities
        if level is CapabilityLevel.UNSUPPORTED:
            results.append(
                CheckResult(
                    check.id,
                    check.title,
                    check.capability,
                    level,
                    CheckStatus.SKIP,
                    0.0,
                    "capability is outside profile",
                    check.fixture,
                )
            )
            continue
        if not declared:
            if level is CapabilityLevel.REQUIRED:
                status = CheckStatus.FAIL
                message = "required capability is not declared by adapter"
            else:
                status = CheckStatus.SKIP
                message = "optional capability is not declared by adapter"
            results.append(
                CheckResult(
                    check.id,
                    check.title,
                    check.capability,
                    level,
                    status,
                    0.0,
                    message,
                    check.fixture,
                )
            )
            continue

        adapter = factory()
        candidate_metadata = validate_adapter(adapter)
        if candidate_metadata.name != metadata.name or candidate_metadata.capabilities != metadata.capabilities:
            results.append(
                CheckResult(
                    check.id,
                    check.title,
                    check.capability,
                    level,
                    CheckStatus.FAIL,
                    0.0,
                    "adapter factory returned inconsistent metadata",
                    check.fixture,
                )
            )
            continue
        check_started = time.perf_counter()
        try:
            adapter.reset()
            check.function(adapter)
        except Exception as error:
            duration = time.perf_counter() - check_started
            results.append(
                CheckResult(
                    check.id,
                    check.title,
                    check.capability,
                    level,
                    CheckStatus.FAIL,
                    duration,
                    "%s: %s" % (type(error).__name__, error),
                    check.fixture,
                )
            )
        else:
            duration = time.perf_counter() - check_started
            results.append(
                CheckResult(
                    check.id,
                    check.title,
                    check.capability,
                    level,
                    CheckStatus.PASS,
                    duration,
                    "",
                    check.fixture,
                )
            )
    return RunResult(
        adapter=metadata,
        profile=profile,
        results=tuple(results),
        duration_seconds=time.perf_counter() - started,
    )


def run_adapter(spec: str = "reference", profile_name: str = "core") -> RunResult:
    return run_conformance(resolve_adapter_factory(spec), get_profile(profile_name))
