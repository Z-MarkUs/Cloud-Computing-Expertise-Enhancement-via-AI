"""Domain exceptions that map to safe public responses."""

from __future__ import annotations


class CloudTutorError(Exception):
    """Base class for expected application failures."""

    code = "cloud_tutor_error"
    status_code = 500
    public_message = "The request could not be completed."


class ProviderConfigurationError(CloudTutorError):
    """Raised when an optional provider cannot be configured."""

    code = "provider_configuration_error"
    status_code = 503
    public_message = "The configured AI provider is unavailable."


class ProviderUnavailableError(CloudTutorError):
    """Raised when a configured provider fails at request time."""

    code = "provider_unavailable"
    status_code = 503
    public_message = "The AI provider is temporarily unavailable. Please try again later."


class CorpusError(CloudTutorError):
    """Raised when the local corpus is absent or malformed."""

    code = "corpus_unavailable"
    status_code = 503
    public_message = "The knowledge base is unavailable."
