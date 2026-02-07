# memory-sync

A tool for consolidating OpenClaw session logs into complete daily memory files. Solves the critical issue of partial memories caused by model switching - when you change models, OpenClaw creates new sessions that can overwrite existing memories, losing earlier context. memory-sync backfills from all session logs to ensure nothing is lost.

## Use Case

### The Problem: Partial Memories from Model Switching

**Critical OpenClaw Issue**: When you switch models during your work session, OpenClaw creates a new session file. This causes the new model to potentially overwrite existing memories for that date, leading to **partial or incomplete memory files**. You lose context from earlier conversations when the model changed.

This is a critical failure of the OpenClaw memory system - your AI assistant literally forgets what happened earlier in the day when you switch models.

### The Solution: Backfill from Session Logs

**memory-sync** solves this by:
1. **Consolidating** all session logs for a date (across model switches) into complete memory files
2. **Extracting** key information from session logs (messages, decisions, model transitions)
3. **Organizing** them into structured daily memory files
4. **Preserving** your hand-written notes when regenerating files
5. **Summarizing** conversations using LLMs (optional) for narrative summaries

This creates a complete, accurate personal knowledge base from your AI interactions, regardless of how many times you switched models.

## Installation

### As an OpenClaw Skill (Recommended)

```bash
# Clone to OpenClaw skills directory (rename to match skill name)
cd ~/.openclaw/skills
git clone git@github.com:mpesavento/openclaw-memory-sync.git memory-sync

# OpenClaw auto-discovers it. Verify with:
openclaw skills list | grep memory-sync
```

Then use via `uv run` from the skill directory, or read the SKILL.md for usage.

### Standalone with uv

```bash
# Clone the repo
git clone https://github.com/mpesavento/openclaw-memory-sync.git
cd openclaw-memory-sync

# Run directly (uv handles dependencies automatically)
uv run memory-sync compare
uv run memory-sync backfill --all

# Or install as a global tool
uv tool install .
memory-sync compare  # now available globally
```

### With pip

```bash
# Basic installation
pip install -e .

# With development dependencies
pip install -e ".[dev]"

# With LLM summarization support
pip install -e ".[summarize]"

# Everything
pip install -e ".[all]"
```

## Quick Start

```bash
# Compare session logs to memory files and find gaps
uv run memory-sync compare

# Nightly automation - backfill today only (fast: 30-60 seconds)
uv run memory-sync backfill --today --summarize

# Backfill a specific date
uv run memory-sync backfill --date 2026-01-15

# Catch-up after a gap - backfill from a date to present
uv run memory-sync backfill --since 2026-01-28 --summarize

# Smart automation - only process dates changed since last run
uv run memory-sync backfill --incremental --summarize

# Initial setup - backfill all missing dates
uv run memory-sync backfill --all --summarize

# Regenerate existing file while preserving hand-written notes
uv run memory-sync backfill --date 2026-01-15 --force --preserve --summarize
```

## Features

### 🔒 Automatic Secret Sanitization

All content is automatically scanned and sanitized before:
- Being sent to LLM APIs
- Being written to memory files
- Being displayed in CLI output

**Detects and redacts**:
- 30+ explicit API key patterns (OpenAI, Anthropic, GitHub, AWS, Stripe, Discord, Slack, etc.)
- JWT tokens, SSH keys, database connection strings
- Password assignments, bearer tokens, environment variables
- High-entropy secrets and generic token patterns

Secrets are replaced with `[REDACTED-TYPE]` placeholders. Multiple validation layers ensure no secrets leak through.

See `docs/SECRET_PATTERNS.md` for complete pattern documentation.

### Simple Extraction Mode (Default)

Generates structured memory files with:
- **Topics Covered**: Key topics extracted from conversation
- **Session Flow**: Overview of tasks, questions, and context
- **Key Decisions**: Important decisions or insights
- **Technical Details**: Commands, files, errors (sanitized)
- **Model Transitions**: When you switched between AI models
- **Message Compaction**: Statistics on message distribution

### LLM Summarization Mode (`--summarize`)

Uses Claude to generate:
- Natural narrative summaries of your day's conversations
- Context-aware topic grouping
- Intelligent insights extraction

**Requires `ANTHROPIC_API_KEY` environment variable:**
```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
```

**Security**: All conversations are sanitized before being sent to the LLM, and outputs are validated.

### Incremental Backfill Strategies ⭐

**Problem**: Running `--all --summarize` on historical data takes 5-10 minutes per day. For nightly automation, this is inefficient.

**Solution**: Use incremental backfill modes to only process new or changed data:

#### `--today` (Recommended for Nightly Automation)
Process only the current day. **Fast** (~30-60 seconds) and perfect for cron jobs:
```bash
0 3 * * * cd ~/.openclaw/skills/memory-sync && uv run memory-sync backfill --today --summarize
```

#### `--since YYYY-MM-DD` (Manual Catch-Up)
Backfill from a specific date to present. Use after gaps or model switches:
```bash
# Backfill last week
uv run memory-sync backfill --since 2026-01-28 --summarize
```

#### `--incremental` (Smart Automation)
Tracks last successful run and only processes dates with file changes. Requires initial `--all` run:
```bash
# Initial setup
uv run memory-sync backfill --all --summarize

# Then use incremental mode
uv run memory-sync backfill --incremental --summarize
```

State is tracked in `~/.memory-sync/state.json`. See `docs/INCREMENTAL_BACKFILL.md` for detailed strategies.

### Hand-Written Content Preservation (`--preserve`)

When regenerating memory files:
- **Simple mode**: Appends hand-written content (after footer marker)
- **LLM mode** (`--summarize`): Passes existing content to LLM with explicit instructions to:
  - Preserve temporal order and chronological structure
  - Respect existing style (narrative vs. bullets)
  - Merge by theme rather than duplicating sections
  - Retain hand-written insights and reflections
  - Update rather than replace the existing baseline

This lets you:
1. Generate initial memory file from logs
2. Add your own notes and context
3. Regenerate later without losing your edits

## Directory Structure

By default, memory-sync looks for:
- **Session logs**: `~/.openclaw/agents/main/sessions/*.jsonl`
- **Memory files**: `~/.openclaw/workspace/memory/*.md`

Override with `--sessions-dir` and `--memory-dir` options.

## Commands

### `compare`

Compare session logs to memory files and report gaps.

```bash
uv run memory-sync compare
uv run memory-sync compare --sessions-dir /path/to/sessions --memory-dir /path/to/memory
```

### `backfill`

Generate missing daily memory files.

**Date Selection (choose exactly one):**
- `--date YYYY-MM-DD` - Single specific date
- `--today` - Current date only (for nightly automation)
- `--since YYYY-MM-DD` - From date to present (for catch-up)
- `--all` - All missing dates (for initial setup)
- `--incremental` - Only dates changed since last run

**Examples:**

```bash
# NIGHTLY AUTOMATION (recommended)
uv run memory-sync backfill --today --summarize

# CATCH-UP after a gap
uv run memory-sync backfill --since 2026-01-28 --summarize

# SMART AUTOMATION (requires prior --all run)
uv run memory-sync backfill --incremental --summarize

# INITIAL SETUP
uv run memory-sync backfill --all --summarize

# SINGLE DATE
uv run memory-sync backfill --date 2026-01-15 --summarize

# DRY RUN - preview only
uv run memory-sync backfill --today --dry-run
```

**Regenerating Existing Files (--force --preserve):**

Use `--force --preserve` when you need to regenerate files that already exist while keeping your hand-written notes:

```bash
# Regenerate a single date, preserve hand-written content
uv run memory-sync backfill --date 2026-01-15 --force --preserve --summarize

# Regenerate today's file after adding more session activity
uv run memory-sync backfill --today --force --preserve --summarize

# Regenerate multiple days, preserving all hand-written sections
uv run memory-sync backfill --since 2026-01-28 --force --preserve --summarize

# Upgrade all files from simple extraction to LLM summaries
uv run memory-sync backfill --all --force --preserve --summarize
```

**Common regeneration scenarios:**
- Added hand-written notes and want to update with new session data
- Switching from simple extraction to LLM summarization
- Testing different LLM models while keeping your edits
- Session logs were updated after initial generation
- Model improved and you want better summaries

**Options:**
- `--dry-run`: Show what would be created without creating files
- `--force`: Overwrite existing files (required for regeneration)
- `--preserve`: Keep hand-written content from existing files
- `--summarize`: Use LLM for narrative summaries (requires `anthropic` package)
- `--model`: Choose LLM model (default: `claude-sonnet-4-20250514`)
- `--sessions-dir`: Override default sessions directory
- `--memory-dir`: Override default memory directory

### `stats`

Show coverage statistics.

```bash
uv run memory-sync stats
```

### `summarize`

Generate an LLM summary for a single day (requires ANTHROPIC_API_KEY).

```bash
uv run memory-sync summarize --date 2026-01-15
uv run memory-sync summarize --date 2026-01-15 --output summary.md
```

Options:
- `--date`: Date to summarize (required)
- `--model`: Model to use (default: `claude-sonnet-4-20250514`)
- `--output`: Write to file instead of stdout

### `extract`

Extract conversations matching criteria.

```bash
uv run memory-sync extract --date 2026-01-15
uv run memory-sync extract --query "memory sync"
uv run memory-sync extract --model claude-sonnet-4 --format json
```

Options:
- `--date`: Filter by specific date
- `--query`: Search term in messages (case-insensitive)
- `--model`: Filter by model used
- `--format`: Output format (`md`, `json`, `text`; default: `md`)

### `transitions`

List model transitions with context.

```bash
uv run memory-sync transitions
uv run memory-sync transitions --date 2026-01-15
uv run memory-sync transitions --output transitions.json
```

### `validate`

Check memory files for consistency issues.

```bash
uv run memory-sync validate
```

## Example Memory File

```markdown
# 2026-01-15 (Wednesday)

*Auto-generated from 42 session messages*

## Topics Covered
- Python packaging and dependency management
- Testing strategies with pytest
- Git workflow and commit conventions

## Session Flow
Started with questions about pytest fixtures, then moved to refactoring
the backfill logic to support content preservation...

## Key Decisions
- Use `extract_preserved_content()` to separate auto-generated from hand-written sections
- Pass existing content to LLM for intelligent merging

---

*Review and edit this draft to capture what's actually important.*

## My Notes

(This section is preserved when regenerating with --preserve)
```

## Development

```bash
# Install with dev dependencies
uv sync --extra dev

# Run all tests
make test
# or: uv run pytest

# Run security tests only
make test-security

# Run integration tests
make test-integration

# Run with coverage
make test-cov
# or: uv run pytest --cov=memory_sync --cov-report=html
```

See `Makefile` for all available test targets.

## Automation Examples

### Nightly Cron Job (Recommended)

Process only today's date - fast and efficient:

```bash
# Edit crontab
crontab -e

# Add this line (runs daily at 3am)
0 3 * * * cd ~/.openclaw/skills/memory-sync && uv run memory-sync backfill --today --summarize >> ~/.memory-sync/cron.log 2>&1
```

### Smart Incremental Mode

Automatically detects changes since last run:

```bash
# First time: backfill everything
cd ~/.openclaw/skills/memory-sync
uv run memory-sync backfill --all --summarize

# Set up nightly incremental
0 3 * * * cd ~/.openclaw/skills/memory-sync && uv run memory-sync backfill --incremental --summarize >> ~/.memory-sync/cron.log 2>&1
```

### Performance Comparison

| Mode | Time per Day | API Calls | Best For |
|------|-------------|-----------|----------|
| `--all` | 5-10 min × N days | High | Initial setup only |
| `--since` | 5-10 min × N days | High | Recovery/catch-up |
| `--today` | 30-60 sec | 1 | **Nightly automation** ⭐ |
| `--incremental` | 30-60 sec × changed | Low | Smart automation |

See `docs/INCREMENTAL_BACKFILL.md` for detailed strategies.

## Configuration

### Environment Variables

**ANTHROPIC_API_KEY** - Required for `--summarize` mode:
```bash
# Set temporarily for current session
export ANTHROPIC_API_KEY=sk-ant-api03-...

# Or add to shell profile for persistence
echo 'export ANTHROPIC_API_KEY=sk-ant-api03-...' >> ~/.bashrc
source ~/.bashrc

# Verify it's set
echo $ANTHROPIC_API_KEY
```

**Note**: Simple extraction mode (without `--summarize`) works without an API key.

### State Files

State tracking (for `--incremental` mode):
- `~/.memory-sync/state.json`: Tracks last run timestamp and processing history

## License

MIT

## Contributing

PRs welcome! Please run tests before submitting.
