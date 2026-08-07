#!/usr/bin/env bash
# Seed/refresh the local `data` branch from the state files currently on disk
# (history.json, about.json, *_seen.json, *_alert.json). CI reads and writes state
# on that orphan branch so bot commits stay out of main's history.
#
# Run this right before pushing the state-branch migration — and re-run it first if
# CI has committed newer state to main in the meantime — then: git push origin main data
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
WT=$(mktemp -d)
if ! git rev-parse -q --verify data >/dev/null; then
  git branch data "$(git commit-tree "$(git mktree </dev/null)" -m 'state: seed data branch')"
fi
git worktree add "$WT" data
mkdir -p "$WT/data"
cp -f data/history.json data/about.json data/*_seen.json data/*_alert.json "$WT/data/" 2>/dev/null || true
git -C "$WT" add -A data
git -C "$WT" diff --cached --quiet || git -C "$WT" commit -m "state: seed from working tree $(date -u +%FT%TZ)"
git worktree remove "$WT"
echo "data branch ready: $(git log -1 --oneline data --)"
