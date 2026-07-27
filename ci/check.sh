#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

printf '%s\n' '==> unittest'
python3 -m unittest discover -s "$ROOT/tests" -v

printf '%s\n' '==> compileall'
python3 -m compileall -q "$ROOT/src" "$ROOT/tests" "$ROOT/examples"

printf '%s\n' '==> full reference conformance'
python3 -m memory_litmus run reference --profile full >/dev/null

printf '%s\n' '==> intentional-break detection'
set +e
python3 -m memory_litmus run broken-dedup --profile core >/dev/null 2>&1
status=$?
set -e
if [ "$status" -ne 1 ]; then
    printf '%s\n' "broken-dedup returned $status; expected semantic-failure exit 1" >&2
    exit 1
fi

printf '%s\n' 'All MemoryLitmus checks passed.'
