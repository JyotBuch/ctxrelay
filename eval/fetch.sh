#!/bin/sh
# Clone each repo in repos.toml at its pinned SHA into eval/.cache/<name>.
set -e
cd "$(dirname "$0")"
mkdir -p .cache
python3 - <<'PY' | while read -r name url sha; do
import tomllib
for r in tomllib.load(open("repos.toml", "rb"))["repo"]:
    print(r["name"], r["url"], r["sha"])
PY
  if [ ! -d ".cache/$name/.git" ]; then
    git init -q ".cache/$name"
    git -C ".cache/$name" remote add origin "$url"
  fi
  git -C ".cache/$name" fetch -q --depth 1 origin "$sha"
  git -C ".cache/$name" checkout -q FETCH_HEAD
  echo "$name @ $sha"
done
