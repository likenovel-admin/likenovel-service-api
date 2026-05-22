import logging
import logging.handlers
import os
from pathlib import Path


_OriginalTimedRotatingFileHandler = logging.handlers.TimedRotatingFileHandler


class _PytestTimedRotatingFileHandler(_OriginalTimedRotatingFileHandler):
    def __init__(self, filename, *args, **kwargs):
        try:
            super().__init__(filename, *args, **kwargs)
        except PermissionError:
            fallback_dir = Path(
                os.environ.get("LIKENOVEL_PYTEST_LOG_DIR", "/tmp/likenovel-pytest-logs")
            )
            fallback_dir.mkdir(parents=True, exist_ok=True)
            super().__init__(fallback_dir / Path(filename).name, *args, **kwargs)


logging.handlers.TimedRotatingFileHandler = _PytestTimedRotatingFileHandler
