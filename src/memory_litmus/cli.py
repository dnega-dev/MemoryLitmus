"""Command-line interface for MemoryLitmus."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence, TextIO

from . import __version__
from .adapters import BUILTIN_ADAPTERS
from .fixtures import FIXTURES
from .profiles import PROFILES, get_profile
from .reporters import FORMATS, render
from .runner import run_adapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory-litmus",
        description="Capability-aware conformance suite for agent-memory semantics.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    commands = parser.add_subparsers(dest="command", required=True)

    adapters = commands.add_parser("adapters", help="Inspect adapter catalog")
    adapter_commands = adapters.add_subparsers(dest="adapters_command", required=True)
    adapters_list = adapter_commands.add_parser("list", help="List bundled adapters")
    adapters_list.add_argument("--format", choices=("text", "json"), default="text")

    run = commands.add_parser("run", help="Run conformance checks")
    run.add_argument(
        "adapter",
        nargs="?",
        default="reference",
        help="Bundled name or importable module:factory (default: reference)",
    )
    run.add_argument("--profile", choices=tuple(sorted(PROFILES)), default="core")
    run.add_argument("--format", choices=FORMATS, default="text")
    run.add_argument("--output", default="-", help="Report path, or - for stdout")

    profile = commands.add_parser("profile", help="Inspect capability profiles")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    profile_show = profile_commands.add_parser("show", help="Show one capability profile")
    profile_show.add_argument("name", nargs="?", choices=tuple(sorted(PROFILES)), default="core")
    profile_show.add_argument("--format", choices=("text", "json"), default="text")

    fixtures = commands.add_parser("fixtures", help="Inspect deterministic fixtures")
    fixture_commands = fixtures.add_subparsers(dest="fixtures_command", required=True)
    fixtures_list = fixture_commands.add_parser("list", help="List bundled fixture scenarios")
    fixtures_list.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def _adapter_catalog(format_name: str) -> str:
    rows = []
    for name in sorted(BUILTIN_ADAPTERS):
        metadata = BUILTIN_ADAPTERS[name]().metadata()
        rows.append(
            {
                "name": name,
                "version": metadata.version,
                "description": metadata.description,
                "intentional_failure": name.startswith("broken-"),
                "capabilities": sorted(item.value for item in metadata.capabilities),
            }
        )
    if format_name == "json":
        return json.dumps({"adapters": rows}, indent=2, sort_keys=True) + "\n"
    lines = ["Bundled adapters:"]
    for row in rows:
        marker = " [intentionally broken]" if row["intentional_failure"] else ""
        lines.append("  %-25s %s%s" % (row["name"], row["description"], marker))
    return "\n".join(lines) + "\n"


def _profile_text(name: str, format_name: str) -> str:
    profile = get_profile(name)
    if format_name == "json":
        return json.dumps(profile.to_dict(), indent=2, sort_keys=True) + "\n"
    lines = [profile.name + ": " + profile.description, "Required:"]
    lines.extend("  - " + item.value for item in sorted(profile.required, key=lambda item: item.value))
    lines.append("Optional:")
    lines.extend("  - " + item.value for item in sorted(profile.optional, key=lambda item: item.value))
    if not profile.optional:
        lines.append("  (none)")
    return "\n".join(lines) + "\n"


def _fixture_text(format_name: str) -> str:
    rows = [fixture.to_dict() for fixture in FIXTURES]
    if format_name == "json":
        return json.dumps({"fixtures": rows}, indent=2, sort_keys=True) + "\n"
    lines = ["Bundled fixtures:"]
    for fixture in FIXTURES:
        lines.append("  %-24s %-23s %s" % (fixture.name, fixture.capability, fixture.description))
    return "\n".join(lines) + "\n"


def _write_output(content: str, destination: str, stdout: TextIO) -> None:
    if destination == "-":
        stdout.write(content)
        return
    Path(destination).write_text(content, encoding="utf-8")


def main(
    argv: Optional[Sequence[str]] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    output_stream = stdout or sys.stdout
    error_stream = stderr or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "adapters":
            output_stream.write(_adapter_catalog(args.format))
            return 0
        if args.command == "profile":
            output_stream.write(_profile_text(args.name, args.format))
            return 0
        if args.command == "fixtures":
            output_stream.write(_fixture_text(args.format))
            return 0
        if args.command == "run":
            result = run_adapter(args.adapter, args.profile)
            _write_output(render(result, args.format), args.output, output_stream)
            return 0 if result.passed else 1
    except (ImportError, AttributeError, KeyError, TypeError, ValueError, OSError) as error:
        error_stream.write("memory-litmus: %s\n" % error)
        return 2
    parser.error("unhandled command")
    return 2
