---
name: memory-sync
description: >
  Scrape and analyze OpenClaw JSONL session logs to reconstruct and backfill 
  agent memory files. Use when: (1) Memory appears incomplete after model 
  switches, (2) Verifying memory coverage, (3) Reconstructing lost memory, 
  (4) Automated daily memory sync via cron/heartbeat. Supports simple 
  extraction and LLM-based narrative summaries with automatic secret 
  sanitization.
---

# Memory Sync

Tool for maintaining agent memory continuity across model switches with automatic secret sanitization.

## Installation

Requires Python 3.11+ and `click`:

```bash
pip install click

# Optional: for LLM-generated summaries
pip install anthropic
```

## Quick Start

```bash
# Run directly from scripts directory
python ~/.openclaw/skills/memory-sync/scripts/memory_sync.py compare

# Or create an alias for convenience
alias memory-sync="python ~/.openclaw/skills/memory-sync/scripts/memory_sync.py"

# Check for gaps
memory-sync compare

# Backfill today's memory
memory-sync backfill --today

# Backfill with LLM narrative (requires anthropic and ANTHROPIC_API_KEY)
memory-sync backfill --today --summarize

# Backfill all missing
memory-sync backfill --all
```

## Commands

| Command | Description |
|---------|-------------|
| `compare` | Find gaps between session logs and memory files |
| `backfill --today` | Generate memory for current day |
| `backfill --since YYYY-MM-DD` | Backfill from date to present |
| `backfill --all` | Backfill all missing dates |
| `backfill --incremental` | Backfill only changed dates since last run |
| `extract` | Extract conversations matching criteria |
| `summarize --date YYYY-MM-DD` | Generate LLM summary for a single day |
| `transitions` | List model transitions |
| `validate` | Check memory files for consistency issues |
| `stats` | Show coverage statistics |

## Common Workflows

### Initial Setup

```bash
# Check what's missing
memory-sync compare

# Backfill everything (may take time)
memory-sync backfill --all
```

### Nightly Automation (Recommended)

```bash
# Fast: Process only today (~30-60 seconds)
memory-sync backfill --today --summarize

# Smart: Process only days changed since last run
memory-sync backfill --incremental --summarize
```

### Catch-Up After Gaps

```bash
# Backfill from last week to present
memory-sync backfill --since 2026-01-28 --summarize
```

### Regenerate with Preserved Content

```bash
# Keep hand-written notes when regenerating
memory-sync backfill --date 2026-02-05 --force --preserve --summarize
```

## Secret Sanitization

All content is automatically sanitized to prevent secret leakage:

- **30+ explicit patterns**: OpenAI, Anthropic, GitHub, AWS, Stripe, Discord, Slack, Notion, Google, Brave, Tavily, SerpAPI, etc.
- **Structural detection**: JWT tokens, SSH keys, database connection strings, high-entropy base64
- **Generic patterns**: API keys, tokens, passwords, environment variables
- **Defense-in-depth**: Secrets redacted at every stage (extraction, LLM processing, file writes, CLI display)

Secrets are replaced with `[REDACTED-TYPE]` placeholders.

See `references/SECRET_PATTERNS.md` for complete pattern list.

## Automated Usage

### Nightly Cron (3am)

Process today only - fast and efficient:

```bash
0 3 * * * cd ~/.openclaw/skills/memory-sync && python scripts/memory_sync.py backfill --today --summarize >> ~/.memory-sync/cron.log 2>&1
```

### Smart Incremental Mode

Automatically detects changes since last run:

```bash
# Initial backfill (run once)
python scripts/memory_sync.py backfill --all --summarize

# Then set up nightly incremental
0 3 * * * cd ~/.openclaw/skills/memory-sync && python scripts/memory_sync.py backfill --incremental --summarize >> ~/.memory-sync/cron.log 2>&1
```

State is tracked in `~/.memory-sync/state.json`.

## Configuration

**Default paths:**
- Session logs: `~/.openclaw/agents/main/sessions/*.jsonl`
- Memory files: `~/.openclaw/workspace/memory/`

**Override with CLI flags:**
- `--sessions-dir /path/to/sessions`
- `--memory-dir /path/to/memory`

**Environment variables:**
- `ANTHROPIC_API_KEY` - Required for `--summarize` option

```bash
# Set temporarily
export ANTHROPIC_API_KEY=sk-ant-...

# Or add to shell profile
echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.bashrc
source ~/.bashrc
```

## Content Preservation

When regenerating existing files with `--force --preserve`:

- **Simple mode**: Hand-written content (after footer) is appended
- **LLM mode** (`--summarize`): Existing content is passed to LLM with instructions to incorporate it, preserving temporal order and thematic structure

Auto-generated markers:
- Header: `*Auto-generated from N session messages*`
- Footer: `*Review and edit this draft to capture what's actually important.*`

Content after the footer marker is considered hand-written and will be preserved.

## Backfill Options

**Date selection (choose one):**
- `--date YYYY-MM-DD` - Single specific date
- `--today` - Current date only (for nightly automation)
- `--since YYYY-MM-DD` - From date to present (for catch-up)
- `--all` - All missing dates (for initial setup)
- `--incremental` - Only dates changed since last run (smart automation)

**Additional flags:**
- `--dry-run` - Show what would be created without creating files
- `--force` - Overwrite existing files (required for regeneration)
- `--preserve` - Keep hand-written content when regenerating
- `--summarize` - Use LLM for narrative summaries (requires ANTHROPIC_API_KEY)
- `--model MODEL` - Model for summarization (default: claude-sonnet-4-20250514)

## Performance

| Mode | Time per Day | Best For |
|------|-------------|----------|
| `--all` | 5-10 min × N days | Initial setup only |
| `--since` | 5-10 min × N days | Recovery after gaps |
| `--today` | 30-60 sec | Nightly automation |
| `--incremental` | 30-60 sec × changed days | Smart automation |
