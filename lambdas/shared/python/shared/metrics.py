from __future__ import annotations

from aws_lambda_powertools import Metrics


def get_metrics(service: str, namespace: str = "ZeroStars") -> Metrics:
    """Return a pre-configured Powertools Metrics instance for the given service."""
    return Metrics(service=service, namespace=namespace)
