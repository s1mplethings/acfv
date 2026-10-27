import logging

from acfv.main_logging import log_error, log_info, log_warning


def test_log_helpers_accept_percent_style_args():
    log_info("value=%s", 1)
    log_warning("value=%s", 2)
    log_error("value=%s", 3)


def test_log_helpers_tolerate_broken_console_stream():
    import acfv.main_logging as main_logging

    class _BrokenStream:
        def write(self, _text):
            return 0

        def flush(self):
            raise OSError(22, "Invalid argument")

    original_stream = main_logging.console_handler.stream
    original_devnull = getattr(main_logging.console_handler, "_devnull_stream", None)
    main_logging.console_handler.setStream(_BrokenStream())
    main_logging.console_handler._devnull_stream = None
    try:
        log_info("broken console still logs")
        assert main_logging.console_handler.stream is not None
    finally:
        current_devnull = getattr(main_logging.console_handler, "_devnull_stream", None)
        if current_devnull is not None:
            current_devnull.close()
        main_logging.console_handler._devnull_stream = original_devnull
        main_logging.console_handler.setStream(original_stream)


def test_safe_stream_handler_replaces_unencodable_console_text():
    import acfv.main_logging as main_logging

    class _StrictAsciiStream:
        encoding = "ascii"

        def __init__(self):
            self.parts = []

        def write(self, text):
            text.encode("ascii")
            self.parts.append(text)
            return len(text)

        def flush(self):
            return None

    handler = main_logging._SafeStreamHandler(_StrictAsciiStream())
    handler.setFormatter(logging.Formatter("%(message)s"))

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="✅ done",
        args=(),
        exc_info=None,
    )

    handler.emit(record)

    assert handler.stream.parts
    assert "done" in handler.stream.parts[0]
