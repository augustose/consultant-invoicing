"""
Centralized logging configuration for Accounting AI.
Uses loguru with file rotation and structured output.
"""

import os
import sys
import logging
from loguru import logger

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


# --- Suppress noisy third-party loggers ---
class NiceGUIFilter(logging.Filter):
    """Suppress known harmless NiceGUI 'Request is not set' warnings."""
    def filter(self, record):
        return "Request is not set" not in record.getMessage()

def suppress_noisy_loggers():
    """Quiet down third-party loggers that flood the terminal."""
    # Suppress NiceGUI "Request is not set" startup noise
    for name in ("nicegui", "nicegui.nicegui"):
        ng_logger = logging.getLogger(name)
        ng_logger.addFilter(NiceGUIFilter())

    # Suppress SQLAlchemy engine echo (also set echo=False on engine)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # Suppress uvicorn access logs (optional, keeps startup info)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def setup_logging():
    """Configure loguru with file sinks for persistence and debugging."""
    
    # Remove default stderr handler to avoid duplicate output
    logger.remove()
    
    # Console output — INFO level, colorful
    logger.add(
        sys.stderr,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        colorize=True,
    )
    
    # App log file — DEBUG level, rotated daily, kept 30 days
    logger.add(
        os.path.join(LOG_DIR, "app.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        enqueue=True,  # Thread-safe
    )
    
    # Error-only log file — for quick error triage
    logger.add(
        os.path.join(LOG_DIR, "errors.log"),
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}\n{exception}",
        rotation="5 MB",
        retention="60 days",
        compression="zip",
        enqueue=True,
        backtrace=True,    # Full traceback
        diagnose=True,     # Variable values in traceback
    )
    
    # Suppress noisy third-party loggers
    suppress_noisy_loggers()
    
    logger.info("📋 Sistema de logging inicializado correctamente")
    logger.debug(f"Directorio de logs: {LOG_DIR}")

# Auto-configure on import
setup_logging()
