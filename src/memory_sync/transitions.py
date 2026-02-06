"""Model transition tracking."""

from pathlib import Path
from typing import Iterator, Optional
from datetime import datetime, date
import json

from .models import ModelTransition
from .parser import get_model_transitions as parse_transitions
from .sessions import find_session_files


def extract_transitions(
    sessions_dir: Path,
    since: Optional[date] = None
) -> Iterator[ModelTransition]:
    """
    Extract all model transitions from session logs.

    Args:
        sessions_dir: Path to session JSONL files
        since: Optional date filter (only return transitions on or after this date)

    Yields:
        ModelTransition objects sorted chronologically
    """
    all_transitions: list[ModelTransition] = []

    for session_file in find_session_files(sessions_dir):
        for transition in parse_transitions(session_file):
            # Apply date filter
            if since is not None and transition.timestamp.date() < since:
                continue
            all_transitions.append(transition)

    # Sort chronologically
    all_transitions.sort(key=lambda t: t.timestamp)

    yield from all_transitions


def write_transitions_json(transitions: list[ModelTransition], output_path: Path):
    """
    Write transitions to JSON file for tracking.

    Creates a JSON file with transition history for external tooling.
    """
    data = {
        'generated_at': datetime.now().isoformat(),
        'count': len(transitions),
        'transitions': [
            {
                'timestamp': t.timestamp.isoformat(),
                'from_model': t.from_model,
                'to_model': t.to_model,
                'from_provider': t.from_provider,
                'provider': t.provider,
                'session_id': t.session_id,
            }
            for t in transitions
        ]
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2))


def format_transition(transition: ModelTransition) -> str:
    """
    Format a single transition for display.

    Returns a human-readable string representation.
    """
    time_str = transition.timestamp.strftime('%Y-%m-%d %H:%M:%S')

    if transition.from_model:
        from_str = f"{transition.from_provider}/{transition.from_model}" if transition.from_provider else transition.from_model
    else:
        from_str = "(start)"

    to_str = f"{transition.provider}/{transition.to_model}" if transition.provider else transition.to_model

    return f"{time_str}: {from_str} -> {to_str}"


def format_transitions_report(
    transitions: list[ModelTransition],
    since: Optional[date] = None
) -> str:
    """
    Format transitions as a human-readable report.
    """
    lines = []

    lines.append("Model Transitions Report")
    lines.append("=" * 50)

    if since:
        lines.append(f"Since: {since}")

    lines.append(f"Total transitions: {len(transitions)}")
    lines.append("")

    if not transitions:
        lines.append("No model transitions found.")
        return '\n'.join(lines)

    # Group by date
    by_date: dict[date, list[ModelTransition]] = {}
    for t in transitions:
        d = t.timestamp.date()
        if d not in by_date:
            by_date[d] = []
        by_date[d].append(t)

    for d in sorted(by_date.keys()):
        lines.append(f"{d} ({d.strftime('%A')})")
        lines.append("-" * 30)
        for t in by_date[d]:
            time_str = t.timestamp.strftime('%H:%M:%S')
            from_str = t.from_model or "(start)"
            to_str = f"{t.provider}/{t.to_model}" if t.provider else t.to_model
            lines.append(f"  {time_str}: {from_str} -> {to_str}")
        lines.append("")

    return '\n'.join(lines)


def get_transition_stats(transitions: list[ModelTransition]) -> dict:
    """
    Calculate statistics about model transitions.

    Returns dict with:
    - total_transitions: count of all transitions
    - models_used: set of all models used
    - providers_used: set of all providers used
    - transitions_by_model: count per model
    - transitions_by_provider: count per provider
    - most_common_model: most frequently used model
    - date_range: (first_date, last_date)
    """
    if not transitions:
        return {
            'total_transitions': 0,
            'models_used': [],
            'providers_used': [],
            'transitions_by_model': {},
            'transitions_by_provider': {},
            'most_common_model': None,
            'date_range': (None, None),
        }

    models: set[str] = set()
    providers: set[str] = set()
    model_counts: dict[str, int] = {}
    provider_counts: dict[str, int] = {}

    first_date: Optional[date] = None
    last_date: Optional[date] = None

    for t in transitions:
        if t.to_model:
            models.add(t.to_model)
            model_counts[t.to_model] = model_counts.get(t.to_model, 0) + 1

        if t.provider:
            providers.add(t.provider)
            provider_counts[t.provider] = provider_counts.get(t.provider, 0) + 1

        trans_date = t.timestamp.date()
        if first_date is None or trans_date < first_date:
            first_date = trans_date
        if last_date is None or trans_date > last_date:
            last_date = trans_date

    most_common = max(model_counts.items(), key=lambda x: x[1])[0] if model_counts else None

    return {
        'total_transitions': len(transitions),
        'models_used': sorted(models),
        'providers_used': sorted(providers),
        'transitions_by_model': model_counts,
        'transitions_by_provider': provider_counts,
        'most_common_model': most_common,
        'date_range': (first_date, last_date),
    }
