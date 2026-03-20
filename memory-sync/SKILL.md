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

## Recent Changes (March 2026)

### v2.0 - Major Consolidation Improvements

1. **OpenClaw Backend Default** - Uses `openclaw agent` CLI instead of external APIs (no API key management)
2. **Session File Discovery** - Now scans `.jsonl.reset.*` and `.jsonl.deleted.*` files (OpenClaw moves sessions aside during compaction)
3. **User Conversation Priority** - LLM summaries now prioritize USER messages over cron/automated activity
4. **Telegram Envelope Stripping** - Extracts actual message content from channel metadata wrappers
5. **Chunked Parallel Summarization** - Large days (>80k chars) are split into 60k chunks, processed in parallel (3 workers)
6. **Tool Result Truncation** - Large tool outputs (API dumps, web fetches) truncated to 15k chars with note

## Installation

Requires Python 3.11+ and `click`:

```bash
pip install click
```

## Quick Start

```bash
# Check for gaps
python ~/.openclaw/skills/memory-sync/memory_sync.py compare

# Backfill with LLM summary (recommended)
python ~/.openclaw/skills/memory-sync/memory_sync.py backfill --today --summarize --preserve

# Backfill all missing dates
python ~/.openclaw/skills/memory-sync/memory_sync.py backfill --all --summarize
```

## Commands

| Command | Description |
|---------|-------------|
| `compare` | Find gaps between session logs and memory files |
| `backfill --today` | Generate memory for current day |
| `backfill --date YYYY-MM-DD` | Backfill specific date |
| `backfill --incremental` | Backfill only changed dates since last run |
| `backfill --all` | Backfill all missing dates |
| `stats` | Show coverage statistics |
| `transitions` | List model transitions |
| `validate` | Check memory files for consistency issues |

## Key Options

```bash
# Core flags
--summarize              # Use LLM for narrative summaries (recommended)
--preserve               # Keep hand-written content when regenerating
--force                  # Overwrite existing files
--dry-run                # Preview without creating files

# Backend selection (openclaw is default)
--summarize-backend openclaw    # Uses OpenClaw gateway (default, no API key needed)
--summarize-backend anthropic   # Direct Anthropic API (requires ANTHROPIC_API_KEY)
--summarize-backend openai      # Direct OpenAI API (requires OPENAI_API_KEY)
```

## How It Works

### Session File Discovery

Scans ALL session files including moved-aside ones:
- `*.jsonl` - Active session files
- `*.jsonl.reset.*` - Sessions moved during compaction
- `*.jsonl.deleted.*` - Soft-deleted sessions

This ensures conversations aren't lost when OpenClaw resets sessions.

### User Conversation Priority

The LLM prompt explicitly prioritizes:
1. **USER messages** - Questions, discussions, decisions (HIGHEST)
2. **User insights** - Philosophical discussions, creative work
3. **Technical accomplishments** - Only after user content
4. **Cron/automated activity** - Lowest priority, often omitted

This prevents days with heavy cron activity from overshadowing important conversations.

### Telegram Envelope Stripping

Messages from Telegram arrive wrapped in metadata:
```
Conversation info (untrusted metadata):
```json
{ "message_id": "123", ... }
```

Actual message here
```

The tool extracts just the actual message content for summarization.

### Chunked Parallel Summarization

For large days (>80k chars total):
1. Split messages into 60k char chunks (size-based, not time-based)
2. Summarize each chunk in parallel (3 workers)
3. Synthesize chunk summaries into final daily summary

This handles days with 1000+ messages without timeout or context overflow.

### Tool Result Truncation

Large tool outputs (API responses, web fetches) are truncated to 15k chars:
- Preserves the fact that the tool was called
- Notes original size: `[... TRUNCATED - original was 200,000 chars ...]`
- Prevents JSON/HTML dumps from overwhelming summaries

## Nightly Automation

### Recommended Cron Job

```bash
# 3am daily - incremental backfill with LLM summaries
0 3 * * * cd ~/.openclaw/skills/memory-sync && python memory_sync.py backfill --incremental --summarize --preserve
```

### OpenClaw Cron Setup

```bash
openclaw cron add \
  --schedule "0 3 * * *" \
  --name "Nightly memory backfill" \
  --task "cd ~/.openclaw/skills/memory-sync && python memory_sync.py backfill --incremental --summarize --preserve"
```

## Secret Sanitization

All content is automatically sanitized:
- 30+ explicit patterns (OpenAI, Anthropic, GitHub, AWS, etc.)
- JWT tokens, SSH keys, connection strings
- High-entropy base64 detection
- Secrets replaced with `[REDACTED-TYPE]` placeholders

## Configuration

**Default paths:**
- Session logs: `~/.openclaw/agents/main/sessions/*.jsonl*`
- Memory files: `~/.openclaw/workspace/memory/`

**Override:**
- `--sessions-dir /path/to/sessions`
- `--memory-dir /path/to/memory`

## Performance

| Scenario | Time | Notes |
|----------|------|-------|
| Light day (<100 msgs) | 30-60 sec | Single LLM call |
| Normal day (100-500 msgs) | 1-2 min | Single LLM call |
| Heavy day (500+ msgs) | 5-10 min | Chunked parallel (3 workers) |
| Very heavy day (1000+ msgs) | 10-15 min | 15+ chunks, parallel |

## Troubleshooting

### "Lost" Conversations

If conversations seem missing:
1. Check for `.reset` or `.deleted` session files
2. Run `memory-sync stats` to see total message count
3. Re-run backfill with `--force`

### Summaries Missing User Content

The LLM prompt prioritizes user conversations. If still missing:
1. Check if messages were in a `.reset` file (now auto-scanned)
2. Verify Telegram envelope stripping is working
3. Check for very large tool results overwhelming the context

### Slow Backfills

For very large days:
- Chunked parallel processing kicks in automatically
- 3 workers process chunks simultaneously
- Progress shown: `Summarizing chunk X/Y`
