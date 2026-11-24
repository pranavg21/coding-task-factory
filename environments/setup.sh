#!/usr/bin/env bash
# Recreate a supplied repository at its pinned commit, with dependencies installed, ready for the factory.
# Usage: bash environments/setup.sh <click|zod|jsoncpp> <target_dir>
# Every environment step is listed here so judges can reproduce it; none of it edits the repository's code.
set -euo pipefail
NAME="${1:?click|zod|jsoncpp}"; DEST="${2:?target directory}"

checkout() {  # url sha
  git clone --quiet "$1" "$DEST"
  git -C "$DEST" checkout --quiet "$2"
  echo "pinned $(git -C "$DEST" rev-parse HEAD)"
}

case "$NAME" in
  click)
    checkout https://github.com/pallets/click 08b803cf32ceb2ae6a772c62d5da42757a897d44
    python3 -m venv "$DEST/.venv"
    "$DEST/.venv/bin/pip" install --quiet -e "$DEST" pytest==9.2.0
    echo "python for the factory: $DEST/.venv/bin/python"
    ;;
  zod)
    checkout https://github.com/colinhacks/zod d40c329910436e528d3c26cb1b9179e05abebf05
    # Zod is built with the Nub package manager (CONTRIBUTING.md), which is not on npm. Its lockfile is in
    # pnpm format, so pnpm installs the same dependency set with two environment-only adjustments:
    #   1. a pnpm-workspace.yaml listing packages/* (pnpm does not read package.json "workspaces"), and
    #   2. package-manager-strict=false, so pnpm does not refuse a project that names another manager.
    # The docs package's postinstall calls `nub` and fails; it is not needed to run the tests.
    # See README "Environment notes". Neither step changes Zod's source or tests.
    printf 'packages:\n  - "packages/*"\n' > "$DEST/pnpm-workspace.yaml"
    (cd "$DEST" && pnpm install --no-frozen-lockfile --config.package-manager-strict=false >/dev/null 2>&1) || true
    (cd "$DEST" && git checkout --quiet -- pnpm-lock.yaml)  # keep the repository's lockfile untouched
    "$DEST/node_modules/.bin/vitest" --version
    ;;
  jsoncpp)
    checkout https://github.com/open-source-parsers/jsoncpp 93acc7b155048f1a66c43235cc205519f1e7a6ea
    for tool in cmake ninja g++; do command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }; done
    echo "the harness builds jsoncpp itself (cmake + ninja)"
    ;;
  *) echo "unknown repository: $NAME" >&2; exit 2 ;;
esac
