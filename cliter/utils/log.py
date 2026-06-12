"""Logging setup."""
import logging

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"cliter.{name}")
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
        logger.addHandler(h)
        logger.setLevel(logging.WARNING)
    return logger
