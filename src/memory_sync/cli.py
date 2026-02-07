"""CLI entry point for memory-sync."""

import sys
from pathlib import Path
from datetime import date, datetime, timedelta
import json

import click

from .sanitize import sanitize_content


# Default paths for OpenClaw
def get_default_sessions_dir() -> Path:
    return Path.home() / '.openclaw' / 'agents' / 'main' / 'sessions'


def get_default_memory_dir() -> Path:
    return Path.home() / '.openclaw' / 'workspace' / 'memory'


def parse_date(date_str: str) -> date:
    """Parse a date string in YYYY-MM-DD format."""
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise click.BadParameter(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")


@click.group()
@click.version_option()
def main():
    """Memory Sync - OpenClaw session log analysis and memory backfill."""
    pass


@main.command()
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
@click.option("--memory-dir", default=None, help="Path to memory files directory")
def compare(sessions_dir, memory_dir):
    """Compare JSONL logs against memory files, identify gaps."""
    from .compare import find_gaps, format_gap_report

    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()
    memory_path = Path(memory_dir) if memory_dir else get_default_memory_dir()

    if not sessions_path.exists():
        click.echo(f"Error: Sessions directory not found: {sessions_path}", err=True)
        sys.exit(1)

    if not memory_path.exists():
        click.echo(f"Warning: Memory directory not found: {memory_path}", err=True)
        click.echo("Will treat all days as missing.", err=True)
        memory_path.mkdir(parents=True, exist_ok=True)

    click.echo(f"Sessions: {sessions_path}")
    click.echo(f"Memory: {memory_path}")
    click.echo("")

    gaps = find_gaps(sessions_path, memory_path)
    report = format_gap_report(gaps)
    click.echo(report)


@main.command()
@click.option("--date", "target_date", default=None, help="Specific date to backfill (YYYY-MM-DD)")
@click.option("--all", "backfill_all", is_flag=True, help="Backfill all missing dates")
@click.option("--today", "today", is_flag=True, help="Backfill only today's date (local timezone)")
@click.option("--since", "since_date", default=None, help="Backfill from date to present (YYYY-MM-DD)")
@click.option("--incremental", "incremental", is_flag=True, help="Backfill only dates changed since last run")
@click.option("--dry-run", is_flag=True, help="Show what would be created")
@click.option("--force", is_flag=True, help="Overwrite existing files")
@click.option("--preserve", is_flag=True, help="Preserve hand-written content from existing files")
@click.option("--summarize", is_flag=True, help="Use LLM to generate narrative summaries (requires anthropic)")
@click.option("--model", default="claude-sonnet-4-20250514", help="Model to use for summarization")
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
@click.option("--memory-dir", default=None, help="Path to memory files directory")
def backfill(target_date, backfill_all, today, since_date, incremental, dry_run, force, preserve, summarize, model, sessions_dir, memory_dir):
    """Generate missing daily memory files from JSONL logs.

    By default, uses simple extraction. With --summarize, uses an LLM to
    generate narrative summaries (requires ANTHROPIC_API_KEY env var).

    Use --preserve to keep hand-written content when regenerating existing files.
    
    Date selection options (mutually exclusive):
    - --date YYYY-MM-DD: Single specific date
    - --today: Current date only (for nightly automation)
    - --since YYYY-MM-DD: From date to present (for catch-up)
    - --all: All missing dates (for initial setup)
    - --incremental: Since last run (smart automation)
    """
    from .backfill import generate_daily_memory, backfill_all_missing
    from .state import load_state, save_state, get_changed_days, get_last_run_datetime

    # Validate mutual exclusivity of date selection flags
    date_flags = [target_date, backfill_all, today, since_date, incremental]
    date_flags_count = sum(1 for flag in date_flags if flag)
    
    if date_flags_count == 0:
        click.echo("Error: Must specify one of: --date, --today, --since, --all, or --incremental", err=True)
        sys.exit(1)
    
    if date_flags_count > 1:
        click.echo("Error: Cannot combine --date, --today, --since, --all, and --incremental", err=True)
        click.echo("Choose exactly one date selection option.", err=True)
        sys.exit(1)

    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()
    memory_path = Path(memory_dir) if memory_dir else get_default_memory_dir()

    if not sessions_path.exists():
        click.echo(f"Error: Sessions directory not found: {sessions_path}", err=True)
        sys.exit(1)

    # Ensure memory directory exists
    memory_path.mkdir(parents=True, exist_ok=True)

    # Choose generator function based on --summarize flag
    if summarize:
        try:
            from .summarize import generate_summarized_memory
        except ImportError as e:
            click.echo(f"Error: {e}", err=True)
            click.echo("Install with: pip install 'memory-sync[summarize]'", err=True)
            sys.exit(1)

        def generate_fn(log_date, sessions_dir, output_path, force, preserve=False):
            return generate_summarized_memory(
                log_date, sessions_dir, output_path, force=force, preserve=preserve, model=model
            )
    else:
        def generate_fn(log_date, sessions_dir, output_path, force, preserve=False):
            return generate_daily_memory(
                log_date, sessions_dir, output_path, force=force, preserve=preserve
            )

    # Determine which dates to process
    dates_to_process = []
    
    if target_date:
        # Backfill single date
        log_date = parse_date(target_date)
        dates_to_process = [log_date]
        
    elif today:
        # Backfill today only
        log_date = datetime.now().date()
        dates_to_process = [log_date]
        click.echo(f"Processing today: {log_date}")
        
    elif since_date:
        # Backfill from specified date to today
        from_date = parse_date(since_date)
        to_date = datetime.now().date()
        
        if from_date > to_date:
            click.echo(f"Error: --since date {from_date} is in the future", err=True)
            sys.exit(1)
        
        # Generate date range
        current = from_date
        while current <= to_date:
            dates_to_process.append(current)
            current += timedelta(days=1)
        
        click.echo(f"Processing dates from {from_date} to {to_date} ({len(dates_to_process)} days)")
        
    elif incremental:
        # Backfill only dates changed since last run
        last_run = get_last_run_datetime()
        
        if last_run is None:
            click.echo("No previous run found. Use --all for initial backfill.", err=True)
            sys.exit(1)
        
        changed_dates = get_changed_days(sessions_path, last_run)
        dates_to_process = sorted(changed_dates)
        
        if dates_to_process:
            click.echo(f"Found {len(dates_to_process)} days with changes since {last_run.strftime('%Y-%m-%d %H:%M')}")
        else:
            click.echo(f"No changes since last run at {last_run.strftime('%Y-%m-%d %H:%M')}")
    
    # Process specific dates
    if dates_to_process and not backfill_all:
        created = []
        skipped = []
        errors = []
        
        for log_date in dates_to_process:
            output_path = memory_path / f"{log_date}.md"
            
            if dry_run:
                click.echo(f"Would create: {output_path}")
                created.append(str(output_path))
            else:
                try:
                    path = generate_fn(log_date, sessions_path, output_path, force=force, preserve=preserve)
                    created.append(path)
                    click.echo(f"Created: {path}")
                except FileExistsError:
                    skipped.append(log_date)
                    if len(dates_to_process) > 1:
                        click.echo(f"Skipped: {output_path} (already exists)")
                    else:
                        click.echo(f"Error: File already exists: {output_path}", err=True)
                        click.echo("Use --force or --preserve to overwrite.", err=True)
                        sys.exit(1)
                except ValueError as e:
                    errors.append((log_date, str(e)))
                    if len(dates_to_process) > 1:
                        click.echo(f"Error for {log_date}: {e}", err=True)
                    else:
                        click.echo(f"Error: {e}", err=True)
                        sys.exit(1)
        
        # Summary for multi-date operations
        if len(dates_to_process) > 1:
            click.echo("")
            if created:
                action = "Would create" if dry_run else "Created"
                click.echo(f"{action} {len(created)} files")
            if skipped:
                click.echo(f"Skipped {len(skipped)} existing files (use --force to overwrite)")
            if errors:
                click.echo(f"Errors: {len(errors)}", err=True)
        
        # Update state for incremental mode
        if incremental and created and not dry_run:
            state = load_state()
            total = state.get('total_days_processed', 0) + len(created)
            last_date = max(dates_to_process) if dates_to_process else None
            save_state(
                last_run=datetime.now(),
                last_successful_date=last_date,
                total_days_processed=total
            )
            click.echo(f"Updated state: {total} total days processed")
    
    elif backfill_all:
        # Backfill all missing
        if summarize:
            # Manual iteration with summarization
            from .compare import find_gaps

            gaps = find_gaps(sessions_path, memory_path)
            created = []
            errors = []

            all_gaps = gaps['missing_days'] + (gaps['sparse_days'] if force else [])

            if dry_run:
                click.echo("Dry run - no files created")
                for gap in all_gaps:
                    click.echo(f"Would create: {memory_path / f'{gap.date}.md'}")
            else:
                for gap in all_gaps:
                    output_path = memory_path / f"{gap.date}.md"
                    click.echo(f"Summarizing {gap.date}...", nl=False)
                    try:
                        path = generate_fn(gap.date, sessions_path, output_path, force=True, preserve=preserve)
                        created.append(path)
                        click.echo(" done")
                    except Exception as e:
                        errors.append((gap.date, str(e)))
                        click.echo(f" error: {e}")

                if created:
                    click.echo(f"\nCreated {len(created)} files")
                if errors:
                    click.echo(f"Errors: {len(errors)}", err=True)
                if not created and not errors:
                    click.echo("No missing files to backfill.")
        else:
            result = backfill_all_missing(sessions_path, memory_path, dry_run=dry_run, force=force, preserve=preserve)

            if dry_run:
                click.echo("Dry run - no files created")
                click.echo("")

            if result['created']:
                action = "Would create" if dry_run else "Created"
                click.echo(f"{action} {len(result['created'])} files:")
                for path in result['created']:
                    click.echo(f"  {path}")

            if result['skipped']:
                click.echo(f"\nSkipped {len(result['skipped'])} existing files (use --force to overwrite)")

            if result['errors']:
                click.echo(f"\nErrors ({len(result['errors'])}):", err=True)
                for err_date, err_msg in result['errors']:
                    click.echo(f"  {err_date}: {err_msg}", err=True)

            if not result['created'] and not result['errors']:
                click.echo("No missing files to backfill.")


@main.command()
@click.option("--date", "target_date", default=None, help="Filter by date (YYYY-MM-DD)")
@click.option("--query", default=None, help="Search term in messages")
@click.option("--model", default=None, help="Filter by model used")
@click.option("--format", "output_format", default="md", type=click.Choice(['md', 'json', 'text']), help="Output format")
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
def extract(target_date, query, model, output_format, sessions_dir):
    """Extract conversations matching criteria."""
    from .parser import get_messages
    from .sessions import find_session_files

    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()

    if not sessions_path.exists():
        click.echo(f"Error: Sessions directory not found: {sessions_path}", err=True)
        sys.exit(1)

    date_filter = parse_date(target_date) if target_date else None

    # Collect matching messages
    messages = []
    for session_file in find_session_files(sessions_path):
        for msg in get_messages(session_file, date_filter=date_filter):
            # Apply query filter
            if query and query.lower() not in msg.text_content.lower():
                continue

            # Apply model filter
            if model and msg.model != model:
                continue

            messages.append(msg)

    # Sort by timestamp
    messages.sort(key=lambda m: m.timestamp)

    if not messages:
        click.echo("No matching messages found.")
        return

    click.echo(f"Found {len(messages)} matching messages")
    click.echo("")

    # Format output (with sanitization)
    if output_format == 'json':
        data = [
            {
                'id': m.id,
                'timestamp': m.timestamp.isoformat(),
                'role': m.role,
                'text': sanitize_content(m.text_content),  # Sanitize full content
                'model': m.model,
                'provider': m.provider,
            }
            for m in messages
        ]
        click.echo(json.dumps(data, indent=2))

    elif output_format == 'text':
        for msg in messages:
            time_str = msg.timestamp.strftime('%Y-%m-%d %H:%M')
            role = msg.role.upper()
            text = sanitize_content(msg.text_content)  # Sanitize full content
            click.echo(f"[{time_str}] {role}: {text}")
            click.echo("")

    else:  # md
        for msg in messages:
            time_str = msg.timestamp.strftime('%Y-%m-%d %H:%M')
            role = msg.role.capitalize()
            model_str = f" ({msg.model})" if msg.model else ""
            click.echo(f"### [{time_str}] {role}{model_str}")
            click.echo("")
            text = sanitize_content(msg.text_content)  # Sanitize full content
            click.echo(text)
            click.echo("")


@main.command()
@click.option("--date", "target_date", required=True, help="Date to summarize (YYYY-MM-DD)")
@click.option("--model", default="claude-sonnet-4-20250514", help="Model to use for summarization")
@click.option("--output", default=None, help="Write to file (default: stdout)")
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
def summarize(target_date, model, output, sessions_dir):
    """Generate an LLM summary for a single day (requires anthropic).

    Prints the summary to stdout or writes to a file.
    Requires ANTHROPIC_API_KEY environment variable.
    """
    try:
        from .summarize import generate_summarized_memory
    except ImportError as e:
        click.echo(f"Error: {e}", err=True)
        click.echo("Install with: pip install 'memory-sync[summarize]'", err=True)
        sys.exit(1)

    import tempfile

    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()

    if not sessions_path.exists():
        click.echo(f"Error: Sessions directory not found: {sessions_path}", err=True)
        sys.exit(1)

    log_date = parse_date(target_date)

    # Generate to temp file or specified output
    if output:
        output_path = Path(output)
    else:
        # Use temp file, then print contents
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False)
        output_path = Path(tmp.name)
        tmp.close()

    try:
        generate_summarized_memory(
            log_date, sessions_path, output_path,
            force=True, model=model
        )

        if not output:
            # Print to stdout
            content = output_path.read_text()
            click.echo(content)
            output_path.unlink()  # Clean up temp file
        else:
            click.echo(f"Wrote summary to: {output_path}")

    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error generating summary: {e}", err=True)
        sys.exit(1)


@main.command()
@click.option("--date", "since_date", default=None, help="Show transitions since date (YYYY-MM-DD)")
@click.option("--output", default=None, help="Write JSON to file")
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
def transitions(since_date, output, sessions_dir):
    """List model transitions with context."""
    from .transitions import extract_transitions, format_transitions_report, write_transitions_json

    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()

    if not sessions_path.exists():
        click.echo(f"Error: Sessions directory not found: {sessions_path}", err=True)
        sys.exit(1)

    since_date_parsed = parse_date(since_date) if since_date else None

    trans_list = list(extract_transitions(sessions_path, since=since_date_parsed))

    if output:
        output_path = Path(output)
        write_transitions_json(trans_list, output_path)
        click.echo(f"Wrote {len(trans_list)} transitions to {output_path}")
    else:
        report = format_transitions_report(trans_list, since=since_date_parsed)
        click.echo(report)


@main.command()
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
@click.option("--memory-dir", default=None, help="Path to memory files directory")
def validate(sessions_dir, memory_dir):
    """Check memory files for consistency issues."""
    from .validate import validate_memory_files, format_validation_report

    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()
    memory_path = Path(memory_dir) if memory_dir else get_default_memory_dir()

    if not memory_path.exists():
        click.echo(f"Error: Memory directory not found: {memory_path}", err=True)
        sys.exit(1)

    click.echo(f"Validating: {memory_path}")
    click.echo(f"Sessions reference: {sessions_path}")
    click.echo("")

    result = validate_memory_files(memory_path, sessions_path)
    report = format_validation_report(result)
    click.echo(report)

    # Exit with error if there are error-level issues
    if any(i.severity == 'error' for i in result['issues']):
        sys.exit(1)


@main.command()
@click.option("--sessions-dir", default=None, help="Path to session logs directory")
@click.option("--memory-dir", default=None, help="Path to memory files directory")
def stats(sessions_dir, memory_dir):
    """Show coverage statistics."""
    from .sessions import find_session_files, get_date_range, collect_daily_activity, get_session_info
    from .compare import get_memory_files, find_gaps
    from .transitions import extract_transitions, get_transition_stats

    sessions_path = Path(sessions_dir) if sessions_dir else get_default_sessions_dir()
    memory_path = Path(memory_dir) if memory_dir else get_default_memory_dir()

    click.echo("Memory Sync Statistics")
    click.echo("=" * 50)
    click.echo("")

    # Session stats
    click.echo("Session Logs")
    click.echo("-" * 30)

    if sessions_path.exists():
        session_files = find_session_files(sessions_path)
        click.echo(f"  Session files: {len(session_files)}")

        total_size = sum(f.stat().st_size for f in session_files)
        click.echo(f"  Total size: {total_size / 1024 / 1024:.1f} MB")

        first_date, last_date = get_date_range(sessions_path)
        if first_date and last_date:
            click.echo(f"  Date range: {first_date} to {last_date}")

        daily_activity = collect_daily_activity(sessions_path)
        total_messages = sum(d.message_count for d in daily_activity.values())
        total_user = sum(d.user_messages for d in daily_activity.values())
        total_assistant = sum(d.assistant_messages for d in daily_activity.values())
        total_tool = sum(d.tool_result_messages for d in daily_activity.values())

        click.echo(f"  Total messages: {total_messages}")
        click.echo(f"    User: {total_user}")
        click.echo(f"    Assistant: {total_assistant}")
        click.echo(f"    Tool results: {total_tool}")

        # Models used
        all_models: set[str] = set()
        for activity in daily_activity.values():
            all_models.update(activity.models_used)
        if all_models:
            click.echo(f"  Models used: {', '.join(sorted(all_models))}")

        # Transitions
        trans_list = list(extract_transitions(sessions_path))
        trans_stats = get_transition_stats(trans_list)
        click.echo(f"  Model transitions: {trans_stats['total_transitions']}")

    else:
        click.echo(f"  Directory not found: {sessions_path}")

    click.echo("")

    # Memory stats
    click.echo("Memory Files")
    click.echo("-" * 30)

    if memory_path.exists():
        memory_files = get_memory_files(memory_path)
        click.echo(f"  Daily files: {len(memory_files)}")

        total_size = sum(f.stat().st_size for _, f in memory_files)
        click.echo(f"  Total size: {total_size / 1024:.1f} KB")

        if memory_files:
            first_mem = memory_files[0][0]
            last_mem = memory_files[-1][0]
            click.echo(f"  Date range: {first_mem} to {last_mem}")

        # Coverage
        if sessions_path.exists():
            gaps = find_gaps(sessions_path, memory_path)
            click.echo(f"  Coverage: {gaps['coverage_pct']:.1f}%")
            click.echo(f"    Active days: {gaps['total_active_days']}")
            click.echo(f"    Covered days: {gaps.get('covered_days', 0)}")
            click.echo(f"    Missing: {len(gaps['missing_days'])}")
            click.echo(f"    Sparse: {len(gaps['sparse_days'])}")
    else:
        click.echo(f"  Directory not found: {memory_path}")

    click.echo("")


if __name__ == "__main__":
    main()
