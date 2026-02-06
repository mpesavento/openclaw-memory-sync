"""Gap detection between logs and memory files."""

from pathlib import Path


def find_gaps(sessions_dir: Path, memory_dir: Path) -> dict:
    """
    Compare session logs against memory files.
    
    Returns dict with:
    - missing_days: dates with activity but no memory file
    - sparse_days: dates with minimal memory content
    - transitions_without_update: model switches without memory writes
    """
    # TODO: Implement
    pass
