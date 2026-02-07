"""Tests for CLI commands."""

import pytest
from click.testing import CliRunner

from memory_sync.cli import main


@pytest.fixture
def runner():
    """Create CLI test runner."""
    return CliRunner()


class TestCompareCommand:
    """Tests for compare command."""

    def test_compare_runs(self, runner, temp_sessions_dir, temp_memory_dir):
        """Compare command runs without error."""
        result = runner.invoke(main, [
            'compare',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 0
        assert 'Coverage' in result.output

    def test_compare_missing_sessions_dir(self, runner, temp_dir):
        """Compare fails gracefully with missing sessions dir."""
        result = runner.invoke(main, [
            'compare',
            '--sessions-dir', str(temp_dir / 'nonexistent'),
            '--memory-dir', str(temp_dir),
        ])

        assert result.exit_code == 1
        assert 'not found' in result.output.lower()


class TestBackfillCommand:
    """Tests for backfill command."""

    def test_backfill_single_date(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill single date."""
        result = runner.invoke(main, [
            'backfill',
            '--date', '2026-01-15',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 0
        assert 'Created' in result.output
        assert (temp_memory_dir / '2026-01-15.md').exists()

    def test_backfill_dry_run(self, runner, temp_sessions_dir, temp_memory_dir):
        """Dry run shows but doesn't create."""
        result = runner.invoke(main, [
            'backfill',
            '--all',
            '--dry-run',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 0
        assert 'Would create' in result.output or 'Dry run' in result.output

        # No files should be created
        md_files = list(temp_memory_dir.glob('*.md'))
        assert len(md_files) == 0

    def test_backfill_requires_date_or_all(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill requires --date or --all."""
        result = runner.invoke(main, [
            'backfill',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 1
        assert '--date' in result.output or '--all' in result.output

    def test_backfill_invalid_date(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill rejects invalid date format."""
        result = runner.invoke(main, [
            'backfill',
            '--date', 'not-a-date',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 2  # Click parameter error


class TestExtractCommand:
    """Tests for extract command."""

    def test_extract_by_date(self, runner, temp_sessions_dir):
        """Extract messages by date."""
        result = runner.invoke(main, [
            'extract',
            '--date', '2026-01-15',
            '--sessions-dir', str(temp_sessions_dir),
        ])

        assert result.exit_code == 0
        assert 'Found' in result.output or 'matching' in result.output.lower()

    def test_extract_json_format(self, runner, temp_sessions_dir):
        """Extract with JSON output format."""
        result = runner.invoke(main, [
            'extract',
            '--date', '2026-01-15',
            '--format', 'json',
            '--sessions-dir', str(temp_sessions_dir),
        ])

        assert result.exit_code == 0
        # JSON format should have brackets
        if 'Found' in result.output and 'matching' in result.output:
            assert '[' in result.output or 'No matching' in result.output


class TestTransitionsCommand:
    """Tests for transitions command."""

    def test_transitions_runs(self, runner, temp_sessions_dir):
        """Transitions command runs."""
        result = runner.invoke(main, [
            'transitions',
            '--sessions-dir', str(temp_sessions_dir),
        ])

        assert result.exit_code == 0
        assert 'Transitions' in result.output

    def test_transitions_since(self, runner, temp_sessions_dir):
        """Filter transitions by since date."""
        result = runner.invoke(main, [
            'transitions',
            '--date', '2026-01-18',
            '--sessions-dir', str(temp_sessions_dir),
        ])

        assert result.exit_code == 0

    def test_transitions_json_output(self, runner, temp_sessions_dir, temp_dir):
        """Write transitions to JSON file."""
        output_file = temp_dir / 'transitions.json'

        result = runner.invoke(main, [
            'transitions',
            '--output', str(output_file),
            '--sessions-dir', str(temp_sessions_dir),
        ])

        assert result.exit_code == 0
        assert output_file.exists()


class TestValidateCommand:
    """Tests for validate command."""

    def test_validate_runs(self, runner, temp_sessions_dir, temp_memory_dir, memory_fixtures_dir):
        """Validate command runs."""
        import shutil
        shutil.copy(
            memory_fixtures_dir / '2026-01-15.md',
            temp_memory_dir / '2026-01-15.md'
        )

        result = runner.invoke(main, [
            'validate',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 0 or result.exit_code == 1  # May have warnings
        assert 'Validation' in result.output


class TestStatsCommand:
    """Tests for stats command."""

    def test_stats_runs(self, runner, temp_sessions_dir, temp_memory_dir):
        """Stats command runs."""
        result = runner.invoke(main, [
            'stats',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 0
        assert 'Statistics' in result.output
        assert 'Session' in result.output

    def test_stats_shows_counts(self, runner, temp_sessions_dir, temp_memory_dir):
        """Stats shows message counts."""
        result = runner.invoke(main, [
            'stats',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])

        assert result.exit_code == 0
        assert 'messages' in result.output.lower()


class TestVersionOption:
    """Tests for --version option."""

    def test_version(self, runner):
        """Show version."""
        result = runner.invoke(main, ['--version'])

        assert result.exit_code == 0
        assert '0.1.0' in result.output


class TestBackfillTodayFlag:
    """Tests for --today flag."""
    
    def test_backfill_today_dry_run(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill --today with dry run."""
        result = runner.invoke(main, [
            'backfill',
            '--today',
            '--dry-run',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])
        
        assert result.exit_code == 0
        assert 'Processing today' in result.output or 'Would create' in result.output
    
    def test_backfill_today_with_force(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill --today with --force."""
        result = runner.invoke(main, [
            'backfill',
            '--today',
            '--force',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])
        
        # May succeed or fail depending on whether there are messages today
        assert result.exit_code in (0, 1)


class TestBackfillSinceFlag:
    """Tests for --since flag."""
    
    def test_backfill_since_dry_run(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill --since with dry run."""
        result = runner.invoke(main, [
            'backfill',
            '--since', '2026-01-15',
            '--dry-run',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])
        
        assert result.exit_code == 0
        assert 'Processing dates from' in result.output or 'days' in result.output
    
    def test_backfill_since_invalid_date(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill --since with invalid date format."""
        result = runner.invoke(main, [
            'backfill',
            '--since', 'not-a-date',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])
        
        assert result.exit_code == 2  # Click validation error
    
    def test_backfill_since_future_date(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill --since with future date fails."""
        result = runner.invoke(main, [
            'backfill',
            '--since', '2099-12-31',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])
        
        assert result.exit_code == 1
        assert 'future' in result.output.lower()


class TestBackfillIncrementalFlag:
    """Tests for --incremental flag."""
    
    def test_backfill_incremental_no_state(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill --incremental without prior state fails."""
        result = runner.invoke(main, [
            'backfill',
            '--incremental',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])
        
        assert result.exit_code == 1
        assert 'No previous run' in result.output or '--all' in result.output
    
    def test_backfill_incremental_with_state(self, runner, temp_sessions_dir, temp_memory_dir, monkeypatch):
        """Backfill --incremental with existing state."""
        from pathlib import Path
        from memory_sync.state import save_state
        from datetime import datetime, timedelta
        
        # Mock home directory to use temp dir
        state_dir = temp_memory_dir.parent / '.memory-sync'
        state_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(Path, 'home', lambda: temp_memory_dir.parent)
        
        # Save a state from 1 day ago
        save_state(last_run=datetime.now() - timedelta(days=1))
        
        result = runner.invoke(main, [
            'backfill',
            '--incremental',
            '--dry-run',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])
        
        # Should succeed with or without changes
        assert result.exit_code == 0


class TestBackfillMutualExclusivity:
    """Tests for mutual exclusivity of date flags."""
    
    def test_no_date_flag_fails(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill without any date flag fails."""
        result = runner.invoke(main, [
            'backfill',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])
        
        assert result.exit_code == 1
        assert 'Must specify one of' in result.output
    
    def test_multiple_date_flags_fails(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill with multiple date flags fails."""
        result = runner.invoke(main, [
            'backfill',
            '--today',
            '--all',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])
        
        assert result.exit_code == 1
        assert 'Cannot combine' in result.output
    
    def test_date_and_since_fails(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill with --date and --since fails."""
        result = runner.invoke(main, [
            'backfill',
            '--date', '2026-01-15',
            '--since', '2026-01-10',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])
        
        assert result.exit_code == 1
        assert 'Cannot combine' in result.output
    
    def test_today_and_incremental_fails(self, runner, temp_sessions_dir, temp_memory_dir):
        """Backfill with --today and --incremental fails."""
        result = runner.invoke(main, [
            'backfill',
            '--today',
            '--incremental',
            '--sessions-dir', str(temp_sessions_dir),
            '--memory-dir', str(temp_memory_dir),
        ])
        
        assert result.exit_code == 1
        assert 'Cannot combine' in result.output
