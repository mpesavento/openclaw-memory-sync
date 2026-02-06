---
name: memory-sync
description: >
  Scrape and analyze OpenClaw JSONL session logs to reconstruct, validate,
  and backfill agent memory files. Use when memory appears incomplete,
  after model switches, or to verify memory coverage. Tracks model transitions
  and identifies gaps between session logs and memory files.
---

# Memory Sync

Tool for maintaining agent memory continuity across model switches.

## Quick Start

```bash
# Check coverage
uv run --directory ~/projects/memory-sync memory-sync compare

# Backfill missing day
uv run --directory ~/projects/memory-sync memory-sync backfill --date 2026-02-05

# List model transitions
uv run --directory ~/projects/memory-sync memory-sync transitions
```

## Commands

### compare
Compare JSONL logs against memory files, identify gaps.

### backfill
Generate missing daily memory files from JSONL logs.

Options: `--date YYYY-MM-DD`, `--all`, `--dry-run`, `--force`

### extract
Extract conversations matching criteria.

Options: `--date`, `--query`, `--model`, `--format`

### transitions
List model transitions with context.

### validate
Check memory files for consistency issues.

### stats
Show coverage statistics.

## Configuration

Default session logs: `~/.openclaw/agents/main/sessions/*.jsonl`
Default memory dir: `~/.openclaw/workspace/memory/`

Override with `--sessions-dir` and `--memory-dir` flags.
