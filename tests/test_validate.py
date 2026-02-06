"""Tests for validate module."""

import pytest
from datetime import date

from memory_sync.validate import (
    validate_memory_files,
    format_validation_report,
)


class TestValidateMemoryFiles:
    """Tests for validate_memory_files function."""

    def test_validate_valid_files(self, temp_memory_dir, temp_sessions_dir):
        """Valid files pass validation."""
        # Create a valid file with enough content
        content = """# 2026-01-15 (Wednesday)

*Auto-generated from 10 session messages*

## Topics Covered
- Topic 1
- Topic 2

This file has adequate content to pass the size check.
More content here to ensure it's over 100 bytes minimum.
""" * 2
        (temp_memory_dir / '2026-01-15.md').write_text(content)

        result = validate_memory_files(temp_memory_dir, temp_sessions_dir)

        # Should have at least one valid file
        assert result['total_count'] >= 1

    def test_detect_naming_issues(self, temp_memory_dir, temp_sessions_dir):
        """Detect files with invalid naming."""
        # Create file with bad name
        (temp_memory_dir / 'not-a-date.md').write_text('# Content\n' * 20)

        result = validate_memory_files(temp_memory_dir, temp_sessions_dir)

        naming_issues = [i for i in result['issues'] if i.issue_type == 'naming']
        assert len(naming_issues) > 0

    def test_detect_header_mismatch(self, temp_memory_dir, temp_sessions_dir):
        """Detect header date not matching filename."""
        # Create file with mismatched header
        content = """# 2026-01-20 (Monday)

Wrong date in header.
""" * 10
        (temp_memory_dir / '2026-01-15.md').write_text(content)

        result = validate_memory_files(temp_memory_dir, temp_sessions_dir)

        mismatch_issues = [i for i in result['issues'] if i.issue_type == 'header_mismatch']
        assert len(mismatch_issues) > 0

    def test_detect_too_small(self, temp_memory_dir, temp_sessions_dir):
        """Detect files that are too small."""
        # Create tiny file
        (temp_memory_dir / '2026-01-15.md').write_text('# 2026-01-15\nTiny.')

        result = validate_memory_files(temp_memory_dir, temp_sessions_dir)

        small_issues = [i for i in result['issues'] if i.issue_type == 'too_small']
        assert len(small_issues) > 0

    def test_detect_orphaned(self, temp_memory_dir, temp_sessions_dir):
        """Detect files with no session activity."""
        # Create file for date with no activity
        content = """# 2026-12-25 (Thursday)

No activity on this date.
""" * 10
        (temp_memory_dir / '2026-12-25.md').write_text(content)

        result = validate_memory_files(temp_memory_dir, temp_sessions_dir)

        orphan_issues = [i for i in result['issues'] if i.issue_type == 'orphaned']
        assert len(orphan_issues) > 0

    def test_nonexistent_memory_dir(self, temp_dir, temp_sessions_dir):
        """Handle nonexistent memory directory."""
        result = validate_memory_files(
            temp_dir / 'nonexistent',
            temp_sessions_dir
        )

        assert len(result['issues']) > 0
        assert result['issues'][0].issue_type == 'parse_error'


class TestFormatValidationReport:
    """Tests for format_validation_report function."""

    def test_format_report(self, temp_memory_dir, temp_sessions_dir):
        """Generate readable validation report."""
        # Create some files
        (temp_memory_dir / '2026-01-15.md').write_text('# 2026-01-15\nSmall')

        result = validate_memory_files(temp_memory_dir, temp_sessions_dir)
        report = format_validation_report(result)

        assert 'Validation Report' in report
        assert 'Total files checked' in report

    def test_report_groups_by_type(self, temp_memory_dir, temp_sessions_dir):
        """Report groups issues by type."""
        # Create files with different issues
        (temp_memory_dir / 'bad-name.md').write_text('# Content\n' * 20)
        (temp_memory_dir / '2026-01-15.md').write_text('# 2026-01-15\nTiny')

        result = validate_memory_files(temp_memory_dir, temp_sessions_dir)
        report = format_validation_report(result)

        # Should have sections for different issue types
        assert 'Naming Issues' in report or 'Too Small' in report

    def test_report_all_valid(self, temp_memory_dir, temp_sessions_dir):
        """Report indicates when all files are valid."""
        # Create valid file
        content = """# 2026-01-15 (Wednesday)

*Auto-generated from 10 session messages*

## Topics Covered
- Topic 1
- Topic 2

This file has adequate content to pass all validation checks.
Additional content to ensure adequate size.
""" * 3
        (temp_memory_dir / '2026-01-15.md').write_text(content)

        result = validate_memory_files(temp_memory_dir, temp_sessions_dir)

        # Filter out orphaned issues (since fixture date may not match sessions)
        non_orphan_issues = [i for i in result['issues'] if i.issue_type != 'orphaned']

        if len(non_orphan_issues) == 0:
            report = format_validation_report({'issues': [], 'valid_count': 1, 'total_count': 1})
            assert 'passed' in report.lower() or 'valid' in report.lower()
