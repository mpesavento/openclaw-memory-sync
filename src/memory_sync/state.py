"""State tracking for incremental backfill operations."""

import json
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Set


def get_state_file_path() -> Path:
    """Get the path to the state file.
    
    Returns:
        Path to ~/.memory-sync/state.json
    """
    state_dir = Path.home() / '.memory-sync'
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / 'state.json'


def load_state() -> dict:
    """Load state from the state file.
    
    Returns:
        State dictionary with keys:
        - last_run: ISO format timestamp of last run
        - last_successful_date: ISO format date of last processed date
        - total_days_processed: Total count of days processed
        
        Returns empty dict if file doesn't exist.
    """
    state_file = get_state_file_path()
    
    if not state_file.exists():
        return {}
    
    try:
        with state_file.open('r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # If file is corrupted, return empty state
        return {}


def save_state(
    last_run: Optional[datetime] = None,
    last_successful_date: Optional[date] = None,
    total_days_processed: Optional[int] = None
) -> None:
    """Save state to the state file.
    
    Args:
        last_run: Timestamp of the run (defaults to now)
        last_successful_date: Last date successfully processed
        total_days_processed: Total count of days processed
        
    Existing values are preserved if not provided.
    """
    state_file = get_state_file_path()
    
    # Load existing state
    state = load_state()
    
    # Update with new values
    if last_run is not None:
        state['last_run'] = last_run.isoformat()
    elif 'last_run' not in state:
        # Default to now if not provided and doesn't exist
        state['last_run'] = datetime.now().isoformat()
    
    if last_successful_date is not None:
        state['last_successful_date'] = last_successful_date.isoformat()
    
    if total_days_processed is not None:
        state['total_days_processed'] = total_days_processed
    elif 'total_days_processed' not in state:
        state['total_days_processed'] = 0
    
    # Write state
    with state_file.open('w') as f:
        json.dump(state, f, indent=2)


def get_changed_days(sessions_dir: Path, since: datetime) -> Set[date]:
    """Get set of dates with session activity since a given timestamp.
    
    Checks session file modification times and extracts dates from messages.
    
    Args:
        sessions_dir: Path to session JSONL files
        since: Only include files modified after this timestamp
        
    Returns:
        Set of dates that have been modified since the timestamp
    """
    from .parser import get_messages
    from .sessions import find_session_files
    
    changed_days: Set[date] = set()
    since_timestamp = since.timestamp()
    
    for session_file in find_session_files(sessions_dir):
        # Check if file was modified since timestamp
        file_mtime = session_file.stat().st_mtime
        
        if file_mtime > since_timestamp:
            # Extract all dates from messages in this file
            for msg in get_messages(session_file):
                changed_days.add(msg.timestamp.date())
    
    return changed_days


def get_last_run_datetime() -> Optional[datetime]:
    """Get the last run timestamp from state.
    
    Returns:
        datetime object of last run, or None if never run
    """
    state = load_state()
    last_run_str = state.get('last_run')
    
    if not last_run_str:
        return None
    
    try:
        return datetime.fromisoformat(last_run_str)
    except (ValueError, TypeError):
        return None
