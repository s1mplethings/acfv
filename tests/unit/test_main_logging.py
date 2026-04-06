from acfv.main_logging import log_error, log_info, log_warning


def test_log_helpers_accept_percent_style_args():
    log_info("value=%s", 1)
    log_warning("value=%s", 2)
    log_error("value=%s", 3)
