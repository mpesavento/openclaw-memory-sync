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

### v2.1 - Gemini Support + Filtering Improvements

1. **Gemini Model Support** - Use `--model gemini` with openclaw backend for large context summarization
2. **Internal Sessions Excluded** - memory-sync, subagent sessions filtered out (internal tooling, not conversations)
3. **Tool Results Excluded** - toolResult messages skipped entirely (raw data dumps, not useful for memory)
4. **Large Message Truncation** - Messages >5K chars truncated (huge pastes, file dumps)

### v2.0 - Major Consolidation Improvements

1. **OpenClaw Backend Default** - Uses `openclaw agent` CLI instead of external APIs (no API key management)
2. **Session File Discovery** - Now scans `.jsonl.reset.*` and `.jsonl.deleted.*` files
3. **User Conversation Priority** - LLM summaries prioritize USER messages over cron/automated activity
4. **Telegram Envelope Stripping** - Extracts actual message content from channel metadata wrappers
5. **Chunked Parallel Summarization** - Large days split into chunks, processed in parallel

## Installation

Requires Python 3.11+ and `click`:

```bash
pip install click
```

## Quick Start

```bash
# Check for gaps
python ~/.openclaw/skills/memory-sync/memory_sync.py compare

# Backfill today (uses Gemini by default)
python ~/.openclaw/skills/memory-sync/memory_sync.py backfill --today --summarize --preserve

# Backfill specific date
python ~/.openclaw/skills/memory-sync/memory_sync.py backfill --date 2026-03-22 --summarize --preserve

# Use Sonnet instead of Gemini
python ~/.openclaw/skills/memory-sync/memory_sync.py backfill --today --summarize --model sonnet --preserve
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

# Model selection (with openclaw backend)
--model gemini           # Use Gemini 2.5 Pro (DEFAULT - 1M+ context, handles huge days)
--model sonnet           # Use Claude Sonnet
--model opus             # Use Claude Opus

# Backend selection (openclaw is default)
--summarize-backend openclaw    # Uses OpenClaw gateway (default, no API key needed)
--summarize-backend anthropic   # Direct Anthropic API (requires ANTHROPIC_API_KEY)
--summarize-backend openai      # Direct OpenAI API (requires OPENAI_API_KEY)
```

## Gemini Setup (Required for Default)

Gemini is the default model. Create the memory-sync agent first:

```bash
openclaw agents add memory-sync --model google/gemini-2.5-pro --workspace ~/.openclaw/workspace --non-interactive
```

**Why Gemini is Default:**
- 1M+ token context window handles even massive days in one pass
- No chunking needed = better coherence
- Faster for heavy days (single call vs many chunk calls)

## What Gets Filtered Out

**NOT included in summaries (by design):**
- `toolResult` messages - Raw API responses, file contents, command output
- Internal sessions - memory-sync processing, subagents, synthesis
- Cron triggers - System automation, not user conversations
- Large pastes - Truncated to 5K chars (preserves first part + note)

**This keeps summaries focused on actual user conversations and decisions.**

## How It Works

### Session File Discovery

Scans user conversation sessions only:
- `*.jsonl` - Active session files
- `*.jsonl.reset.*` - Sessions moved during compaction
- `*.jsonl.deleted.*` - Soft-deleted sessions

**Excludes internal sessions:**
- `memory-sync-*` - Summarization processing
- `*subagent*` - Spawned subagents
- `*synthesis*` - Chunk synthesis sessions

### User Conversation Priority

The LLM prompt explicitly prioritizes:
1. **USER messages** - Questions, discussions, decisions (HIGHEST)
2. **User insights** - Philosophical discussions, creative work
3. **Technical accomplishments** - Only after user content
4. **Cron/automated activity** - Lowest priority, often omitted

### Telegram Envelope Stripping

Messages from Telegram arrive wrapped in metadata - the tool extracts just the actual message content.

## Nightly Automation

### Recommended Cron Job

```bash
# 3am daily - yesterday only (Gemini is default)
0 3 * * * cd ~/.openclaw/skills/memory-sync && python memory_sync.py backfill --date $(date -d yesterday +%Y-%m-%d) --summarize --preserve
```

### OpenClaw Cron Setup

```bash
openclaw cron add \
  --schedule "0 3 * * *" \
  --name "Nightly memory backfill" \
  --task "cd ~/.openclaw/skills/memory-sync && python memory_sync.py backfill --date \$(date -d yesterday +%Y-%m-%d) --summarize --preserve"
```

## Secret Sanitization

All content is automatically sanitized:
- 30+ explicit patterns (OpenAI, Anthropic, GitHub, AWS, etc.)
- JWT tokens, SSH keys, connection strings
- High-entropy base64 detection
- Secrets replaced with `[REDACTED-TYPE]` placeholders

## Performance

| Scenario | Gemini | Chunked (Sonnet) |
|----------|--------|------------------|
| Light day (<100 msgs) | 30-60 sec | 30-60 sec |
| Normal day (100-500 msgs) | 30-60 sec | 1-2 min |
| Heavy day (500+ msgs) | 1-2 min | 5-10 min |
| Very heavy day (1000+ msgs) | 2-3 min | 10-15 min |

**Gemini processes all days in roughly the same time** since it doesn't need chunking.

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

### Very Large Days Timing Out

Use Gemini: `--model gemini` handles days that would require excessive chunking with Sonnet.

### Gemini SIGKILL / Resource Failures on Raspberry Pi

If Gemini consistently fails with SIGKILL or timeout errors (common on Pi 5 with limited RAM):

**Fallback to Kimi:**
```bash
python memory_sync.py backfill --date YYYY-MM-DD --summarize --model kimi --preserve
```

**Why this works:**
- Kimi uses less memory than Gemini's 1M context window
- Chunking still happens automatically for heavy days
- Slightly slower but more reliable on resource-constrained hardware

**To make Kimi the default** (if Gemini consistently fails):
```bash
# Edit memory_sync.py line 64:
DEFAULT_SUMMARIZE_MODEL = "kimi"  # Instead of "gemini"
```

Or create a dedicated Kimi agent:
```bash
openclaw agents add memory-sync-kimi --model moonshot/kimi-k2.5 --workspace ~/.openclaw/workspace --non-interactive
```

**Note:** Gemini is still preferred for very heavy days (>500 messages) when hardware permits—it's faster due to no chunking needed.
