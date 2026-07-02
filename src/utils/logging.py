import logging
import sys

LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FMT = "%H:%M:%S"


def setup_logging(level: str = "INFO") -> logging.Logger:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(FMT, DATE_FMT))

    logger = logging.getLogger("captcha_solver")
    logger.setLevel(LEVELS.get(level.upper(), logging.INFO))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger(name: str = "captcha_solver") -> logging.Logger:
    return logging.getLogger(name)
