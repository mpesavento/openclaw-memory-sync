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
memory-sync compare

# Backfill a specific date
memory-sync backfill 2026-01-15

# Backfill all missing dates
memory-sync backfill --all

# Use LLM to generate narrative summaries (requires ANTHROPIC_API_KEY)
memory-sync backfill --all --summarize

# Regenerate existing files while preserving hand-written content
memory-sync backfill --all --preserve --force
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
- Session logs: `~/.cursor/OpenClaw/sessions/*.jsonl`
- Memory files: `~/.cursor/OpenClaw/memory/*.md`

Override with `--sessions-dir` and `--memory-dir` options.

## Commands

### `compare`

Compare session logs to memory files and report gaps.

```bash
memory-sync compare
memory-sync compare --sessions-dir /path/to/sessions --memory-dir /path/to/memory
```

### `backfill`

Generate missing daily memory files.

```bash
# Single date
memory-sync backfill 2026-01-15

# All missing dates (dry run)
memory-sync backfill --all --dry-run

# All missing dates (simple extraction)
memory-sync backfill --all

# All missing dates (LLM summarization)
memory-sync backfill --all --summarize

# Overwrite existing files
memory-sync backfill --all --force

# Preserve hand-written content when overwriting
memory-sync backfill --all --preserve --force
```

Options:
- `--dry-run`: Show what would be created without creating files
- `--force`: Overwrite existing files
- `--preserve`: Keep hand-written content from existing files
- `--summarize`: Use LLM for narrative summaries (requires `anthropic` package)
- `--model`: Choose LLM model (default: `claude-sonnet-4-20250514`)

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
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=memory_sync --cov-report=html
```

## Configuration

Set these environment variables:
- `ANTHROPIC_API_KEY`: Required for `--summarize` mode

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]
