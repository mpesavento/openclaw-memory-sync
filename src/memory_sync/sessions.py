"""Session discovery and activity collection."""

from pathlib import Path
from typing import Optional
from datetime import date
from collections import defaultdict

from .models import DayActivity, ModelTransition
from .parser import get_messages, get_model_transitions, get_session_metadata


def find_session_files(sessions_dir: Path) -> list[Path]:
    """
    Find all session JSONL files in a directory.

    Excludes .jsonl.lock files (active sessions).
    Returns files sorted by modification time (oldest first).
    """
    if not sessions_dir.exists():
        return []

    files = []
    for f in sessions_dir.glob('*.jsonl'):
        # Skip lock files
        if f.suffix == '.lock' or f.name.endswith('.jsonl.lock'):
            continue
        files.append(f)

    # Sort by modification time (oldest first)
    files.sort(key=lambda p: p.stat().st_mtime)
    return files


def get_date_range(sessions_dir: Path) -> tuple[Optional[date], Optional[date]]:
    """
    Get the date range of activity across all session files.

    Returns (first_date, last_date) tuple. Returns (None, None) if no messages found.
    """
    first_date: Optional[date] = None
    last_date: Optional[date] = None

    for session_file in find_session_files(sessions_dir):
        for msg in get_messages(session_file):
            msg_date = msg.timestamp.date()

            if first_date is None or msg_date < first_date:
                first_date = msg_date
            if last_date is None or msg_date > last_date:
                last_date = msg_date

    return first_date, last_date


def collect_daily_activity(sessions_dir: Path) -> dict[date, DayActivity]:
    """
    Collect activity summary for each day across all sessions.

    Groups messages by date and tracks models used, transitions, and session IDs.
    """
    # Temporary storage for aggregation
    daily_data: dict[date, dict] = defaultdict(lambda: {
        'message_count': 0,
        'user_messages': 0,
        'assistant_messages': 0,
        'tool_result_messages': 0,
        'models': set(),
        'transitions': [],
        'session_ids': set(),
    })

    session_files = find_session_files(sessions_dir)

    for session_file in session_files:
        # Get session ID
        session_meta = get_session_metadata(session_file)
        session_id = session_meta.get('id', session_file.stem) if session_meta else session_file.stem

        # Collect messages
        for msg in get_messages(session_file):
            msg_date = msg.timestamp.date()
            data = daily_data[msg_date]

            data['message_count'] += 1
            data['session_ids'].add(session_id)

            if msg.role == 'user':
                data['user_messages'] += 1
            elif msg.role == 'assistant':
                data['assistant_messages'] += 1
                if msg.model:
                    data['models'].add(msg.model)
            elif msg.role == 'toolResult':
                data['tool_result_messages'] += 1

        # Collect transitions
        for transition in get_model_transitions(session_file):
            trans_date = transition.timestamp.date()
            daily_data[trans_date]['transitions'].append(transition)

    # Convert to DayActivity objects
    result: dict[date, DayActivity] = {}
    for day, data in daily_data.items():
        result[day] = DayActivity(
            date=day,
            message_count=data['message_count'],
            user_messages=data['user_messages'],
            assistant_messages=data['assistant_messages'],
            tool_result_messages=data['tool_result_messages'],
            models_used=sorted(data['models']),
            transitions=data['transitions'],
            session_ids=sorted(data['session_ids']),
        )

    return result


def get_session_info(session_file: Path) -> dict:
    """
    Get summary information about a single session file.

    Returns dict with session_id, file_size, message_count, date_range, etc.
    """
    session_meta = get_session_metadata(session_file)
    session_id = session_meta.get('id', session_file.stem) if session_meta else session_file.stem

    file_size = session_file.stat().st_size

    message_count = 0
    user_count = 0
    assistant_count = 0
    tool_result_count = 0
    first_date: Optional[date] = None
    last_date: Optional[date] = None
    models: set[str] = set()

    for msg in get_messages(session_file):
        message_count += 1
        msg_date = msg.timestamp.date()

        if first_date is None or msg_date < first_date:
            first_date = msg_date
        if last_date is None or msg_date > last_date:
            last_date = msg_date

        if msg.role == 'user':
            user_count += 1
        elif msg.role == 'assistant':
            assistant_count += 1
            if msg.model:
                models.add(msg.model)
        elif msg.role == 'toolResult':
            tool_result_count += 1

    transitions = list(get_model_transitions(session_file))

    return {
        'session_id': session_id,
        'file_path': str(session_file),
        'file_size': file_size,
        'message_count': message_count,
        'user_messages': user_count,
        'assistant_messages': assistant_count,
        'tool_result_messages': tool_result_count,
        'models_used': sorted(models),
        'transition_count': len(transitions),
        'date_range': (first_date, last_date),
        'metadata': session_meta,
    }
