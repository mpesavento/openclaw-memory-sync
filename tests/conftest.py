"""Pytest fixtures for memory-sync tests."""

import pytest
from pathlib import Path
import tempfile
import shutil
from datetime import datetime


@pytest.fixture
def fixtures_dir() -> Path:
    """Path to the test fixtures directory."""
    return Path(__file__).parent / 'fixtures'


@pytest.fixture
def sample_session_path(fixtures_dir) -> Path:
    """Path to the sample multi-day session JSONL file."""
    return fixtures_dir / 'sample_session.jsonl'


@pytest.fixture
def sample_session_small_path(fixtures_dir) -> Path:
    """Path to the minimal session JSONL file."""
    return fixtures_dir / 'sample_session_small.jsonl'


@pytest.fixture
def malformed_path(fixtures_dir) -> Path:
    """Path to the malformed JSONL file."""
    return fixtures_dir / 'malformed.jsonl'


@pytest.fixture
def model_transitions_path(fixtures_dir) -> Path:
    """Path to the session with model transitions."""
    return fixtures_dir / 'model_transitions.jsonl'


@pytest.fixture
def memory_fixtures_dir(fixtures_dir) -> Path:
    """Path to the memory fixtures directory."""
    return fixtures_dir / 'memory'


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test outputs."""
    tmpdir = tempfile.mkdtemp()
    yield Path(tmpdir)
    shutil.rmtree(tmpdir)


@pytest.fixture
def temp_sessions_dir(temp_dir, fixtures_dir):
    """Create a temporary sessions directory with fixture files."""
    sessions_dir = temp_dir / 'sessions'
    sessions_dir.mkdir()

    # Copy fixture files
    for f in fixtures_dir.glob('*.jsonl'):
        if 'malformed' not in f.name:  # Exclude malformed for normal tests
            shutil.copy(f, sessions_dir / f.name)

    return sessions_dir


@pytest.fixture
def temp_memory_dir(temp_dir):
    """Create a temporary memory directory."""
    memory_dir = temp_dir / 'memory'
    memory_dir.mkdir()
    return memory_dir


@pytest.fixture
def temp_sessions_with_all(temp_dir, fixtures_dir):
    """Create a temporary sessions directory with all fixtures including malformed."""
    sessions_dir = temp_dir / 'sessions_all'
    sessions_dir.mkdir()

    # Copy all fixture files
    for f in fixtures_dir.glob('*.jsonl'):
        shutil.copy(f, sessions_dir / f.name)

    return sessions_dir


@pytest.fixture
def temp_state_dir(tmp_path, monkeypatch):
    """Create temporary state directory for incremental backfill tests."""
    state_dir = tmp_path / '.memory-sync'
    state_dir.mkdir(parents=True, exist_ok=True)
    
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    
    return state_dir
