#!/usr/bin/env bash
cd "$(dirname "$0")"
PY=python3
command -v python3 >/dev/null || PY=python
$PY watch.py --seed
exec $PY watch.py --daemon
