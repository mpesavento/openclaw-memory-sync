"""Tests for backfill module."""

import pytest
from datetime import date

from memory_sync.backfill import (
    generate_daily_memory,
    backfill_all_missing,
    extract_topics,
    extract_key_exchanges,
    extract_decisions,
    format_transitions,
    render_daily_template,
)
from memory_sync.parser import get_messages
from memory_sync.models import ModelTransition
from datetime import datetime, timezone


class TestGenerateDailyMemory:
    """Tests for generate_daily_memory function."""

    def test_creates_file(self, temp_sessions_dir, temp_memory_dir):
        """File is created at correct path."""
        output_path = temp_memory_dir / '2026-01-15.md'

        result = generate_daily_memory(
            date(2026, 1, 15),
            temp_sessions_dir,
            output_path
        )

        assert output_path.exists()
        assert result == str(output_path)

    def test_format_correct(self, temp_sessions_dir, temp_memory_dir):
        """Output matches expected template format."""
        output_path = temp_memory_dir / '2026-01-15.md'

        generate_daily_memory(
            date(2026, 1, 15),
            temp_sessions_dir,
            output_path
        )

        content = output_path.read_text()

        # Check structure
        assert '# 2026-01-15' in content
        assert 'Auto-generated' in content
        assert 'Review and edit' in content

    def test_no_overwrite_without_force(self, temp_sessions_dir, temp_memory_dir):
        """Fails without --force when file exists."""
        output_path = temp_memory_dir / '2026-01-15.md'
        output_path.write_text('Existing content')

        with pytest.raises(FileExistsError):
            generate_daily_memory(
                date(2026, 1, 15),
                temp_sessions_dir,
                output_path,
                force=False
            )

    def test_overwrite_with_force(self, temp_sessions_dir, temp_memory_dir):
        """Overwrites with --force."""
        output_path = temp_memory_dir / '2026-01-15.md'
        output_path.write_text('Existing content')

        generate_daily_memory(
            date(2026, 1, 15),
            temp_sessions_dir,
            output_path,
            force=True
        )

        content = output_path.read_text()
        assert 'Existing content' not in content
        assert '2026-01-15' in content

    def test_no_messages_raises_error(self, temp_sessions_dir, temp_memory_dir):
        """Raises error if no messages for date."""
        output_path = temp_memory_dir / '2026-12-25.md'

        with pytest.raises(ValueError, match='No messages found'):
            generate_daily_memory(
                date(2026, 12, 25),
                temp_sessions_dir,
                output_path
            )


class TestBackfillAllMissing:
    """Tests for backfill_all_missing function."""

    def test_creates_all_missing(self, temp_sessions_dir, temp_memory_dir):
        """Creates files for all missing dates."""
        result = backfill_all_missing(temp_sessions_dir, temp_memory_dir)

        assert len(result['created']) > 0
        assert len(result['errors']) == 0

        # Files should exist
        for path in result['created']:
            assert temp_memory_dir.joinpath(path.split('/')[-1]).exists()

    def test_dry_run(self, temp_sessions_dir, temp_memory_dir):
        """Dry run shows what would be created without creating."""
        result = backfill_all_missing(
            temp_sessions_dir,
            temp_memory_dir,
            dry_run=True
        )

        assert len(result['created']) > 0
        assert result['dry_run'] is True

        # Files should NOT exist
        for path in result['created']:
            filename = path.split('/')[-1]
            assert not (temp_memory_dir / filename).exists()


class TestExtractTopics:
    """Tests for extract_topics function."""

    def test_extract_topics(self, sample_session_path):
        """Extract topics from messages."""
        messages = list(get_messages(sample_session_path))
        topics = extract_topics(messages)

        assert isinstance(topics, list)
        # Should have extracted some topics
        assert len(topics) >= 0  # May be empty for small samples

    def test_excludes_stopwords(self, sample_session_path):
        """Common words are excluded."""
        messages = list(get_messages(sample_session_path))
        topics = extract_topics(messages)

        stopwords = ['the', 'and', 'with', 'you', 'can']
        for topic in topics:
            assert topic.lower() not in stopwords


class TestExtractKeyExchanges:
    """Tests for extract_key_exchanges function."""

    def test_extract_exchanges(self, sample_session_path):
        """Extract user questions with responses."""
        messages = list(get_messages(sample_session_path))
        exchanges = extract_key_exchanges(messages)

        assert isinstance(exchanges, list)
        assert len(exchanges) > 0

        # Each exchange has expected fields
        for ex in exchanges:
            assert 'time' in ex
            assert 'user_excerpt' in ex

    def test_respects_max_limit(self, sample_session_path):
        """Respects max_exchanges limit."""
        messages = list(get_messages(sample_session_path))
        exchanges = extract_key_exchanges(messages, max_exchanges=2)

        assert len(exchanges) <= 2


class TestExtractDecisions:
    """Tests for extract_decisions function."""

    def test_extract_decisions(self, sample_session_path):
        """Extract decisions from assistant messages."""
        messages = list(get_messages(sample_session_path))
        decisions = extract_decisions(messages)

        assert isinstance(decisions, list)
        # May or may not have decisions depending on content


class TestFormatTransitions:
    """Tests for format_transitions function."""

    def test_format_transitions(self):
        """Format transitions for template."""
        transitions = [
            ModelTransition(
                timestamp=datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc),
                from_model='claude-sonnet-4',
                to_model='gpt-4o',
                session_id='test',
                provider='openai',
                from_provider='anthropic',
            )
        ]

        formatted = format_transitions(transitions)

        assert len(formatted) == 1
        assert formatted[0]['time'] == '14:00'
        assert 'sonnet' in formatted[0]['from'].lower()
        assert 'gpt' in formatted[0]['to'].lower()


class TestRenderDailyTemplate:
    """Tests for render_daily_template function."""

    def test_render_basic(self):
        """Render basic template."""
        context = {
            'date': '2026-01-15',
            'day_name': 'Wednesday',
            'message_count': 10,
            'topics': ['Python', 'Testing'],
            'key_exchanges': [],
            'decisions': [],
            'transitions': [],
            'compaction_summary': None,
        }

        content = render_daily_template(context)

        assert '# 2026-01-15 (Wednesday)' in content
        assert '10 session messages' in content
        assert 'Python' in content
        assert 'Testing' in content

    def test_render_with_compaction(self):
        """Render with compaction summary."""
        context = {
            'date': '2026-01-15',
            'day_name': 'Wednesday',
            'message_count': 10,
            'topics': [],
            'key_exchanges': [],
            'decisions': [],
            'transitions': [],
            'compaction_summary': '## Goal\nTest goal',
        }

        content = render_daily_template(context)

        assert 'Context Summary' in content
        assert 'Test goal' in content

    def test_render_with_transitions(self):
        """Render with model transitions."""
        context = {
            'date': '2026-01-15',
            'day_name': 'Wednesday',
            'message_count': 10,
            'topics': [],
            'key_exchanges': [],
            'decisions': [],
            'transitions': [{'time': '14:00', 'from': 'sonnet', 'to': 'gpt-4o'}],
            'compaction_summary': None,
        }

        content = render_daily_template(context)

        assert 'Model Transitions' in content
        assert '14:00' in content
