"""Backward-compatible imports for the renamed Typhoon service."""

from .typhoon import TyphoonChat, TyphoonResponse, TyphoonService, TyphoonServiceError


GeminiService = TyphoonService

__all__ = [
    "GeminiService",
    "TyphoonChat",
    "TyphoonResponse",
    "TyphoonService",
    "TyphoonServiceError",
]
