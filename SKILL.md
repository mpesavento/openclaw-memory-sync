---
name: memory-sync
description: >
  Scrape and analyze OpenClaw JSONL session logs to reconstruct, validate,
  and backfill agent memory files. Use when: (1) Memory appears incomplete after
  model switches, (2) Verifying memory coverage, (3) Reconstructing lost memory,
  (4) Running automated daily memory sync via cron/heartbeat. Supports simple
  extraction and LLM-based narrative summaries. Commands: compare, backfill,
  summarize, extract, transitions, validate, stats.
---

# Memory Sync

Tool for maintaining agent memory continuity across model switches.

## Quick Start

```bash
# Check what's missing
uv run memory-sync compare

# Backfill a specific date
uv run memory-sync backfill --date 2026-02-05

# Backfill all missing (simple extraction)
uv run memory-sync backfill --all

# Backfill with LLM narrative summaries
uv run memory-sync backfill --all --summarize

# Preserve existing hand-written content
uv run memory-sync backfill --date 2026-02-05 --preserve
```

## Installation

```bash
# Clone and run with uv (recommended)
git clone https://github.com/mpesavento/openclaw-memory-sync.git
cd openclaw-memory-sync
uv run memory-sync compare

# Or install globally
uv tool install .
memory-sync compare

# Or with pip
pip install -e .
pip install -e '.[summarize]'  # for LLM support
```

## Commands Reference

### compare

Compare JSONL logs against memory files, identify gaps.

```bash
uv run memory-sync compare
uv run memory-sync compare --sessions-dir /path/to/sessions --memory-dir /path/to/memory
```

### backfill

Generate missing daily memory files from JSONL logs.

```bash
# Single date
uv run memory-sync backfill --date 2026-02-05

# All missing dates
uv run memory-sync backfill --all

# With LLM summarization
uv run memory-sync backfill --date 2026-02-05 --summarize

# Preview without creating
uv run memory-sync backfill --all --dry-run

# Overwrite existing
uv run memory-sync backfill --date 2026-02-05 --force

# Preserve hand-written content when regenerating
uv run memory-sync backfill --date 2026-02-05 --force --preserve
```

Options:
- `--date YYYY-MM-DD` - Specific date to backfill
- `--all` - Backfill all missing dates
- `--dry-run` - Show what would be created
- `--force` - Overwrite existing files
- `--preserve` - Keep hand-written content when regenerating
- `--summarize` - Use LLM for narrative summaries (requires ANTHROPIC_API_KEY)
- `--model MODEL` - Model for summarization (default: claude-sonnet-4-20250514)

### summarize

Generate an LLM summary for a single day.

```bash
uv run memory-sync summarize --date 2026-02-05
uv run memory-sync summarize --date 2026-02-05 --output /path/to/output.md
```

### extract

Extract conversations matching criteria.

```bash
uv run memory-sync extract --date 2026-02-05
uv run memory-sync extract --query "memory sync"
uv run memory-sync extract --model claude-sonnet-4 --format json
```

Options: `--date`, `--query`, `--model`, `--format [md|json|text]`

### transitions

List model transitions with context.

```bash
uv run memory-sync transitions
uv run memory-sync transitions --since 2026-02-01
uv run memory-sync transitions --output transitions.json
```

### validate

Check memory files for consistency issues.

```bash
uv run memory-sync validate
```

### stats

Show coverage statistics.

```bash
uv run memory-sync stats
```

## Automated Usage (Cron/Heartbeat)

### Daily Memory Sync

Run at end of day to ensure memory coverage:

```bash
# Simple extraction (fast, no API needed)
0 23 * * * cd ~/projects/memory-sync && uv run memory-sync backfill --all

# With LLM summarization (requires ANTHROPIC_API_KEY)
0 23 * * * cd ~/projects/memory-sync && uv run memory-sync backfill --all --summarize
```

### Heartbeat Check

Quick coverage check every few hours:

```bash
# Every 4 hours, log gaps to file
0 */4 * * * cd ~/projects/memory-sync && uv run memory-sync compare >> /var/log/memory-gaps.log 2>&1
```

### OpenClaw Hook Integration

Can be triggered as a post-session hook or heartbeat task.

## Configuration

**Default paths:**
- Session logs: `~/.openclaw/agents/main/sessions/*.jsonl`
- Memory files: `~/.openclaw/workspace/memory/`

**Override with CLI flags:**
- `--sessions-dir /path/to/sessions`
- `--memory-dir /path/to/memory`

**Environment variables:**
- `ANTHROPIC_API_KEY` - Required for `--summarize` option

## Content Preservation

When regenerating a memory file that already exists:

- **Without `--preserve`**: Existing file is completely replaced
- **With `--preserve`**: Hand-written content (after the auto-generated footer) is preserved

Auto-generated markers:
- Header: `*Auto-generated from N session messages*`
- Footer: `*Review and edit this draft to capture what's actually important.*`

Content after the footer marker is considered hand-written and will be preserved.
