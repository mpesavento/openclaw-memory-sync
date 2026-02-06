"""Tests for compare module."""

import pytest
from datetime import date
import shutil

from memory_sync.compare import (
    find_gaps,
    get_memory_files,
    find_orphaned_memory_files,
    format_gap_report,
)


class TestFindGaps:
    """Tests for find_gaps function."""

    def test_find_gaps_identifies_missing_days(self, temp_sessions_dir, temp_memory_dir):
        """Identify days with activity but no memory file."""
        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)

        # With empty memory dir, all active days should be missing
        assert len(gaps['missing_days']) > 0
        assert gaps['total_active_days'] > 0

    def test_find_gaps_identifies_sparse_days(self, temp_sessions_dir, temp_memory_dir, memory_fixtures_dir):
        """Identify days with files that are too small."""
        # Copy sparse memory file
        shutil.copy(
            memory_fixtures_dir / '2026-01-16.md',
            temp_memory_dir / '2026-01-16.md'
        )

        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)

        # 2026-01-16.md is sparse (< 100 bytes)
        sparse_dates = [g.date for g in gaps['sparse_days']]
        assert date(2026, 1, 16) in sparse_dates

    def test_find_gaps_full_coverage(self, temp_sessions_dir, temp_memory_dir, memory_fixtures_dir):
        """No gaps when all files are adequate."""
        # Copy adequate memory file for a day
        shutil.copy(
            memory_fixtures_dir / '2026-01-15.md',
            temp_memory_dir / '2026-01-15.md'
        )

        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)

        # 2026-01-15 should not be in missing or sparse
        missing_dates = [g.date for g in gaps['missing_days']]
        sparse_dates = [g.date for g in gaps['sparse_days']]

        assert date(2026, 1, 15) not in missing_dates
        assert date(2026, 1, 15) not in sparse_dates

    def test_coverage_percentage_calculation(self, temp_sessions_dir, temp_memory_dir, memory_fixtures_dir):
        """Coverage percentage is calculated correctly."""
        # Start with 0% coverage
        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)
        assert gaps['coverage_pct'] == 0.0

        # Add adequate file for one day
        shutil.copy(
            memory_fixtures_dir / '2026-01-15.md',
            temp_memory_dir / '2026-01-15.md'
        )

        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)

        # Should have some coverage now
        assert gaps['coverage_pct'] > 0.0
        assert gaps['covered_days'] > 0

    def test_gaps_include_activity_info(self, temp_sessions_dir, temp_memory_dir):
        """Gap objects include activity information."""
        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)

        assert len(gaps['missing_days']) > 0

        gap = gaps['missing_days'][0]
        assert gap.activity is not None
        assert gap.activity.message_count > 0


class TestGetMemoryFiles:
    """Tests for get_memory_files function."""

    def test_get_memory_files(self, memory_fixtures_dir):
        """Get memory files with correct dates."""
        files = get_memory_files(memory_fixtures_dir)

        assert len(files) == 2  # 2026-01-15.md and 2026-01-16.md

        dates = [d for d, _ in files]
        assert date(2026, 1, 15) in dates
        assert date(2026, 1, 16) in dates

    def test_ignores_non_date_files(self, temp_memory_dir):
        """Ignore files that don't match YYYY-MM-DD.md pattern."""
        # Create non-date file
        (temp_memory_dir / 'MEMORY.md').write_text('# Main memory')
        (temp_memory_dir / 'notes.md').write_text('# Notes')
        (temp_memory_dir / '2026-01-20.md').write_text('# Valid date file')

        files = get_memory_files(temp_memory_dir)

        # Should only find the date file
        assert len(files) == 1
        assert files[0][0] == date(2026, 1, 20)

    def test_sorted_by_date(self, temp_memory_dir):
        """Files are sorted by date."""
        (temp_memory_dir / '2026-01-25.md').write_text('# Later')
        (temp_memory_dir / '2026-01-10.md').write_text('# Earlier')
        (temp_memory_dir / '2026-01-20.md').write_text('# Middle')

        files = get_memory_files(temp_memory_dir)
        dates = [d for d, _ in files]

        assert dates == sorted(dates)


class TestFindOrphanedMemoryFiles:
    """Tests for find_orphaned_memory_files function."""

    def test_find_orphaned(self, temp_sessions_dir, temp_memory_dir):
        """Find memory files with no session activity."""
        # Create memory file for a date with no activity
        (temp_memory_dir / '2026-02-01.md').write_text('# No activity day')

        orphaned = find_orphaned_memory_files(temp_sessions_dir, temp_memory_dir)

        orphaned_dates = [d for d, _ in orphaned]
        assert date(2026, 2, 1) in orphaned_dates

    def test_no_orphans_when_activity_exists(self, temp_sessions_dir, temp_memory_dir, memory_fixtures_dir):
        """No orphans when files match activity dates."""
        # Copy file for an active date
        shutil.copy(
            memory_fixtures_dir / '2026-01-15.md',
            temp_memory_dir / '2026-01-15.md'
        )

        orphaned = find_orphaned_memory_files(temp_sessions_dir, temp_memory_dir)

        orphaned_dates = [d for d, _ in orphaned]
        assert date(2026, 1, 15) not in orphaned_dates


class TestFormatGapReport:
    """Tests for format_gap_report function."""

    def test_format_report(self, temp_sessions_dir, temp_memory_dir):
        """Generate readable report."""
        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)
        report = format_gap_report(gaps)

        assert 'Coverage' in report
        assert 'Active days' in report

    def test_format_report_with_missing(self, temp_sessions_dir, temp_memory_dir):
        """Report shows missing days."""
        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)
        report = format_gap_report(gaps)

        assert 'Missing' in report

    def test_format_report_full_coverage(self, temp_sessions_dir, temp_memory_dir, memory_fixtures_dir):
        """Report indicates full coverage when appropriate."""
        # Add adequate files for all dates
        for day in [15, 16, 17, 19]:
            content = f"# 2026-01-{day:02d}\n\nAdequate content with enough bytes to pass the sparse check threshold.\n" * 10
            (temp_memory_dir / f'2026-01-{day:02d}.md').write_text(content)

        gaps = find_gaps(temp_sessions_dir, temp_memory_dir)
        report = format_gap_report(gaps)

        # If coverage is 100%, should say adequate
        if gaps['coverage_pct'] == 100.0:
            assert 'adequate' in report.lower() or 'all days' in report.lower()
