#!/usr/bin/env bash
# Vendor the srbounce package (validated strategy code) into the build context,
# then build the image. Run from the repo root.
set -euo pipefail

SRBOUNCE_SRC="${SRBOUNCE_SRC:-$HOME}"   # dir containing srbounce/ + pyproject.toml

rm -rf srbounce-pkg
mkdir -p srbounce-pkg/srbounce
cp "$SRBOUNCE_SRC"/srbounce/*.py srbounce-pkg/srbounce/
cp "$SRBOUNCE_SRC"/pyproject.toml srbounce-pkg/

docker compose build
echo "Built. Start with: docker compose up -d"
