# OpenClaw Memory Sync

Tool for maintaining agent memory continuity across model switches.

## The Problem

OpenClaw agents maintain continuity through memory files (`memory/YYYY-MM-DD.md`, `MEMORY.md`). But there's a critical failure mode:

**Model switches create memory isolation.** When OpenClaw switches between models (Opus → Sonnet → GPT), each model instance operates independently. If one instance doesn't write to memory files, that context is lost to future instances.

In practice, this means:
- Daily memory files never get created (or are sparse)
- Important conversations vanish between model switches
- The agent "forgets" decisions, context, and relationships
- MEMORY.md drifts out of sync or stays empty

We discovered this when an entire day (330 messages) was missing, and another day had only 827 bytes for 598 messages—missing an important thread entirely.

## The Solution

**The JSONL session logs are the ground truth.** OpenClaw writes every message, tool call, and model transition to `~/.openclaw/agents/main/sessions/*.jsonl`. These persist across ALL model switches.

This tool:
1. Parses the native JSONL session logs
2. Reconstructs daily memory files from the actual conversation history
3. Optionally uses LLM summarization for coherent narratives
4. Runs automated backfill to prevent future gaps
5. Sanitizes secrets before writing anything to disk

**Result:** Memory continuity survives model switches because it's reconstructed from persistent logs, not dependent on any single model instance maintaining state.

## Use Cases

- **Memory gaps after model switches** - Reconstruct memory that was lost during model transitions
- **Verify memory coverage** - Identify days with missing or sparse memory files
- **Automated daily sync** - Run via cron to keep memory files current
- **Backfill historical data** - Generate memory files for past sessions
- **Recovery after failures** - The logs are always there; memory can always be rebuilt

## Project Structure

```
openclaw-memory-sync/
├── scripts/
│   └── memory_sync.py      # Single-file CLI tool (all logic here)
├── tests/
│   ├── test_memory_sync.py # Consolidated test suite
│   ├── conftest.py         # Pytest fixtures
│   └── fixtures/           # Test data files
├── references/
│   └── SECRET_PATTERNS.md  # Documentation of secret detection patterns
├── SKILL.md                # OpenClaw skill definition (agent instructions)
└── README.md               # This file
```

## Installation

Requires Python 3.11+ and `click`:

```bash
pip install click

# Optional: for direct API summarization backends
pip install openai
```

### As an OpenClaw Skill

```bash
cd ~/.openclaw/skills
git clone git@github.com:mpesavento/openclaw-memory-sync.git memory-sync

# Create an alias for convenience
alias memory-sync="python ~/.openclaw/skills/memory-sync/scripts/memory_sync.py"
```

## Quick Start

```bash
# Check for gaps in memory coverage
memory-sync compare

# Backfill today's memory (simple extraction, fast)
memory-sync backfill --today

# Backfill with LLM narrative summary (recommended for quality)
memory-sync backfill --today --summarize --preserve

# Backfill all missing dates
memory-sync backfill --all
```

## Commands

| Command | Description |
|---------|-------------|
| `compare` | Find gaps between session logs and memory files |
| `backfill` | Generate missing daily memory files |
| `summarize` | Generate LLM summary for a single day |
| `extract` | Extract conversations matching criteria |
| `transitions` | List model transitions |
| `validate` | Check memory files for consistency issues |
| `stats` | Show coverage statistics |

## Summarization Modes

**Simple Extraction (without `--summarize`):**
- Fast, no LLM calls
- Extracts topics, key exchanges, and decisions via pattern matching
- Best for initial backfills or systems without LLM access

**LLM Summarization (with `--summarize`):**
- Generates coherent narrative summaries
- Uses OpenClaw's native model by default (no API key needed)
- Alternative backends: `--summarize-backend anthropic` or `--summarize-backend openai`

**Recommended for daily use:**
```bash
memory-sync backfill --today --summarize --preserve
```

## Secret Sanitization

All content is automatically sanitized before writing to memory files. Detected secrets are replaced with `[REDACTED-TYPE]` placeholders.

Supported patterns include:
- API keys (OpenAI, Anthropic, GitHub, AWS, Stripe, etc.)
- Tokens (JWT, OAuth, session tokens)
- Connection strings with credentials
- SSH keys and certificates
- Environment variable references

See [references/SECRET_PATTERNS.md](references/SECRET_PATTERNS.md) for the complete list of 30+ detection patterns.

## Configuration

**Default paths:**
- Session logs: `~/.openclaw/agents/main/sessions/*.jsonl`
- Memory files: `~/.openclaw/workspace/memory/`

**Override with CLI flags:**
```bash
memory-sync compare --sessions-dir /path/to/sessions --memory-dir /path/to/memory
```

## Automated Usage

### Nightly Cron

```bash
# Run at 3am daily
0 3 * * * cd ~/.openclaw/skills/memory-sync && python scripts/memory_sync.py backfill --today --summarize --preserve >> ~/.memory-sync/cron.log 2>&1
```

### Incremental Mode

Only process days that have changed since the last run:

```bash
memory-sync backfill --incremental --summarize --preserve
```

State is tracked in `~/.memory-sync/state.json`.

## Running Tests

```bash
pip install pytest

# Run all tests
pytest tests/

# Run specific test class
pytest tests/test_memory_sync.py::TestSummarizeWithOpenclaw -v
```

## Documentation

- **[SKILL.md](SKILL.md)** - OpenClaw skill definition with detailed usage instructions for agents
- **[references/SECRET_PATTERNS.md](references/SECRET_PATTERNS.md)** - Complete documentation of secret detection patterns

## License

MIT
