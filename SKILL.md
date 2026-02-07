---
name: memory-sync
description: >
  Scrape and analyze OpenClaw JSONL session logs to reconstruct, validate,
  and backfill agent memory files. Use when: (1) Memory appears incomplete after
  model switches, (2) Verifying memory coverage, (3) Reconstructing lost memory,
  (4) Running automated daily memory sync via cron/heartbeat. Supports simple
  extraction and LLM-based narrative summaries with incremental backfill modes
  (--today, --since, --incremental) for efficient nightly automation. Commands:
  compare, backfill, summarize, extract, transitions, validate, stats. Includes
  automatic secret sanitization (30+ API key patterns, JWT, SSH keys, passwords)
  with multiple validation layers to prevent secret leakage.
---

# Memory Sync

**REQUIREMENTS:**
- **`uv` package manager** - All commands must be run with `uv run` prefix
- **`ANTHROPIC_API_KEY`** - Required for `--summarize` mode (LLM narrative summaries)
  - Set in environment: `export ANTHROPIC_API_KEY=sk-ant-...`
  - Or add to shell profile: `echo 'export ANTHROPIC_API_KEY=sk-ant-...' >> ~/.bashrc`
  - Simple extraction mode works without API key

Tool for maintaining agent memory continuity across model switches with automatic secret sanitization and incremental backfill strategies.

## Quick Start

```bash
# Check what's missing
uv run memory-sync compare

# Backfill today only (fast, for nightly automation)
uv run memory-sync backfill --today --summarize

# Backfill a specific date
uv run memory-sync backfill --date 2026-02-05 --summarize

# Backfill from a date to present (catch-up after gap)
uv run memory-sync backfill --since 2026-02-01 --summarize

# Backfill only changed dates since last run (smart automation)
uv run memory-sync backfill --incremental --summarize

# Backfill all missing (initial setup)
uv run memory-sync backfill --all --summarize

# Regenerate existing file while preserving hand-written notes
uv run memory-sync backfill --date 2026-02-05 --force --preserve --summarize
```

## Installation

```bash
# As OpenClaw skill (recommended)
cd ~/.openclaw/skills
git clone git@github.com:mpesavento/openclaw-memory-sync.git memory-sync
# OpenClaw auto-discovers it

# Then run from skill directory:
cd ~/.openclaw/skills/memory-sync
uv run memory-sync compare

# Or install globally:
uv tool install .
memory-sync compare

# Or with pip:
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

**Date Selection (choose exactly one):**
- `--date YYYY-MM-DD` - Single specific date
- `--today` - Current date only (for nightly automation) ⭐
- `--since YYYY-MM-DD` - From date to present (for catch-up) ⭐
- `--all` - All missing dates (for initial setup)
- `--incremental` - Only dates changed since last run (smart automation) ⭐

**Examples by use case:**

```bash
# NIGHTLY AUTOMATION (recommended) - process today only
uv run memory-sync backfill --today --summarize

# CATCH-UP - backfill from last week
uv run memory-sync backfill --since 2026-01-28 --summarize

# SMART AUTOMATION - only process changes since last run
# (requires initial --all run first)
uv run memory-sync backfill --incremental --summarize

# INITIAL SETUP - backfill everything
uv run memory-sync backfill --all --summarize

# SINGLE DATE - specific day
uv run memory-sync backfill --date 2026-02-05 --summarize

# DRY RUN - preview what would be created
uv run memory-sync backfill --today --dry-run
```

**Regenerating Existing Files (--force --preserve):**

When you need to regenerate a memory file that already exists:

```bash
# REGENERATE with simple extraction, preserve hand-written notes
uv run memory-sync backfill --date 2026-02-05 --force --preserve

# REGENERATE with LLM, incorporate existing content into new summary
uv run memory-sync backfill --date 2026-02-05 --force --preserve --summarize

# REGENERATE today's file (e.g., after adding more context mid-day)
uv run memory-sync backfill --today --force --preserve --summarize

# REGENERATE multiple days, preserving all hand-written content
uv run memory-sync backfill --since 2026-02-01 --force --preserve --summarize

# REGENERATE all files with new summarization (preserves hand-written sections)
uv run memory-sync backfill --all --force --preserve --summarize
```

**When to use --force --preserve:**
- You added hand-written notes and want to regenerate with new session data
- Model improved and you want better summaries without losing your notes
- Session logs were updated (e.g., after a model switch you didn't catch)
- Switching from simple extraction to LLM summarization
- Testing different summarization models while keeping your edits

**Additional Options:**
- `--dry-run` - Show what would be created without creating files
- `--force` - Overwrite existing files (required for regeneration)
- `--preserve` - Keep hand-written content when regenerating
- `--summarize` - Use LLM for narrative summaries (requires ANTHROPIC_API_KEY)
- `--model MODEL` - Model for summarization (default: claude-sonnet-4-20250514)
- `--sessions-dir PATH` - Override default sessions directory
- `--memory-dir PATH` - Override default memory directory

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
uv run memory-sync transitions --date 2026-02-01
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

### Recommended: Nightly Automation with --today

**Fast and efficient** - processes only the current day (~30-60 seconds):

```bash
# Run daily at 3am (recommended approach)
0 3 * * * cd ~/.openclaw/skills/memory-sync && uv run memory-sync backfill --today --summarize >> ~/.memory-sync/cron.log 2>&1
```

### Alternative: Smart Incremental Mode

**Automatically detects changes** - tracks state and only processes modified dates:

```bash
# First, run initial backfill
cd ~/.openclaw/skills/memory-sync
uv run memory-sync backfill --all --summarize

# Then set up nightly incremental run
0 3 * * * cd ~/.openclaw/skills/memory-sync && uv run memory-sync backfill --incremental --summarize >> ~/.memory-sync/cron.log 2>&1
```

State is tracked in `~/.memory-sync/state.json`.

### Manual Catch-Up After Gaps

If you miss a few days or need to backfill a range:

```bash
# Backfill last 7 days
uv run memory-sync backfill --since 2026-01-28 --summarize

# Or use date command for dynamic ranges
uv run memory-sync backfill --since $(date -d "7 days ago" +%Y-%m-%d) --summarize
```

### Heartbeat Check (Optional)

Quick coverage check without processing:

```bash
# Every 4 hours, log gaps to file
0 */4 * * * cd ~/.openclaw/skills/memory-sync && uv run memory-sync compare >> /var/log/memory-gaps.log 2>&1
```

### Performance Comparison

| Mode | Time per Day | API Calls | Best For |
|------|-------------|-----------|----------|
| `--all` | 5-10 min × N days | High | Initial setup only |
| `--since` | 5-10 min × N days | High | Recovery after gaps |
| `--today` | 30-60 sec | 1 | **Nightly automation** ⭐ |
| `--incremental` | 30-60 sec × changed days | Low | Smart automation |

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
  ```bash
  # Set temporarily for current session
  export ANTHROPIC_API_KEY=sk-ant-api03-...
  
  # Or add to shell profile for persistence
  echo 'export ANTHROPIC_API_KEY=sk-ant-api03-...' >> ~/.bashrc
  source ~/.bashrc
  
  # Verify it's set
  echo $ANTHROPIC_API_KEY
  ```

## Content Preservation

When regenerating a memory file that already exists:

- **Without `--preserve`**: Existing file is completely replaced
- **With `--preserve` (simple mode)**: Hand-written content (after footer) is appended
- **With `--preserve` (--summarize mode)**: Existing content is passed to LLM with explicit instructions to incorporate it, preserving temporal order and thematic structure

### LLM Content Incorporation

When using `--preserve --summarize`, the LLM receives explicit guidance to:
1. **Preserve temporal order** - maintain chronological sequence and existing time sections
2. **Respect existing style** - match narrative vs. bullet format already used
3. **Merge by theme** - combine related topics rather than duplicating sections
4. **Preserve insights** - retain hand-written reflections and context
5. **Update, don't replace** - treat existing content as baseline, augment with new data
6. **Maintain headers** - keep existing section names and structure

Auto-generated markers:
- Header: `*Auto-generated from N session messages*`
- Footer: `*Review and edit this draft to capture what's actually important.*`

Content after the footer marker is considered hand-written and will be preserved.

## Security & Sanitization

All content is automatically sanitized to prevent secret leakage:

- **30+ explicit patterns**: OpenAI, Anthropic, GitHub, AWS, Stripe, Discord, Slack, Notion, Google, Brave, Tavily, SerpAPI, etc.
- **Structural detection**: JWT tokens, SSH keys, database connection strings, high-entropy base64
- **Generic patterns**: API keys, tokens, passwords, environment variables
- **Multiple validation layers**: Input sanitization, LLM prompt instructions, output validation
- **Defense-in-depth**: Secrets redacted at every stage (extraction, LLM processing, file writes, CLI display)

Secrets are replaced with `[REDACTED-TYPE]` placeholders.

See `docs/SECRET_PATTERNS.md` for complete pattern documentation.
