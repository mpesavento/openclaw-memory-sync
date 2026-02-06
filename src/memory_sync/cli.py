"""CLI entry point for memory-sync."""

import click


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
    # TODO: Implement
    click.echo("compare: not yet implemented")


@main.command()
@click.option("--date", default=None, help="Specific date to backfill (YYYY-MM-DD)")
@click.option("--all", "backfill_all", is_flag=True, help="Backfill all missing dates")
@click.option("--dry-run", is_flag=True, help="Show what would be created")
@click.option("--force", is_flag=True, help="Overwrite existing files")
def backfill(date, backfill_all, dry_run, force):
    """Generate missing daily memory files from JSONL logs."""
    # TODO: Implement
    click.echo("backfill: not yet implemented")


@main.command()
@click.option("--date", default=None, help="Filter by date (YYYY-MM-DD)")
@click.option("--query", default=None, help="Search term in messages")
@click.option("--model", default=None, help="Filter by model used")
@click.option("--format", "output_format", default="md", help="Output format (md, json, text)")
def extract(date, query, model, output_format):
    """Extract conversations matching criteria."""
    # TODO: Implement
    click.echo("extract: not yet implemented")


@main.command()
@click.option("--since", default=None, help="Show transitions since date (YYYY-MM-DD)")
def transitions(since):
    """List model transitions with context."""
    # TODO: Implement
    click.echo("transitions: not yet implemented")


@main.command()
def validate():
    """Check memory files for consistency issues."""
    # TODO: Implement
    click.echo("validate: not yet implemented")


@main.command()
def stats():
    """Show coverage statistics."""
    # TODO: Implement
    click.echo("stats: not yet implemented")


if __name__ == "__main__":
    main()
