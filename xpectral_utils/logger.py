"""Opt-in console logging for the xpectral_utils package logger."""

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

# Standard library imports
import logging
import sys
from typing import Literal

# -----------------------------------------------------------------------------
# Globals and constants
# -----------------------------------------------------------------------------

__all__ = ["LogLevel", "setup_logging"]

# Package-root logger. Modules log via ``logging.getLogger(__name__)``, which
# descends from this as ``xpectral_utils.*``.
_ROOT = "xpectral_utils"

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# ANSI colors per level for the optional colored console handler.
_COLORS = {
    "DEBUG": "\033[94m",
    "INFO": "\033[92m",
    "WARNING": "\033[93m",
    "ERROR": "\033[91m",
    "CRITICAL": "\033[95m",
}
_RESET = "\033[0m"

# Silent by default: a no-op handler on the package root stops Python's
# last-resort handler from printing until the app opts in (via setup_logging or
# its own logging config).
logging.getLogger(_ROOT).addHandler(logging.NullHandler())

# -----------------------------------------------------------------------------
# General API
# -----------------------------------------------------------------------------


def setup_logging(
    level: LogLevel = "INFO", *, color: bool = True, force_color: bool = False
) -> None:
    """Turn on console logging for xpectral_utils (opt-in, to stderr).

    Apps that manage their own logging can ignore this and configure the
    standard ``logging`` module directly. Color is applied only on a TTY, so
    ANSI escapes don't leak into files or pipes; pass ``force_color=True`` to
    color output regardless (e.g. in a notebook, which renders ANSI but is not
    a TTY).
    """
    logger = logging.getLogger(_ROOT)
    # Replace a handler a previous call added so repeats don't duplicate output.
    logger.handlers = [h for h in logger.handlers if isinstance(h, logging.NullHandler)]
    logger.setLevel(level)
    logger.propagate = False

    handler = logging.StreamHandler()
    handler.setFormatter(
        _ColorFormatter(color and (force_color or sys.stderr.isatty()))
    )
    logger.addHandler(handler)


# -----------------------------------------------------------------------------
# Private API
# -----------------------------------------------------------------------------


class _ColorFormatter(logging.Formatter):
    """Render ``[LEVEL] name: message``, coloring the line when enabled."""

    def __init__(self, color: bool):
        super().__init__("[%(levelname)s] %(name)s: %(message)s")
        self._color = color

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if not self._color:
            return text
        return f"{_COLORS.get(record.levelname, '')}{text}{_RESET}"
