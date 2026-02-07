# Incremental Memory Backfill Strategy

**Problem:** `memory-sync backfill --all --summarize` can take 5-10 minutes per day when using LLM summarization. Running this nightly for all historical data is inefficient.

**Solution:** Use incremental backfill strategies to only process new or updated data.

---

## Recommended Approaches

### 1. Nightly Cron (Automated)

Use `--today` to process only the current day:

```bash
# In cron job - runs daily at 3am
0 3 * * * cd ~/projects/openclaw-memory-sync && uv run memory-sync backfill --today --summarize
```

**Benefits:**
- Fast: ~30-60 seconds per run
- Only processes new day's activity
- Minimal API usage (LLM calls)
- Perfect for automation

**Implementation:** Add `--today` flag to CLI that sets target_date to today's date in local timezone.

---

### 2. Manual Catch-Up (On-Demand)

Use `--since` to backfill from a specific date:

```bash
# Backfill everything since Feb 1st
uv run memory-sync backfill --since 2026-02-01 --summarize

# Backfill last 3 days
uv run memory-sync backfill --since $(date -d "3 days ago" +%Y-%m-%d) --summarize
```

**Use cases:**
- Initial setup: Backfill historical data
- Recovery: After model switch or memory loss
- Gap filling: When you notice missing days

---

### 3. Smart Incremental (Advanced)

Track last run timestamp and auto-detect changed days:

```bash
# Store last run timestamp
uv run memory-sync backfill --incremental --summarize
```

**How it works:**
1. Read stored timestamp from `~/.memory-sync/last-run`
2. Check which session files have been modified since then
3. Only process dates with new activity
4. Update timestamp after successful run

**Benefits:**
- Fully automatic
- Handles partial days (if session continues past midnight)
- No manual date calculation needed

---

## CLI Flag Reference

| Flag | Description | Use Case |
|------|-------------|----------|
| `--date 2026-02-06` | Single specific date | One-off backfill |
| `--today` | Current date only | Nightly automation |
| `--since 2026-02-01` | From date to present | Catch-up / recovery |
| `--all` | All missing dates | Initial setup |
| `--incremental` | Since last run | Smart automation |

---

## Implementation Notes

### Timezone Handling

When checking "today", use local timezone (not UTC) to match user's perception of "today":

```python
from datetime import datetime
import pytz

def get_today_local():
    """Get today's date in local timezone."""
    tz = pytz.timezone('America/Los_Angeles')  # Or detect from system
    return datetime.now(tz).date()
```

### Incremental Tracking

Store last successful run in JSON:

```python
# ~/.memory-sync/state.json
{
    "last_run": "2026-02-06T03:00:00-08:00",
    "last_successful_date": "2026-02-06",
    "total_days_processed": 42
}
```

### File Modification Check

For smart incremental, check session file mtimes:

```python
import os
from pathlib import Path

def get_changed_days(sessions_dir: Path, since: datetime) -> list[date]:
    """Get list of dates with session activity since timestamp."""
    changed_days = set()
    
    for session_file in sessions_dir.glob('*.jsonl'):
        if session_file.stat().st_mtime > since.timestamp():
            # Parse file to get dates it contains
            dates_in_file = extract_dates_from_session(session_file)
            changed_days.update(dates_in_file)
    
    return sorted(changed_days)
```

---

## Migration Path

### Current State
Cron job uses `--all`:
```bash
0 3 * * * uv run memory-sync backfill --all --summarize
```

### Target State
1. **Short-term:** Add `--today` flag, update cron
2. **Medium-term:** Add `--since` flag for manual use
3. **Long-term:** Implement `--incremental` with state tracking

---

## Performance Comparison

| Approach | Time (per day) | API Calls | Use Case |
|----------|---------------|-----------|----------|
| `--all` | 5-10 min × N days | High | Initial setup only |
| `--since` | 5-10 min × N days | High | Recovery/catch-up |
| `--today` | 30-60 sec | 1 | Nightly automation |
| `--incremental` | 30-60 sec × changed days | Low | Smart automation |

---

## Example Cron Setup

```bash
# Edit crontab
crontab -e

# Add nightly job
0 3 * * * cd ~/projects/openclaw-memory-sync && uv run memory-sync backfill --today --summarize >> ~/.memory-sync/cron.log 2>&1
```

---

## Related

- See `SECURITY_GUIDE.md` for sanitization requirements
- See `SKILL.md` for full CLI reference
- See `docs/ARCHITECTURE.md` for data flow details
