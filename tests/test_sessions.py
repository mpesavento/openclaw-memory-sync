"""Tests for session discovery module."""

import pytest
from datetime import date

from memory_sync.sessions import (
    find_session_files,
    get_date_range,
    collect_daily_activity,
    get_session_info,
)


class TestFindSessionFiles:
    """Tests for find_session_files function."""

    def test_find_session_files(self, temp_sessions_dir):
        """Find .jsonl files, exclude .lock files."""
        files = find_session_files(temp_sessions_dir)

        assert len(files) > 0

        # All should be .jsonl
        for f in files:
            assert f.suffix == '.jsonl'

    def test_excludes_lock_files(self, temp_sessions_dir):
        """Exclude .jsonl.lock files."""
        # Create a lock file
        lock_file = temp_sessions_dir / 'active.jsonl.lock'
        lock_file.write_text('{}')

        files = find_session_files(temp_sessions_dir)

        # Lock file should not be included
        assert not any('lock' in f.name for f in files)

    def test_empty_directory(self, temp_dir):
        """Return empty list for empty directory."""
        empty_dir = temp_dir / 'empty'
        empty_dir.mkdir()

        files = find_session_files(empty_dir)
        assert files == []

    def test_nonexistent_directory(self, temp_dir):
        """Return empty list for nonexistent directory."""
        files = find_session_files(temp_dir / 'nonexistent')
        assert files == []


class TestGetDateRange:
    """Tests for get_date_range function."""

    def test_get_date_range(self, temp_sessions_dir):
        """Get correct first/last dates from sessions."""
        first, last = get_date_range(temp_sessions_dir)

        assert first is not None
        assert last is not None
        assert first <= last

        # Based on fixtures: 2026-01-15 to 2026-01-19
        assert first == date(2026, 1, 15)
        assert last == date(2026, 1, 19)

    def test_empty_returns_none(self, temp_dir):
        """Return (None, None) for empty directory."""
        empty_dir = temp_dir / 'empty'
        empty_dir.mkdir()

        first, last = get_date_range(empty_dir)
        assert first is None
        assert last is None


class TestCollectDailyActivity:
    """Tests for collect_daily_activity function."""

    def test_collect_daily_activity(self, temp_sessions_dir):
        """Group messages correctly by date."""
        activity = collect_daily_activity(temp_sessions_dir)

        assert len(activity) > 0

        # Should have activity for multiple days
        dates = list(activity.keys())
        assert len(dates) >= 2

    def test_activity_counts_messages(self, temp_sessions_dir):
        """Count messages by role correctly."""
        activity = collect_daily_activity(temp_sessions_dir)

        for day, data in activity.items():
            assert data.message_count > 0
            assert data.message_count >= data.user_messages
            assert data.message_count >= data.assistant_messages

    def test_activity_tracks_models(self, temp_sessions_dir):
        """Track models used per day."""
        activity = collect_daily_activity(temp_sessions_dir)

        # At least one day should have models tracked
        all_models = []
        for data in activity.values():
            all_models.extend(data.models_used)

        assert len(all_models) > 0

    def test_activity_tracks_sessions(self, temp_sessions_dir):
        """Track session IDs per day."""
        activity = collect_daily_activity(temp_sessions_dir)

        for day, data in activity.items():
            assert len(data.session_ids) > 0


class TestGetSessionInfo:
    """Tests for get_session_info function."""

    def test_get_session_info(self, sample_session_path):
        """Get summary info for a session file."""
        info = get_session_info(sample_session_path)

        assert info['session_id'] == 'test-session-001'
        assert info['message_count'] > 0
        assert info['file_size'] > 0
        assert info['date_range'][0] is not None
        assert info['date_range'][1] is not None

    def test_session_info_counts_by_role(self, sample_session_path):
        """Correctly count messages by role."""
        info = get_session_info(sample_session_path)

        assert info['user_messages'] > 0
        assert info['assistant_messages'] > 0
        assert info['tool_result_messages'] >= 0

        # Total should equal sum of roles
        total = info['user_messages'] + info['assistant_messages'] + info['tool_result_messages']
        assert total == info['message_count']

    def test_session_info_tracks_transitions(self, model_transitions_path):
        """Track transition count."""
        info = get_session_info(model_transitions_path)

        assert info['transition_count'] >= 3
