from __future__ import annotations

from aws_lambda_powertools import Logger


def get_logger(service: str) -> Logger:
    """Return a pre-configured Powertools Logger for the given service."""
    return Logger(service=service, log_uncaught_exceptions=True)
    # NOTE: Powertools maintainers warn that log_uncaught_exceptions=True may
    # not function correctly in the Lambda runtime environment. If uncaught
    # exceptions are not appearing in logs, remove this parameter and rely on
    # Lambda's native error logging instead.
