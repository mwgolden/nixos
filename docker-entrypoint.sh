#!/usr/bin/env bash
set -e

git config --global --add safe.directory /workspace

# Run the given command (bootstrap.sh passes a build command), or an
# interactive shell by default.
exec "$@"
