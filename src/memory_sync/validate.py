"""Validation of memory files for consistency issues."""

from pathlib import Path
from datetime import date
import re

from .models import ValidationIssue
from .sessions import collect_daily_activity


# Minimum file size to be considered valid
MIN_VALID_SIZE = 100  # bytes


def validate_memory_files(memory_dir: Path, sessions_dir: Path) -> dict:
    """
    Validate memory files for consistency issues.

    Checks:
    - File naming (YYYY-MM-DD.md pattern)
    - Date header matches filename
    - Minimum file size (> 100 bytes)
    - Orphaned files (no session activity for that date)

    Returns dict with:
    - issues: list of ValidationIssue objects
    - valid_count: count of files passing all checks
    - total_count: total files checked
    """
    issues: list[ValidationIssue] = []
    valid_count = 0
    total_count = 0

    if not memory_dir.exists():
        return {
            'issues': [ValidationIssue(
                file_path=str(memory_dir),
                issue_type='parse_error',
                description='Memory directory does not exist',
                severity='error'
            )],
            'valid_count': 0,
            'total_count': 0,
        }

    # Get activity data for orphan detection
    daily_activity = collect_daily_activity(sessions_dir) if sessions_dir.exists() else {}

    # Check all markdown files
    for file_path in memory_dir.glob('*.md'):
        total_count += 1
        file_issues: list[ValidationIssue] = []

        # Skip MEMORY.md (main memory file, not daily)
        if file_path.name.upper() == 'MEMORY.MD':
            continue

        # Check file naming
        file_date = _validate_filename(file_path)
        if file_date is None:
            file_issues.append(ValidationIssue(
                file_path=str(file_path),
                issue_type='naming',
                description=f'Filename does not match YYYY-MM-DD.md pattern: {file_path.name}',
                severity='warning'
            ))
        else:
            # Check header matches filename
            header_issue = _validate_header(file_path, file_date)
            if header_issue:
                file_issues.append(header_issue)

            # Check for orphaned files
            if file_date not in daily_activity or daily_activity[file_date].message_count == 0:
                file_issues.append(ValidationIssue(
                    file_path=str(file_path),
                    issue_type='orphaned',
                    description=f'No session activity found for {file_date}',
                    severity='warning'
                ))

        # Check file size
        file_size = file_path.stat().st_size
        if file_size < MIN_VALID_SIZE:
            file_issues.append(ValidationIssue(
                file_path=str(file_path),
                issue_type='too_small',
                description=f'File too small: {file_size} bytes (minimum: {MIN_VALID_SIZE})',
                severity='warning'
            ))

        if file_issues:
            issues.extend(file_issues)
        else:
            valid_count += 1

    return {
        'issues': issues,
        'valid_count': valid_count,
        'total_count': total_count,
    }


def _validate_filename(file_path: Path) -> date | None:
    """
    Validate filename matches YYYY-MM-DD.md pattern.

    Returns the parsed date if valid, None otherwise.
    """
    try:
        return date.fromisoformat(file_path.stem)
    except ValueError:
        return None


def _validate_header(file_path: Path, expected_date: date) -> ValidationIssue | None:
    """
    Validate that the file's date header matches the filename.

    Returns a ValidationIssue if mismatch, None if OK.
    """
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        return ValidationIssue(
            file_path=str(file_path),
            issue_type='parse_error',
            description=f'Could not read file: {e}',
            severity='error'
        )

    # Look for date in first line header
    first_line = content.split('\n')[0] if content else ''

    # Expected formats:
    # "# 2026-01-15 (Thursday)"
    # "# 2026-01-15 - Daily Memory"
    # "# January 15, 2026"
    date_pattern = r'\b(\d{4}-\d{2}-\d{2})\b'
    match = re.search(date_pattern, first_line)

    if match:
        header_date_str = match.group(1)
        try:
            header_date = date.fromisoformat(header_date_str)
            if header_date != expected_date:
                return ValidationIssue(
                    file_path=str(file_path),
                    issue_type='header_mismatch',
                    description=f'Header date {header_date} does not match filename date {expected_date}',
                    severity='warning'
                )
        except ValueError:
            pass  # Date parsing failed, but it's not a mismatch per se

    return None


def format_validation_report(validation_result: dict) -> str:
    """
    Format validation results as a human-readable report.
    """
    lines = []

    lines.append("Memory File Validation Report")
    lines.append("=" * 50)
    lines.append("")
    lines.append(f"Total files checked: {validation_result['total_count']}")
    lines.append(f"Valid files: {validation_result['valid_count']}")
    lines.append(f"Files with issues: {validation_result['total_count'] - validation_result['valid_count']}")
    lines.append("")

    issues = validation_result['issues']
    if not issues:
        lines.append("All files passed validation!")
        return '\n'.join(lines)

    # Group issues by type
    by_type: dict[str, list[ValidationIssue]] = {}
    for issue in issues:
        if issue.issue_type not in by_type:
            by_type[issue.issue_type] = []
        by_type[issue.issue_type].append(issue)

    # Report by type
    type_labels = {
        'naming': 'Naming Issues',
        'header_mismatch': 'Header Mismatches',
        'too_small': 'Files Too Small',
        'orphaned': 'Orphaned Files (no session activity)',
        'parse_error': 'Parse Errors',
    }

    for issue_type, type_issues in by_type.items():
        label = type_labels.get(issue_type, issue_type)
        severity_icon = "!" if any(i.severity == 'error' for i in type_issues) else "~"

        lines.append(f"{severity_icon} {label} ({len(type_issues)})")
        lines.append("-" * 40)
        for issue in type_issues:
            file_name = Path(issue.file_path).name
            lines.append(f"  {file_name}: {issue.description}")
        lines.append("")

    return '\n'.join(lines)
