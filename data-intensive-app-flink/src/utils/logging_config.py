"""
Structured logging configuration for PyFlink jobs
"""
import logging
import sys
from datetime import datetime
import structlog


def setup_logging(log_level=logging.INFO, json_logs=True):
    """Setup structured logging for PyFlink applications"""
    
    # Configure stdlib logging
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        stream=sys.stdout,
    )
    
    # Configure structlog
    structlog.configure(
        processors=[
            # Add log level and timestamp
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="ISO"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # JSON formatting for production
            structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Get logger
    logger = structlog.get_logger()
    
    # Log initial setup
    logger.info("Logging configured", 
                log_level=logging.getLevelName(log_level),
                json_format=json_logs,
                timestamp=datetime.now().isoformat())
    
    return logger


# Create default logger instance
logger = structlog.get_logger(__name__)