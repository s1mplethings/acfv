import logging, sys
from pathlib import Path

def setup_logging(settings):
    Path(settings.workdir).mkdir(parents=True, exist_ok=True)
    log_path = Path(settings.workdir) / "acfv.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path, encoding="utf-8")],
    )
