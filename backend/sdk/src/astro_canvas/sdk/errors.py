"""Exception types raised by the SDK."""

from __future__ import annotations


class SdkError(Exception):
    """Base class for every SDK error."""


class NodeDefinitionError(SdkError, TypeError):
    """A ``@node`` or ``@port_type`` declaration is invalid (bad annotation, id, return type)."""


class DuplicateNodeError(SdkError, ValueError):
    """Two nodes (or two port types) were registered under the same id."""


class UnknownNodeError(SdkError, LookupError):
    """No node with the requested id is registered."""


class UnknownTypeError(SdkError, LookupError):
    """No port type with the requested id is registered."""


class BlobError(SdkError, ValueError):
    """A port value could not be serialized to, or restored from, a blob."""
