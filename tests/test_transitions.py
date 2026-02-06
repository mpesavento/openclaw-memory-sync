"""Tests for transitions module."""

import pytest
from datetime import date, datetime, timezone

from memory_sync.transitions import (
    extract_transitions,
    write_transitions_json,
    format_transition,
    format_transitions_report,
    get_transition_stats,
)
from memory_sync.models import ModelTransition


class TestExtractTransitions:
    """Tests for extract_transitions function."""

    def test_extract_from_model_change(self, temp_sessions_dir):
        """Extract transitions from explicit model_change records."""
        transitions = list(extract_transitions(temp_sessions_dir))

        assert len(transitions) > 0

        # Should have transitions to different models
        models = {t.to_model for t in transitions}
        assert len(models) > 1

    def test_transitions_chronological_order(self, temp_sessions_dir):
        """Transitions are sorted by timestamp."""
        transitions = list(extract_transitions(temp_sessions_dir))

        timestamps = [t.timestamp for t in transitions]
        assert timestamps == sorted(timestamps)

    def test_since_filter(self, temp_sessions_dir):
        """Filter transitions by since date."""
        # Get all transitions
        all_trans = list(extract_transitions(temp_sessions_dir))

        # Filter to only recent
        since_date = date(2026, 1, 18)
        filtered = list(extract_transitions(temp_sessions_dir, since=since_date))

        assert len(filtered) < len(all_trans)

        for t in filtered:
            assert t.timestamp.date() >= since_date


class TestWriteTransitionsJson:
    """Tests for write_transitions_json function."""

    def test_write_json(self, temp_dir):
        """Write transitions to JSON file."""
        transitions = [
            ModelTransition(
                timestamp=datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
                from_model='claude-sonnet-4',
                to_model='gpt-4o',
                session_id='test-001',
                provider='openai',
                from_provider='anthropic',
            )
        ]

        output_path = temp_dir / 'transitions.json'
        write_transitions_json(transitions, output_path)

        assert output_path.exists()

        import json
        data = json.loads(output_path.read_text())

        assert data['count'] == 1
        assert len(data['transitions']) == 1
        assert data['transitions'][0]['to_model'] == 'gpt-4o'


class TestFormatTransition:
    """Tests for format_transition function."""

    def test_format_basic(self):
        """Format a basic transition."""
        t = ModelTransition(
            timestamp=datetime(2026, 1, 15, 14, 30, 45, tzinfo=timezone.utc),
            from_model='claude-sonnet-4',
            to_model='gpt-4o',
            session_id='test',
            provider='openai',
            from_provider='anthropic',
        )

        formatted = format_transition(t)

        assert '2026-01-15' in formatted
        assert '14:30:45' in formatted
        assert 'sonnet' in formatted.lower()
        assert 'gpt-4o' in formatted.lower()

    def test_format_first_transition(self):
        """Format transition from start (no from_model)."""
        t = ModelTransition(
            timestamp=datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            from_model=None,
            to_model='claude-sonnet-4',
            session_id='test',
            provider='anthropic',
            from_provider=None,
        )

        formatted = format_transition(t)

        assert '(start)' in formatted
        assert 'sonnet' in formatted.lower()


class TestFormatTransitionsReport:
    """Tests for format_transitions_report function."""

    def test_format_report(self):
        """Generate readable report."""
        transitions = [
            ModelTransition(
                timestamp=datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
                from_model='claude-sonnet-4',
                to_model='gpt-4o',
                session_id='test',
                provider='openai',
                from_provider='anthropic',
            ),
            ModelTransition(
                timestamp=datetime(2026, 1, 16, 10, 0, 0, tzinfo=timezone.utc),
                from_model='gpt-4o',
                to_model='claude-opus-4',
                session_id='test',
                provider='anthropic',
                from_provider='openai',
            ),
        ]

        report = format_transitions_report(transitions)

        assert 'Model Transitions Report' in report
        assert 'Total transitions: 2' in report
        assert '2026-01-15' in report
        assert '2026-01-16' in report

    def test_empty_report(self):
        """Report handles empty transitions."""
        report = format_transitions_report([])

        assert 'No model transitions found' in report

    def test_report_with_since(self):
        """Report shows since date."""
        transitions = []
        since = date(2026, 1, 15)

        report = format_transitions_report(transitions, since=since)

        assert 'Since: 2026-01-15' in report


class TestGetTransitionStats:
    """Tests for get_transition_stats function."""

    def test_stats_basic(self):
        """Calculate basic stats."""
        transitions = [
            ModelTransition(
                timestamp=datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
                from_model='claude-sonnet-4',
                to_model='gpt-4o',
                session_id='test',
                provider='openai',
                from_provider='anthropic',
            ),
            ModelTransition(
                timestamp=datetime(2026, 1, 16, 10, 0, 0, tzinfo=timezone.utc),
                from_model='gpt-4o',
                to_model='claude-opus-4',
                session_id='test',
                provider='anthropic',
                from_provider='openai',
            ),
        ]

        stats = get_transition_stats(transitions)

        assert stats['total_transitions'] == 2
        assert 'gpt-4o' in stats['models_used']
        assert 'claude-opus-4' in stats['models_used']
        assert 'openai' in stats['providers_used']
        assert 'anthropic' in stats['providers_used']

    def test_stats_empty(self):
        """Handle empty transitions."""
        stats = get_transition_stats([])

        assert stats['total_transitions'] == 0
        assert stats['models_used'] == []
        assert stats['most_common_model'] is None

    def test_most_common_model(self):
        """Find most common model."""
        transitions = [
            ModelTransition(
                timestamp=datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
                from_model=None,
                to_model='gpt-4o',
                session_id='test',
                provider='openai',
            ),
            ModelTransition(
                timestamp=datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
                from_model='gpt-4o',
                to_model='claude-sonnet-4',
                session_id='test',
                provider='anthropic',
            ),
            ModelTransition(
                timestamp=datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
                from_model='claude-sonnet-4',
                to_model='gpt-4o',
                session_id='test',
                provider='openai',
            ),
        ]

        stats = get_transition_stats(transitions)

        # gpt-4o appears twice as to_model
        assert stats['most_common_model'] == 'gpt-4o'
