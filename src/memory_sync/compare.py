"""Gap detection between logs and memory files."""

from pathlib import Path
from datetime import date, timedelta
from typing import Optional

from .models import MemoryGap, DayActivity
from .sessions import get_date_range, collect_daily_activity


# Thresholds for sparse detection
MIN_FILE_SIZE_BYTES = 1024  # Files under 1KB considered potentially sparse
MIN_BYTES_PER_MESSAGE = 10  # Less than 10 bytes per message is too sparse


def find_gaps(sessions_dir: Path, memory_dir: Path) -> dict:
    """
    Compare session logs against memory files to identify coverage gaps.

    Returns dict with:
    - missing_days: dates with activity but no memory file
    - sparse_days: dates with minimal memory content relative to activity
    - coverage_pct: percentage of active days with adequate memory files
    - total_active_days: count of days with any activity
    - first_date: first date with activity
    - last_date: last date with activity
    """
    # Get date range and activity from sessions
    first_date, last_date = get_date_range(sessions_dir)

    if first_date is None or last_date is None:
        return {
            'missing_days': [],
            'sparse_days': [],
            'coverage_pct': 100.0,
            'total_active_days': 0,
            'first_date': None,
            'last_date': None,
        }

    daily_activity = collect_daily_activity(sessions_dir)

    missing_gaps: list[MemoryGap] = []
    sparse_gaps: list[MemoryGap] = []
    covered_days = 0

    for day, activity in sorted(daily_activity.items()):
        # Skip days with no meaningful activity
        if activity.message_count == 0:
            continue

        memory_file = memory_dir / f"{day}.md"

        if not memory_file.exists():
            missing_gaps.append(MemoryGap(
                date=day,
                gap_type='missing',
                activity=activity,
                memory_file_size=0,
                reason=f"No memory file for {activity.message_count} messages"
            ))
        else:
            file_size = memory_file.stat().st_size
            bytes_per_msg = file_size / activity.message_count if activity.message_count > 0 else 0

            if file_size < MIN_FILE_SIZE_BYTES or bytes_per_msg < MIN_BYTES_PER_MESSAGE:
                sparse_gaps.append(MemoryGap(
                    date=day,
                    gap_type='sparse',
                    activity=activity,
                    memory_file_size=file_size,
                    reason=f"Only {file_size} bytes for {activity.message_count} messages ({bytes_per_msg:.1f} bytes/msg)"
                ))
            else:
                covered_days += 1

    total_active_days = len(daily_activity)
    coverage_pct = (covered_days / total_active_days * 100) if total_active_days > 0 else 100.0

    return {
        'missing_days': missing_gaps,
        'sparse_days': sparse_gaps,
        'coverage_pct': coverage_pct,
        'total_active_days': total_active_days,
        'covered_days': covered_days,
        'first_date': first_date,
        'last_date': last_date,
    }


def get_memory_files(memory_dir: Path) -> list[tuple[date, Path]]:
    """
    Get all memory files in the memory directory.

    Returns list of (date, path) tuples for files matching YYYY-MM-DD.md pattern.
    """
    if not memory_dir.exists():
        return []

    files = []
    for f in memory_dir.glob('*.md'):
        # Try to parse date from filename
        try:
            file_date = date.fromisoformat(f.stem)
            files.append((file_date, f))
        except ValueError:
            # Skip files that don't match date pattern (e.g., MEMORY.md)
            continue

    return sorted(files, key=lambda x: x[0])


def find_orphaned_memory_files(sessions_dir: Path, memory_dir: Path) -> list[tuple[date, Path]]:
    """
    Find memory files that have no corresponding session activity.

    These might be manually created or from deleted sessions.
    """
    daily_activity = collect_daily_activity(sessions_dir)
    memory_files = get_memory_files(memory_dir)

    orphaned = []
    for file_date, file_path in memory_files:
        if file_date not in daily_activity or daily_activity[file_date].message_count == 0:
            orphaned.append((file_date, file_path))

    return orphaned


def format_gap_report(gaps: dict) -> str:
    """
    Format gap detection results as a human-readable report.
    """
    lines = []

    lines.append("Memory Coverage Report")
    lines.append("=" * 50)
    lines.append("")

    if gaps['first_date'] and gaps['last_date']:
        lines.append(f"Date range: {gaps['first_date']} to {gaps['last_date']}")
    lines.append(f"Active days: {gaps['total_active_days']}")
    lines.append(f"Covered days: {gaps.get('covered_days', 0)}")
    lines.append(f"Coverage: {gaps['coverage_pct']:.1f}%")
    lines.append("")

    missing = gaps['missing_days']
    sparse = gaps['sparse_days']

    if missing:
        lines.append(f"Missing Memory Files ({len(missing)} days)")
        lines.append("-" * 40)
        for gap in missing:
            models_str = ', '.join(gap.activity.models_used) if gap.activity.models_used else 'unknown'
            lines.append(f"  {gap.date}: {gap.activity.message_count} msgs ({models_str})")
        lines.append("")

    if sparse:
        lines.append(f"Sparse Memory Files ({len(sparse)} days)")
        lines.append("-" * 40)
        for gap in sparse:
            lines.append(f"  {gap.date}: {gap.reason}")
        lines.append("")

    if not missing and not sparse:
        lines.append("All days have adequate memory coverage!")

    return '\n'.join(lines)
