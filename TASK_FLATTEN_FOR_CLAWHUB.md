# Task: Flatten memory-sync for ClawHub Submission

**Goal:** Prepare the memory-sync skill for ClawHub submission by simplifying to a minimal, single-file structure while preserving all functionality.

## Current Structure (Too Complex)
```
memory-sync/
├── SKILL.md
├── README.md
├── pyproject.toml
├── docs/
│   ├── INCREMENTAL_BACKFILL.md
│   ├── SECRET_PATTERNS.md
│   └── SECURITY_GUIDE.md
├── src/memory_sync/
│   ├── __init__.py
│   ├── cli.py (18k)
│   ├── parser.py (8k)
│   ├── compare.py (6k)
│   ├── backfill.py (15k)
│   ├── transitions.py (6k)
│   ├── sanitize.py (16k)
│   ├── sessions.py (5k)
│   ├── models.py (5k)
│   ├── summarize.py (11k)
│   └── validate.py (7k)
└── tests/
```

## Target Structure (ClawHub Ready)
```
memory-sync/
├── SKILL.md                    # Required - frontmatter + usage
├── scripts/
│   └── memory_sync.py          # Single-file CLI (~500 lines)
└── references/
    └── SECRET_PATTERNS.md      # Optional - detailed patterns
```

**No pyproject.toml needed** - this is a simple script skill, not a package.

## Requirements

### 1. Single-File CLI (`scripts/memory_sync.py`)
Merge these into one file:
- CLI argument parsing (from `cli.py`)
- JSONL parsing (from `parser.py`)
- Session discovery (from `sessions.py`)
- Gap detection (from `compare.py`)
- Backfill generation (from `backfill.py`)
- Model transitions (from `transitions.py`)
- Secret sanitization (from `sanitize.py`)
- LLM summarization (from `summarize.py`)

**Keep these functions:**
- `compare()` - Find gaps between logs and memory
- `backfill()` - Generate memory files (with --today, --since, --all flags)
- `transitions()` - List model switches
- `summarize()` - LLM narrative generation

**Remove:**
- Class-based structure (use functions)
- Separate modules (merge into one file)
- `validate()` function (not critical for v1)
- Complex data models (use simple dataclasses or dicts)

### 2. Simplify Dependencies
**Current:**
```toml
dependencies = [
    "click>=8.0",
    "anthropic>=0.40.0",
]
```

**Target:**
No `pyproject.toml` needed. Just document dependencies in SKILL.md:

**Required:** `click` (for CLI)
**Optional:** `anthropic` (only for `--summarize` flag)

**Runtime check pattern:**
```python
def generate_summary_with_llm(text: str) -> str:
    """Generate LLM summary, gracefully handle if anthropic not installed."""
    try:
        import anthropic
        # Use LLM for narrative summary
        return call_anthropic(text)
    except ImportError:
        return "(LLM summarization requires: pip install anthropic)"
```

This makes anthropic truly optional - basic functionality works without it.

### 3. Update SKILL.md
**Keep:**
- YAML frontmatter (name, description)
- Quick start section
- Commands reference
- Installation instructions

**Remove:**
- Detailed architecture docs
- Security guide (move to references/)
- Incremental backfill doc (move to references/)

### 4. Handle Timezone Bug
**Fix in parser:**
```python
# Current (UTC):
return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)

# Target (local):
return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone()
```

### 5. Fix Sparse Threshold
**In compare logic:**
```python
# Current:
MIN_BYTES_PER_MESSAGE = 10

# Target:
MIN_BYTES_PER_MESSAGE = 5  # Simple extraction is ~7-8 bytes/msg
```

### 6. Add --today Flag
**New CLI flag:**
```python
@click.option("--today", is_flag=True, help="Backfill only today's date")
```

When used, set `target_date = datetime.now().date()`

## File Contents

### `scripts/memory_sync.py` (Target Structure)
```python
#!/usr/bin/env python3
"""Memory Sync - Single-file CLI for OpenClaw session log analysis."""

import os
import re
import json
import click
from pathlib import Path
from datetime import datetime, date, timezone
from dataclasses import dataclass
from typing import Optional, Iterator

# === CONFIGURATION ===
DEFAULT_SESSIONS_DIR = Path.home() / '.openclaw' / 'agents' / 'main' / 'sessions'
DEFAULT_MEMORY_DIR = Path.home() / '.openclaw' / 'workspace' / 'memory'
MIN_BYTES_PER_MESSAGE = 5

# === DATA MODELS ===
@dataclass
class Message:
    timestamp: datetime
    role: str
    content: str
    model: Optional[str] = None

@dataclass  
class DayActivity:
    date: date
    message_count: int
    models: set

# === SECRET SANITIZATION ===
SECRET_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{48}', '[REDACTED-OPENAI-KEY]'),
    (r'ak-[a-zA-Z0-9]{20,}', '[REDACTED-COMPOSIO-KEY]'),
    # ... add other patterns from existing sanitize.py
]

def sanitize_content(text: str) -> str:
    for pattern, replacement in SECRET_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text

# === PARSER ===
def parse_timestamp(record: dict) -> Optional[datetime]:
    """Parse timestamp from record, convert to local timezone."""
    ts = record.get('timestamp') or record.get('message', {}).get('timestamp')
    if isinstance(ts, (int, float)):
        # Convert UTC to local
        return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).astimezone()
    return None

def get_messages(session_file: Path) -> Iterator[Message]:
    """Yield messages from a session file."""
    with open(session_file) as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get('type') != 'message':
                    continue
                ts = parse_timestamp(record)
                if not ts:
                    continue
                msg = record.get('message', {})
                yield Message(
                    timestamp=ts,
                    role=msg.get('role', 'unknown'),
                    content=sanitize_content(str(msg.get('content', ''))[:500]),
                    model=msg.get('model')
                )
            except json.JSONDecodeError:
                continue

# === SESSION DISCOVERY ===
def collect_daily_activity(sessions_dir: Path) -> dict[date, DayActivity]:
    """Collect message counts per day from all session files."""
    daily = {}
    for session_file in sessions_dir.glob('*.jsonl'):
        if session_file.suffix == '.lock':
            continue
        for msg in get_messages(session_file):
            day = msg.timestamp.date()
            if day not in daily:
                daily[day] = DayActivity(date=day, message_count=0, models=set())
            daily[day].message_count += 1
            if msg.model:
                daily[day].models.add(msg.model)
    return daily

# === COMPARE ===
def find_gaps(sessions_dir: Path, memory_dir: Path) -> dict:
    """Find days with missing or sparse memory files."""
    daily_activity = collect_daily_activity(sessions_dir)
    missing = []
    sparse = []
    covered = 0
    
    for day, activity in sorted(daily_activity.items()):
        memory_file = memory_dir / f"{day}.md"
        if not memory_file.exists():
            missing.append({'date': day, 'messages': activity.message_count})
        else:
            size = memory_file.stat().st_size
            bytes_per_msg = size / activity.message_count if activity.message_count > 0 else 0
            if bytes_per_msg < MIN_BYTES_PER_MESSAGE:
                sparse.append({
                    'date': day, 
                    'messages': activity.message_count,
                    'bytes': size,
                    'bytes_per_msg': bytes_per_msg
                })
            else:
                covered += 1
    
    total = len(daily_activity)
    return {
        'missing': missing,
        'sparse': sparse,
        'coverage': (covered / total * 100) if total else 100
    }

# === LLM SUMMARIZATION (Optional) ===
def generate_llm_summary(messages: list) -> str:
    """Generate narrative summary using LLM. Gracefully handles missing anthropic."""
    try:
        import anthropic
        client = anthropic.Anthropic()
        
        # Build prompt from messages
        content = "\n".join([f"{m.role}: {m.content[:200]}" for m in messages[:50]])
        
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": f"Summarize this day's OpenClaw session activity:\n\n{content}"
            }]
        )
        return response.content[0].text
    except ImportError:
        return "(LLM summarization requires: pip install anthropic)"
    except Exception as e:
        return f"(Summary generation failed: {e})"

# === BACKFILL ===
def generate_daily_memory(day: date, sessions_dir: Path, output_path: Path, 
                         summarize: bool = False) -> None:
    """Generate memory file for a single day."""
    # Collect all messages for this day
    messages = []
    for session_file in sessions_dir.glob('*.jsonl'):
        for msg in get_messages(session_file):
            if msg.timestamp.date() == day:
                messages.append(msg)
    
    messages.sort(key=lambda m: m.timestamp)
    
    # Generate content
    lines = [
        f"# {day} ({day.strftime('%A')})",
        "",
        f"*Auto-generated from {len(messages)} session messages*",
        "",
        "## Topics Covered",
        "- (topics extracted from content)",
        "",
        "## Key Exchanges",
    ]
    
    for i, msg in enumerate(messages[:20]):  # Limit to first 20
        time_str = msg.timestamp.strftime('%H:%M')
        content_preview = msg.content[:100].replace('\n', ' ')
        lines.append(f"- [{time_str}] ({msg.role}): {content_preview}...")
    
    if summarize and len(messages) > 0:
        lines.extend(["", "## Summary", generate_llm_summary(messages)])
    
    lines.extend(["", "---", "", "*Review and edit this draft to capture what's actually important.*"])
    
    output_path.write_text('\n'.join(lines))

# === CLI ===
@click.group()
def cli():
    """Memory Sync - OpenClaw session log analysis."""
    pass

@cli.command()
@click.option('--sessions-dir', default=None, help='Path to session logs')
@click.option('--memory-dir', default=None, help='Path to memory files')
def compare(sessions_dir, memory_dir):
    """Find gaps between logs and memory files."""
    sessions_path = Path(sessions_dir) if sessions_dir else DEFAULT_SESSIONS_DIR
    memory_path = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR
    
    gaps = find_gaps(sessions_path, memory_path)
    
    click.echo(f"Coverage: {gaps['coverage']:.1f}%")
    if gaps['missing']:
        click.echo(f"\nMissing: {len(gaps['missing'])} days")
        for g in gaps['missing'][:5]:
            click.echo(f"  {g['date']}: {g['messages']} msgs")
    if gaps['sparse']:
        click.echo(f"\nSparse: {len(gaps['sparse'])} days")

@cli.command()
@click.option('--date', default=None, help='Specific date (YYYY-MM-DD)')
@click.option('--today', is_flag=True, help='Use today\'s date')
@click.option('--since', default=None, help='Backfill from date (YYYY-MM-DD)')
@click.option('--all', 'backfill_all', is_flag=True, help='Backfill all missing')
@click.option('--summarize', is_flag=True, help='Use LLM summarization')
@click.option('--force', is_flag=True, help='Overwrite existing')
@click.option('--sessions-dir', default=None)
@click.option('--memory-dir', default=None)
def backfill(date, today, since, backfill_all, summarize, force, sessions_dir, memory_dir):
    """Generate memory files from session logs."""
    sessions_path = Path(sessions_dir) if sessions_dir else DEFAULT_SESSIONS_DIR
    memory_path = Path(memory_dir) if memory_dir else DEFAULT_MEMORY_DIR
    memory_path.mkdir(parents=True, exist_ok=True)
    
    # Determine target date(s)
    if today:
        target_date = datetime.now().date()
        dates_to_process = [target_date]
    elif date:
        target_date = date.fromisoformat(date)
        dates_to_process = [target_date]
    elif since:
        since_date = date.fromisoformat(since)
        gaps = find_gaps(sessions_path, memory_path)
        dates_to_process = [g['date'] for g in gaps['missing'] if g['date'] >= since_date]
    elif backfill_all:
        gaps = find_gaps(sessions_path, memory_path)
        dates_to_process = [g['date'] for g in gaps['missing']]
    else:
        click.echo("Error: Specify --date, --today, --since, or --all")
        return
    
    for day in dates_to_process:
        output_path = memory_path / f"{day}.md"
        if output_path.exists() and not force:
            click.echo(f"Skipping {day} (exists, use --force to overwrite)")
            continue
        
        generate_daily_memory(day, sessions_path, output_path, summarize=summarize)
        click.echo(f"Created: {output_path}")

@cli.command()
@click.option('--date', default=None)
@click.option('--sessions-dir', default=None)
def transitions(date, sessions_dir):
    """List model transitions."""
    sessions_path = Path(sessions_dir) if sessions_dir else DEFAULT_SESSIONS_DIR
    # TODO: Implement transition extraction
    click.echo("Model transitions: (implementation pending)")

# Entry point
if __name__ == '__main__':
    cli()
```

### `SKILL.md` (Simplified)
```yaml
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

Tool for maintaining agent memory continuity across model switches.

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

# Backfill with LLM narrative (requires anthropic)
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
| `transitions` | List model transitions (pending) |

## Secret Sanitization

All content is automatically sanitized to prevent secret leakage:
- API keys (OpenAI, Anthropic, Composio, etc.)
- Tokens and passwords
- SSH keys and JWTs
- High-entropy base64 strings

See `references/SECRET_PATTERNS.md` for complete pattern list.

## Automated Usage

### Nightly Cron (3am)

```bash
0 3 * * * cd ~/.openclaw/skills/memory-sync && memory-sync backfill --today --summarize
```
```

### `references/SECRET_PATTERNS.md`
Move the detailed secret patterns from SECURITY_GUIDE.md here.

## Deliverables

1. **Flattened `scripts/memory_sync.py`** - Single-file CLI with all core functionality
2. **Simplified `SKILL.md`** - Usage-focused, ~100 lines
3. **Optional `references/SECRET_PATTERNS.md`** - Detailed patterns (if needed)

**No pyproject.toml, no package structure** - just a script + documentation.

## Testing Checklist

- [ ] `python scripts/memory_sync.py compare` works
- [ ] `python scripts/memory_sync.py backfill --today` creates file
- [ ] `python scripts/memory_sync.py backfill --date 2026-02-06` works
- [ ] Secret sanitization works (check for [REDACTED-*] patterns)
- [ ] Timezone handling correct (uses local time, not UTC)
- [ ] Sparse threshold updated (5 bytes/msg)
- [ ] Works WITHOUT anthropic installed (basic functionality)
- [ ] Works WITH anthropic installed (--summarize flag)

## Notes

- Remove all `__pycache__` and `.pyc` files before packaging
- Test in fresh venv: `pip install click` only
- Package with `clawhub publish` when ready
- This is a "script skill" - Codex reads SKILL.md, then executes the script
