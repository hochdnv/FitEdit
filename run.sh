#!/bin/sh
# Start the FIT viewer/editor for the .fit files in this folder.
set -eu

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$dir"

python=python3
command -v "$python" >/dev/null 2>&1 || python=python

exec "$python" -m fitedit --dir "$dir" "$@"
