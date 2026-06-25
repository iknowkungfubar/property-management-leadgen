"""Structured JSON logging module with rotation and crash recovery.

Usage::

    from src.utils.logging import setup_logging

    logger = setup_logging(level=logging.INFO, json_format=True)
    logger.info("Application started", extra={"pid": os.getpid()})

On an unhandled exception a crash report is written to
``~/.leadgen/crash-reports/`` containing the full traceback and the last
100 log lines.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

# ── Optional JSON logger ─────────────────────────────────────────────

try:
    from pythonjsonlogger import jsonlogger

    HAS_JSON_LOGGER: bool = True
except ImportError:
    jsonlogger = None  # type: ignore[assignment]
    HAS_JSON_LOGGER: bool = False

# ── Constants ─────────────────────────────────────────────────────────

CRASH_LOG_LINES: int = 100
"""Number of recent log lines to bundle into a crash report."""

LOG_DIR: Path = Path.home() / ".leadgen" / "logs"
"""Default log directory (can be overridden in :func:`setup_logging`)."""

CRASH_DIR: Path = Path.home() / ".leadgen" / "crash-reports"
"""Directory where crash reports are written."""

# ── Recent-log ring buffer ────────────────────────────────────────────


class RecentLogBuffer(logging.Handler):
    """In-memory ring buffer that keeps the last *capacity* log records.

    Used to capture the most recent log messages for inclusion in crash
    reports.  Thread-safe because ``list.append`` / ``pop`` are atomic
    in CPython for simple operations.
    """

    def __init__(self, capacity: int = CRASH_LOG_LINES) -> None:
        super().__init__(level=logging.DEBUG)
        self._capacity: int = capacity
        self._buffer: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Store *record* and evict the oldest if over capacity."""
        self._buffer.append(record)
        if len(self._buffer) > self._capacity:
            self._buffer.pop(0)

    def get_recent(self, fmt: logging.Formatter | None = None) -> list[str]:
        """Return the *capacity* most recent log messages as formatted strings."""
        if fmt is None:
            fmt = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            )
        return [fmt.format(r) for r in self._buffer]

    def clear(self) -> None:
        """Empty the buffer."""
        self._buffer.clear()


# Module-level reference so the crash hook can read it without needing
# to be passed a reference at hook-registration time.
_recent_buffer: RecentLogBuffer | None = None


# ── Crash report machinery ────────────────────────────────────────────


def _write_crash_report(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: object,
) -> None:
    """Write a crash report to ``~/.leadgen/crash-reports/``.

    Includes the full traceback and the last *CRASH_LOG_LINES* log entries
    from the ring buffer.
    """
    CRASH_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    crash_path = CRASH_DIR / f"crash-{timestamp}.log"

    lines: list[str] = [
        f"Crash Report — {timestamp}",
        f"Type: {exc_type.__name__}",
        f"Value: {exc_value}",
        "─" * 60,
        "Traceback:",
        "─" * 60,
    ]
    lines.extend(traceback.format_exception(exc_type, exc_value, exc_tb))

    if _recent_buffer is not None:
        recent: list[str] = _recent_buffer.get_recent()
        if recent:
            lines.append("─" * 60)
            lines.append(f"Last {len(recent)} log line(s):")
            lines.append("─" * 60)
            lines.extend(recent)  # type: ignore[arg-type]

    lines.append("─" * 60)
    lines.append("End of crash report")

    try:
        crash_path.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        # If we cannot write the crash report, there is nothing else to do.
        pass


def _install_crash_hook() -> None:
    """Replace ``sys.excepthook`` to capture unhandled exceptions.

    The custom hook writes a crash report to disk and then delegates to
    the original ``excepthook``.
    """
    original_hook: object = sys.excepthook

    def crash_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: object,
    ) -> None:
        # Silence crash reports for keyboard interrupts.
        if issubclass(exc_type, KeyboardInterrupt):
            if callable(original_hook):
                original_hook(exc_type, exc_value, exc_tb)
            return

        try:
            _write_crash_report(exc_type, exc_value, exc_tb)
        except Exception:
            # Don't let a crash-report write failure mask the original error.
            pass

        if callable(original_hook):
            original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = crash_hook


# ── Public API ────────────────────────────────────────────────────────


def setup_logging(
    level: int = logging.INFO,
    json_format: bool = True,
    log_dir: str | Path | None = None,
) -> logging.Logger:
    """Configure structured JSON logging with rotation and crash recovery.

    Sets up three handlers on the root logger:

    * **Rotating file handler** — writes to ``<log_dir>/leadgen.log``
      (10 MiB per file, 5 backups).
    * **Stderr stream handler** — human-readable format for development /
      Docker.
    * **Ring buffer handler** — keeps the last 100 records in memory for
      crash-report bundling.

    When *json_format* is ``True`` and the ``python-json-logger`` package
    is installed, the file handler uses JSON formatting with fields:
    ``timestamp``, ``level``, ``module``, ``message``.  If the package is
    not installed the formatter falls back to a hand-rolled JSON-like
    format.

    The function also installs a :func:`sys.excepthook` that writes crash
    reports (traceback + last 100 log lines) to ``~/.leadgen/crash-reports/``.

    Args:
        level: Minimum log level for the file handler (default:
            ``logging.INFO``).  The stderr handler always uses
            ``DEBUG`` level.
        json_format: If ``True``, use JSON formatting (requires
            ``python-json-logger``, falls back gracefully).
        log_dir: Directory for log files.  Defaults to
            ``~/.leadgen/logs``.

    Returns:
        The root logger instance.

    """
    global _recent_buffer

    resolved_log_dir = Path(log_dir) if log_dir else LOG_DIR
    resolved_log_dir.mkdir(parents=True, exist_ok=True)

    log_path = resolved_log_dir / "leadgen.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # Root accepts everything; handlers filter.

    # Remove any pre-existing handlers to avoid duplicates if
    # setup_logging is called more than once.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    # ── Build file formatter ──────────────────────────────────────
    if json_format and HAS_JSON_LOGGER:
        file_fmt: logging.Formatter = jsonlogger.JsonFormatter(
            fmt="%(timestamp)s %(level)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
            rename_fields={
                "timestamp": "timestamp",
                "level": "level",
                "name": "module",
                "message": "message",
            },
        )
    elif json_format:
        # Fallback: hand-rolled JSON-like format.
        file_fmt = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
            '"module": "%(name)s", "message": "%(message)s"}',
        )
    else:
        file_fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    # ── Rotating file handler (10 MiB, 5 backups) ─────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(file_fmt)
    root.addHandler(file_handler)

    # ── Stderr handler (dev / Docker) ──────────────────────────────
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.DEBUG)
    stderr_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"),
    )
    root.addHandler(stderr_handler)

    # ── In-memory ring buffer for crash reports ────────────────────
    _recent_buffer = RecentLogBuffer(capacity=CRASH_LOG_LINES)
    _recent_buffer.setLevel(logging.DEBUG)
    root.addHandler(_recent_buffer)

    # ── Install system exception hook ──────────────────────────────
    _install_crash_hook()

    return root
