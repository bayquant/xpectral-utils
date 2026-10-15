# ----------------------------------------------------------------------------
# Imports
# ----------------------------------------------------------------------------

# Standard library imports
import logging

# Third-party imports
import pytest

# First-party imports
from xpectral_utils.logger import setup_logging

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


@pytest.fixture
def package_logger():
    """The package logger, with its state restored after each test."""
    logger = logging.getLogger("xpectral_utils")
    handlers, level, propagate = logger.handlers[:], logger.level, logger.propagate
    yield logger
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate


def _stream_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if not isinstance(h, logging.NullHandler)]


# ----------------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------------


def test_silent_by_default(package_logger):
    assert any(isinstance(h, logging.NullHandler) for h in package_logger.handlers)
    assert _stream_handlers(package_logger) == []


def test_setup_logging_adds_one_handler_and_sets_level(package_logger):
    setup_logging("DEBUG", color=False)

    assert len(_stream_handlers(package_logger)) == 1
    assert package_logger.level == logging.DEBUG
    assert package_logger.propagate is False


def test_setup_logging_is_idempotent(package_logger):
    setup_logging("INFO", color=False)
    setup_logging("WARNING", color=False)

    assert len(_stream_handlers(package_logger)) == 1
    assert package_logger.level == logging.WARNING


def test_setup_logging_keeps_the_null_handler(package_logger):
    setup_logging("INFO", color=False)

    assert any(isinstance(h, logging.NullHandler) for h in package_logger.handlers)


def test_plain_format_has_no_ansi_codes(package_logger):
    setup_logging("INFO", color=False)
    record = logging.LogRecord(
        "xpectral_utils.s3", logging.INFO, __file__, 1, "downloaded: key", None, None
    )

    text = _stream_handlers(package_logger)[0].format(record)

    assert text == "[INFO] xpectral_utils.s3: downloaded: key"


def test_force_color_wraps_the_line_in_ansi_codes(package_logger):
    setup_logging("INFO", force_color=True)
    record = logging.LogRecord(
        "xpectral_utils.s3", logging.WARNING, __file__, 1, "no object", None, None
    )

    text = _stream_handlers(package_logger)[0].format(record)

    assert text.startswith("\033[93m")
    assert text.endswith("\033[0m")
    assert "[WARNING] xpectral_utils.s3: no object" in text
