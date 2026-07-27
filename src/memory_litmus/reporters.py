"""Text, JSON, JUnit XML, and SARIF 2.1.0 renderers."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Callable, Dict

from .runner import CheckStatus, RunResult


FORMATS = ("text", "json", "junit", "sarif")


def render_text(run: RunResult) -> str:
    counts = run.counts()
    lines = [
        "MemoryLitmus %s profile — adapter %s %s"
        % (run.profile.name, run.adapter.name, run.adapter.version),
        "",
    ]
    markers = {CheckStatus.PASS: "PASS", CheckStatus.FAIL: "FAIL", CheckStatus.SKIP: "SKIP"}
    for result in run.results:
        line = "[%s] %-34s %s" % (markers[result.status], result.check_id, result.title)
        if result.message:
            line += " — " + result.message
        lines.append(line)
    lines.extend(
        [
            "",
            "%s: %d passed, %d failed, %d skipped (%.3fs)"
            % (
                "CONFORMANT" if run.passed else "NON-CONFORMANT",
                counts["pass"],
                counts["fail"],
                counts["skip"],
                run.duration_seconds,
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def render_json(run: RunResult) -> str:
    return json.dumps(run.to_dict(), indent=2, sort_keys=True) + "\n"


def render_junit(run: RunResult) -> str:
    counts = run.counts()
    root = ET.Element(
        "testsuites",
        {
            "name": "MemoryLitmus",
            "tests": str(len(run.results)),
            "failures": str(counts["fail"]),
            "skipped": str(counts["skip"]),
            "time": "%.6f" % run.duration_seconds,
        },
    )
    suite = ET.SubElement(
        root,
        "testsuite",
        {
            "name": "%s.%s" % (run.adapter.name, run.profile.name),
            "tests": str(len(run.results)),
            "failures": str(counts["fail"]),
            "errors": "0",
            "skipped": str(counts["skip"]),
            "time": "%.6f" % run.duration_seconds,
        },
    )
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(properties, "property", {"name": "adapter.version", "value": run.adapter.version})
    ET.SubElement(properties, "property", {"name": "profile", "value": run.profile.name})
    for result in run.results:
        case = ET.SubElement(
            suite,
            "testcase",
            {
                "classname": "memory_litmus.%s" % result.capability.value,
                "name": result.check_id,
                "time": "%.6f" % result.duration_seconds,
            },
        )
        if result.status is CheckStatus.FAIL:
            failure = ET.SubElement(case, "failure", {"message": result.message, "type": "ConformanceFailure"})
            failure.text = result.title
        elif result.status is CheckStatus.SKIP:
            ET.SubElement(case, "skipped", {"message": result.message})
    xml_body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body + "\n"


def render_sarif(run: RunResult) -> str:
    rules = []
    results = []
    for check in run.results:
        rules.append(
            {
                "id": check.check_id,
                "name": check.check_id.replace(".", "_"),
                "shortDescription": {"text": check.title},
                "fullDescription": {
                    "text": "%s capability check using fixture %s."
                    % (check.capability.value, check.fixture)
                },
                "properties": {
                    "capability": check.capability.value,
                    "level": check.level.value,
                },
            }
        )
        if check.status is CheckStatus.FAIL:
            kind = "fail"
            level = "error"
        elif check.status is CheckStatus.PASS:
            kind = "pass"
            level = "none"
        else:
            kind = "notApplicable"
            level = "none"
        results.append(
            {
                "ruleId": check.check_id,
                "kind": kind,
                "level": level,
                "message": {"text": check.message or check.title},
                "properties": {
                    "capability": check.capability.value,
                    "profileLevel": check.level.value,
                    "durationSeconds": round(check.duration_seconds, 6),
                },
            }
        )
    document = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "MemoryLitmus",
                        "semanticVersion": "0.1.0",
                        "rules": rules,
                    }
                },
                "invocations": [
                    {
                        "executionSuccessful": run.passed,
                        "properties": {
                            "adapter": run.adapter.name,
                            "adapterVersion": run.adapter.version,
                            "profile": run.profile.name,
                        },
                    }
                ],
                "results": results,
            }
        ],
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


_RENDERERS: Dict[str, Callable[[RunResult], str]] = {
    "text": render_text,
    "json": render_json,
    "junit": render_junit,
    "sarif": render_sarif,
}


def render(run: RunResult, format_name: str) -> str:
    try:
        renderer = _RENDERERS[format_name]
    except KeyError:
        raise ValueError("unknown report format %r" % format_name)
    return renderer(run)
