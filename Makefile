.PHONY: test test-security test-integration test-all test-cov install clean help

# Default target
help:
	@echo "Available targets:"
	@echo "  make test              - Run all tests"
	@echo "  make test-security     - Run security sanitization tests only"
	@echo "  make test-integration  - Run integration tests only"
	@echo "  make test-all          - Run all tests with verbose output"
	@echo "  make test-cov          - Run tests with coverage report"
	@echo "  make install           - Install package with dev dependencies"
	@echo "  make clean             - Remove cache and build files"

# Run all tests (quiet mode)
test:
	uv run --extra dev pytest tests/ -q

# Run security tests only
test-security:
	uv run --extra dev pytest tests/test_sanitize.py tests/test_sanitize_integration.py -v

# Run integration tests only
test-integration:
	uv run --extra dev pytest tests/test_sanitize_integration.py -v

# Run all tests with verbose output
test-all:
	uv run --extra dev pytest tests/ -v

# Run tests with coverage report
test-cov:
	uv run --extra dev pytest tests/ --cov=memory_sync --cov-report=term-missing --cov-report=html

# Install package with dev dependencies
install:
	uv pip install -e ".[dev]"

# Clean up cache and build files
clean:
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
