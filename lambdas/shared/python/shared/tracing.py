from __future__ import annotations

from aws_lambda_powertools import Tracer


def get_tracer(service: str) -> Tracer:
    """Return a pre-configured Powertools Tracer for the given service."""
    return Tracer(service=service)
    # auto_patch=True is the default — do not set auto_patch=False, as
    # Powertools warns against it when Tracer is shared across Lambda Layers.
    # Response capture is disabled globally via POWERTOOLS_TRACER_CAPTURE_RESPONSE=false.
