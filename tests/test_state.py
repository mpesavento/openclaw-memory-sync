"""Tests for state management."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timedelta

from memory_sync.state import (
    get_state_file_path,
    load_state,
    save_state,
    get_changed_days,
    get_last_run_datetime
)


@pytest.fixture
def temp_state_dir(tmp_path, monkeypatch):
    """Create temporary state directory."""
    state_dir = tmp_path / '.memory-sync'
    state_dir.mkdir(parents=True, exist_ok=True)
    
    # Mock Path.home() to return tmp_path
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    
    return state_dir


class TestStateFile:
    """Tests for state file operations."""
    
    def test_get_state_file_path(self, temp_state_dir):
        """State file path is in home directory."""
        path = get_state_file_path()
        assert path.name == 'state.json'
        assert '.memory-sync' in str(path)
    
    def test_load_state_empty(self, temp_state_dir):
        """Loading nonexistent state returns empty dict."""
        state = load_state()
        assert state == {}
    
    def test_save_and_load_state(self, temp_state_dir):
        """State can be saved and loaded."""
        now = datetime.now()
        
        save_state(
            last_run=now,
            last_successful_date=now.date(),
            total_days_processed=5
        )
        
        state = load_state()
        assert 'last_run' in state
        assert 'last_successful_date' in state
        assert state['total_days_processed'] == 5
    
    def test_save_state_incremental(self, temp_state_dir):
        """State updates preserve existing values."""
        # Save initial state
        save_state(total_days_processed=5)
        
        # Update with new value
        save_state(total_days_processed=10)
        
        state = load_state()
        assert state['total_days_processed'] == 10
        assert 'last_run' in state  # Should be auto-set
    
    def test_save_state_partial(self, temp_state_dir):
        """Partial state updates work correctly."""
        now = datetime.now()
        save_state(last_run=now, total_days_processed=3)
        
        # Update only total_days_processed
        save_state(total_days_processed=5)
        
        state = load_state()
        assert state['total_days_processed'] == 5
        assert 'last_run' in state
    
    def test_load_state_corrupted(self, temp_state_dir):
        """Corrupted state file returns empty dict."""
        state_file = get_state_file_path()
        state_file.write_text("not valid json{")
        
        state = load_state()
        assert state == {}
    
    def test_get_last_run_datetime(self, temp_state_dir):
        """Get last run datetime from state."""
        now = datetime.now()
        save_state(last_run=now)
        
        last_run = get_last_run_datetime()
        assert last_run is not None
        # Compare as strings since datetime comparison can be finicky
        assert last_run.isoformat() == now.isoformat()
    
    def test_get_last_run_datetime_none(self, temp_state_dir):
        """Get last run returns None if no state."""
        last_run = get_last_run_datetime()
        assert last_run is None


class TestChangedDays:
    """Tests for detecting changed days."""
    
    def test_get_changed_days_empty(self, tmp_path):
        """Empty sessions dir returns empty set."""
        empty_sessions_dir = tmp_path / 'empty_sessions'
        empty_sessions_dir.mkdir()
        
        since = datetime.now() - timedelta(days=7)
        changed = get_changed_days(empty_sessions_dir, since)
        assert changed == set()
    
    def test_get_changed_days_with_sessions(self, temp_sessions_dir):
        """Detects dates from modified session files."""
        # Create a session file with a recent modification time
        session_file = temp_sessions_dir / 'test-session.jsonl'
        
        # Write a message from yesterday
        from datetime import date
        yesterday = date.today() - timedelta(days=1)
        
        session_file.write_text(json.dumps({
            'type': 'message',
            'timestamp': yesterday.isoformat() + 'T10:00:00Z',
            'message': {
                'role': 'user',
                'content': [{'type': 'text', 'text': 'Hello'}]
            }
        }) + '\n')
        
        # Set modified time to now
        import time
        now_timestamp = time.time()
        import os
        os.utime(session_file, (now_timestamp, now_timestamp))
        
        # Check for changes since 2 days ago
        since = datetime.now() - timedelta(days=2)
        changed = get_changed_days(temp_sessions_dir, since)
        
        assert len(changed) > 0
    
    def test_get_changed_days_old_files_ignored(self, tmp_path):
        """Old session files are not included."""
        clean_sessions_dir = tmp_path / 'clean_sessions'
        clean_sessions_dir.mkdir()
        
        session_file = clean_sessions_dir / 'old-session.jsonl'
        session_file.write_text(json.dumps({
            'type': 'message',
            'timestamp': '2026-01-01T10:00:00Z',
            'message': {
                'role': 'user',
                'content': [{'type': 'text', 'text': 'Hello'}]
            }
        }) + '\n')
        
        # Set modified time to 10 days ago
        import time
        old_timestamp = time.time() - (10 * 24 * 60 * 60)
        import os
        os.utime(session_file, (old_timestamp, old_timestamp))
        
        # Check for changes since 1 day ago
        since = datetime.now() - timedelta(days=1)
        changed = get_changed_days(clean_sessions_dir, since)
        
        assert len(changed) == 0


class TestStateIntegration:
    """Integration tests for state management."""
    
    def test_full_workflow(self, temp_state_dir):
        """Complete workflow: save, load, update."""
        # Initial save
        run1 = datetime.now()
        save_state(last_run=run1, total_days_processed=3)
        
        # Load and verify
        state = load_state()
        assert state['total_days_processed'] == 3
        
        # Update
        run2 = datetime.now()
        save_state(last_run=run2, total_days_processed=5)
        
        # Verify update
        state = load_state()
        assert state['total_days_processed'] == 5
        
        last_run = get_last_run_datetime()
        assert last_run.isoformat() == run2.isoformat()
