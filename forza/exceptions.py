"""
All custom exceptions for the forza package.

Hierarchy:
    ForzaError                  — base for all forza exceptions
    ├── ConfigValidationError   — forza_config.ini contains invalid or missing values
    ├── ExtractionError         — LLM call failed (timeout, HTTP error, retries exceeded)
    ├── ParseError              — LLM returned a response that could not be parsed
    ├── ImageEncodeError        — image file could not be encoded for the model
    ├── PersistenceError        — relational persistence failed during a run
    ├── CacheCorruptionError    — JSON import/export artifact is structurally invalid
    └── NormalizationError      — reference data missing or track/car lookup failed

Usage:
    from forza.exceptions import ExtractionError, ParseError, ConfigValidationError
"""

from __future__ import annotations


class ForzaError(Exception):
    """Base class for all forza-specific exceptions."""


class ConfigValidationError(ForzaError):
    """
    Raised when forza_config.ini contains invalid or missing values.

    The error message lists all validation failures so the operator can
    fix them all in one pass. Raised by ``forza.config.validate_config``
    and surfaced by ``python -m forza config-check``.
    """


class ExtractionError(ForzaError):
    """
    Raised when the LLM backend fails to extract data from an image.

    This covers:
    - Connection refused / LM Studio or Ollama not running
    - HTTP error status from the inference endpoint
    - Timeout (connect or read)
    - All retries exhausted
    """


class ParseError(ForzaError):
    """
    Raised when the LLM returned a response but it could not be parsed
    into a valid race session.

    This covers:
    - Response is not valid JSON
    - JSON is valid but missing required fields
    - All parse retries exhausted
    """


class ImageEncodeError(ForzaError):
    """Raised when an image file cannot be encoded for an LLM request."""


class PersistenceError(ForzaError):
    """Raised when a runtime result cannot be persisted to SQLite."""


class CacheCorruptionError(ForzaError):
    """
    Raised when an explicit JSON import/export artifact cannot be loaded due to
    structural corruption.

    Runtime extraction history is stored in SQLite.
    """


class NormalizationError(ForzaError):
    """
    Raised when reference data is required but could not be loaded, or when
    a normalisation operation fails fatally.

    Runtime references are stored in SQLite; explicit seed/dev tooling may
    still use standalone reference text files outside the product config.
    """
