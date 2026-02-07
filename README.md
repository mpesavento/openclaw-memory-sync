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

# Backfill a specific date
uv run memory-sync backfill --date 2026-01-15

# Backfill all missing dates
uv run memory-sync backfill --all

# Use LLM to generate narrative summaries (requires ANTHROPIC_API_KEY)
uv run memory-sync backfill --all --summarize

# Regenerate existing files while preserving hand-written content
uv run memory-sync backfill --all --preserve --force
```

## Features

### Simple Extraction Mode (Default)

Generates structured memory files with:
- **Topics Covered**: Key topics extracted from conversation
- **Session Flow**: Overview of tasks, questions, and context
- **Key Decisions**: Important decisions or insights
- **Technical Details**: Commands, files, errors
- **Model Transitions**: When you switched between AI models
- **Message Compaction**: Statistics on message distribution

### LLM Summarization Mode (`--summarize`)

Uses Claude to generate:
- Natural narrative summaries of your day's conversations
- Context-aware topic grouping
- Intelligent insights extraction

Requires `ANTHROPIC_API_KEY` environment variable.

### Hand-Written Content Preservation (`--preserve`)

When regenerating memory files:
- Detects hand-written content (anything after the auto-generated footer)
- Keeps your manual notes, insights, and edits
- Updates only the auto-generated sections

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

```bash
# Single date
uv run memory-sync backfill --date 2026-01-15

# All missing dates (dry run)
uv run memory-sync backfill --all --dry-run

# All missing dates (simple extraction)
uv run memory-sync backfill --all

# All missing dates (LLM summarization)
uv run memory-sync backfill --all --summarize

# Overwrite existing files
uv run memory-sync backfill --all --force

# Preserve hand-written content when overwriting
uv run memory-sync backfill --all --preserve --force
```

Options:
- `--dry-run`: Show what would be created without creating files
- `--force`: Overwrite existing files
- `--preserve`: Keep hand-written content from existing files
- `--summarize`: Use LLM for narrative summaries (requires `anthropic` package)
- `--model`: Choose LLM model (default: `claude-sonnet-4-20250514`)

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

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=memory_sync --cov-report=html
```

## Configuration

Set these environment variables:
- `ANTHROPIC_API_KEY`: Required for `--summarize` mode

## License

MIT

## Contributing

PRs welcome! Please run tests before submitting.
