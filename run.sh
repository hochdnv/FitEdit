#!/bin/sh
# Start the FIT viewer/editor for the .fit files in this folder.
set -eu

dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Remove a trailing slash so the passed path is a clean directory name.
dir=${dir%/}
cd "$dir"

venv_dir="$dir/.venv"
python_bin="${venv_dir}/bin/python"

if [ ! -x "$python_bin" ]; then
  echo "Creating virtual environment..."
  python3 -m venv "$venv_dir"
fi

"$python_bin" -m pip install --upgrade pip >/dev/null 2>&1 || true
printf 'Installing Garmin Connect support...\n'
"$python_bin" -m pip install -r "$dir/requirements-garmin.txt"
printf '\nVirtual environment: %s\n' "$venv_dir"
printf 'Starting FIT Editor at http://127.0.0.1:8731/\n'
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  xdg-open "http://127.0.0.1:8731/" >/dev/null 2>&1 || true
fi
exec "$python_bin" -m fitedit --dir "$dir" --no-browser "$@"
