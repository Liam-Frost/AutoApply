"""ATS-specific application adapters."""

from src.execution.ats.ashby import AshbyAdapter
from src.execution.ats.base import ApplicationResult, BaseATSAdapter
from src.execution.ats.generic import GenericAdapter
from src.execution.ats.greenhouse import GreenhouseAdapter
from src.execution.ats.lever import LeverAdapter

__all__ = [
    "ApplicationResult",
    "AshbyAdapter",
    "BaseATSAdapter",
    "GenericAdapter",
    "GreenhouseAdapter",
    "LeverAdapter",
]
