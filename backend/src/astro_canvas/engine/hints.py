"""One-line hints for the exceptions a user actually hits.

Every failure — a node's, or an unhandled one in a REST handler — travels with a `hint` when
there is something useful to say, and the node badge, the inspector, the errors drawer and the
toast all show it. The rule for adding one: it must tell the user *what to do next*, in their
terms. "Check the node's parameters" qualifies; "invalid literal for int()" does not.

Types that only exist in a pack (astropy, httpx, pyarrow) are matched by **name** rather than by
`isinstance`, because the engine must not import a pack's dependencies to explain its errors.
"""

from __future__ import annotations

from pydantic import ValidationError

from astro_canvas.sdk import BlobError

BY_NAME: dict[str, str] = {
    # Filesystem and workspace
    "FileNotFoundError": "That file is not in the workspace any more. Pick it again in the "
    "Workspace panel, or re-upload it.",
    "IsADirectoryError": "That path is a folder. Choose a file inside it.",
    "PermissionError": "The file cannot be read with this server's permissions.",
    "FileExistsError": "Something is already at that path. Choose another name.",
    "OSError": "The filesystem refused the operation; check free space and permissions.",
    # Resources
    "MemoryError": "Not enough memory for this step. Crop or rebin the data first, or mark the "
    "node expensive so it runs in its own process.",
    "RecursionError": "The graph or the data nests too deeply for this node.",
    # `concurrent.futures.TimeoutError` on 3.10, where it is not the builtin `TimeoutError` the
    # `isinstance` check below would catch.
    "TimeoutError": "The node exceeded the configured time limit.",
    # Environment
    "ModuleNotFoundError": "A package this node needs is not installed. Install it from "
    "Manager > Packs, or install the pack that provides it.",
    "ImportError": "A package this node needs could not be imported; Manager > Packs shows the "
    "load error.",
    # Data
    "UnitConversionError": "Those units are not convertible. Check the wavelength or flux unit "
    "on the input.",
    "UnitsError": "Astropy could not make sense of the unit. Use a unit string it knows, such "
    "as 'Angstrom' or 'erg / (s cm2 Angstrom)'.",
    "ArrowInvalid": "The table could not be read as Arrow; check the column types.",
    "KeyError": "A column or header keyword the node needs is missing from the data.",
    "IndexError": "An index is outside the data; check the wavelength range or the row number.",
    "ZeroDivisionError": "A divisor is zero — often an empty range or an all-zero error array.",
    # Network (the archive fetch nodes)
    "ConnectError": "The archive could not be reached. Check the network, then run the node again.",
    "ConnectTimeout": "The archive did not answer in time. Run the node again, or narrow the "
    "query.",
    "ReadTimeout": "The archive stopped responding mid-download. Run the node again.",
    "HTTPStatusError": "The archive refused the query; its own message is above.",
    "TooManyRedirects": "The archive redirected in a loop; check the service URL.",
    "JSONDecodeError": "The response was not the JSON this node expected.",
}
"""Exception class name to hint. Names, not classes: no pack import to explain a pack error."""


def _by_type() -> tuple[tuple[type[BaseException], str], ...]:
    """Hints for the engine's own exception types (imported lazily to avoid a cycle)."""
    from astro_canvas.engine.outputs import OutputError  # noqa: PLC0415
    from astro_canvas.engine.scheduler import UpstreamMissingError  # noqa: PLC0415

    return (
        (ValidationError, "Check the node's parameters against its schema."),
        (
            BlobError,
            "This value cannot be serialized; astro.Any outputs need cheap (in-process) nodes.",
        ),
        (UpstreamMissingError, "Run the upstream node first or reconnect the input."),
        (TimeoutError, "The node exceeded the configured time limit."),
        (OutputError, "The node returned a value that does not match its declared outputs."),
    )


def hint_for(exc: BaseException) -> str | None:
    """A one-line "what to do next", or ``None`` when there is nothing honest to say."""
    for kind, hint in _by_type():
        if isinstance(exc, kind):
            return hint
    # Walk the class hierarchy so a subclass of a known error inherits its hint.
    for cls in type(exc).__mro__:
        found = BY_NAME.get(cls.__name__)
        if found is not None:
            return found
    return None
