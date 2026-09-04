"""Locating and running ``uv``: the only way this app is allowed to touch its Python environment.

The tooling rule (CONTRIBUTING) forbids ``pip``/``venv``/``conda`` everywhere, the pack manager
included, so every environment mutation goes through ``uv pip`` against an explicit
``--python <interpreter>``. ``find_uv`` prefers the binary shipped next to the launcher, then the
one on ``PATH``; ``download_uv`` is the last resort for a user who installed the app as a wheel.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import structlog

from astro_canvas.manager.archive import safe_extract

log = structlog.get_logger("astro_canvas.manager")

UV_ENV_VAR = "ASTRO_CANVAS_UV_PATH"
UV_RELEASE_URL = "https://github.com/astral-sh/uv/releases/latest/download"
DEFAULT_TIMEOUT_S = 600.0

UV_ASSETS: dict[tuple[str, str], str] = {
    ("win32", "AMD64"): "uv-x86_64-pc-windows-msvc.zip",
    ("win32", "ARM64"): "uv-aarch64-pc-windows-msvc.zip",
    ("darwin", "arm64"): "uv-aarch64-apple-darwin.tar.gz",
    ("darwin", "x86_64"): "uv-x86_64-apple-darwin.tar.gz",
    ("linux", "x86_64"): "uv-x86_64-unknown-linux-gnu.tar.gz",
    ("linux", "aarch64"): "uv-aarch64-unknown-linux-gnu.tar.gz",
}


class UvNotFoundError(RuntimeError):
    """No ``uv`` executable could be located (and downloading one was not allowed or failed)."""


class UvError(RuntimeError):
    """A ``uv`` invocation failed. ``result`` carries the captured output."""

    def __init__(self, message: str, result: UvResult) -> None:
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class UvResult:
    """Outcome of one ``uv`` subprocess."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        """stdout and stderr joined, in the order a terminal would show them."""
        return "\n".join(part for part in (self.stdout.strip(), self.stderr.strip()) if part)


def _binary_name() -> str:
    return "uv.exe" if sys.platform == "win32" else "uv"


def _candidates() -> list[Path]:
    """Where a bundled ``uv`` may sit: next to this interpreter, or in the launcher's folder."""
    name = _binary_name()
    roots = [Path(sys.prefix), Path(sys.base_prefix), Path(sys.executable).parent]
    out: list[Path] = []
    for root in roots:
        out.extend([root / name, root / "bin" / name, root / "Scripts" / name])
    return out


def find_uv(explicit: Path | str | None = None) -> Path:
    """The ``uv`` binary to use: ``explicit``, then ``$ASTRO_CANVAS_UV_PATH``, bundled, then PATH.

    Raises:
        UvNotFoundError: when nothing usable was found.
    """
    for candidate in (explicit, os.environ.get(UV_ENV_VAR)):
        if candidate:
            path = Path(candidate).expanduser()
            if path.is_file():
                return path
            raise UvNotFoundError(f"{path} is not an executable file")
    for path in _candidates():
        if path.is_file():
            return path
    found = shutil.which("uv")
    if found:
        return Path(found)
    raise UvNotFoundError(
        "uv was not found. Install it from https://docs.astral.sh/uv/ or set "
        f"{UV_ENV_VAR} to its path."
    )


def download_uv(dest_dir: Path, *, timeout: float = 120.0) -> Path:
    """Fetch the latest ``uv`` release for this platform into ``dest_dir`` and return its path.

    Only reached when the user asks for it in Manager > Settings; an install that already has
    ``uv`` on PATH never gets here.
    """
    import httpx  # noqa: PLC0415 - lazy: only the download path needs an HTTP client

    key = (sys.platform, platform.machine())
    asset = UV_ASSETS.get(key)
    if asset is None:
        raise UvNotFoundError(f"no uv release is published for {key[0]}/{key[1]}")
    url = f"{UV_RELEASE_URL}/{asset}"
    log.info("downloading uv", url=url)
    response = httpx.get(url, follow_redirects=True, timeout=timeout)
    response.raise_for_status()
    dest_dir.mkdir(parents=True, exist_ok=True)
    payload = BytesIO(response.content)
    if asset.endswith(".zip"):
        with zipfile.ZipFile(payload) as zf:
            safe_extract(zf, dest_dir, forbidden_suffixes=())
    else:
        with tarfile.open(fileobj=payload, mode="r:gz") as tf:
            _extract_tar(tf, dest_dir)
    for path in sorted(dest_dir.rglob(_binary_name())):
        path.chmod(0o755)
        return path
    raise UvNotFoundError(f"{asset} did not contain a uv binary")


def _extract_tar(tf: tarfile.TarFile, dest: Path) -> None:
    """Extract a uv tarball, refusing anything that is not a plain file inside ``dest``."""
    dest = dest.resolve()
    for member in tf.getmembers():
        if not member.isfile():
            continue
        target = (dest / member.name).resolve()
        if not target.is_relative_to(dest):
            raise UvNotFoundError(f"unsafe archive member {member.name!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source = tf.extractfile(member)
        if source is None:  # pragma: no cover - non-regular members are filtered above
            continue
        with source, target.open("wb") as out:
            shutil.copyfileobj(source, out)


class UvRunner:
    """Runs ``uv`` subcommands against one target interpreter.

    ``python`` is the interpreter of the *app* environment -- normally ``sys.executable``, so the
    manager installs packs into the very environment the server runs from (design 9: one shared
    environment, not one per pack).
    """

    def __init__(
        self,
        uv_path: Path | str | None = None,
        python: Path | str | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_S,
        env: dict[str, str] | None = None,
    ) -> None:
        self.uv_path = Path(uv_path) if uv_path else find_uv()
        self.python = Path(python) if python else Path(sys.executable)
        self.timeout = timeout
        self.env = env

    def version(self) -> str:
        """``uv``'s own version string (``uv 0.11.25``), or ``unknown`` when it will not talk."""
        result = self.run(["--version"], check=False)
        return result.stdout.strip().splitlines()[0] if result.ok and result.stdout else "unknown"

    def run(self, args: list[str], *, check: bool = True, timeout: float | None = None) -> UvResult:
        """Run ``uv <args>``; raises ``UvError`` when ``check`` and the command fails."""
        argv = [str(self.uv_path), *args]
        env = {**os.environ, **(self.env or {})}
        # uv colours its resolver diagnostics; plain text is what the parser and the UI want.
        env.setdefault("NO_COLOR", "1")
        try:
            completed = subprocess.run(  # noqa: S603 - argv is built from our own arguments
                argv,
                capture_output=True,
                text=True,
                # uv writes UTF-8 whatever the console code page is; decoding with the locale
                # encoding turns its box-drawing report into mojibake the parser cannot read.
                encoding="utf-8",
                errors="replace",
                timeout=timeout if timeout is not None else self.timeout,
                env=env,
                check=False,
            )
        except FileNotFoundError as exc:
            raise UvNotFoundError(f"{self.uv_path} could not be executed") from exc
        except subprocess.TimeoutExpired as exc:
            result = UvResult(tuple(argv), 124, "", f"uv timed out after {exc.timeout or 0:.0f}s")
            raise UvError("uv timed out", result) from exc
        result = UvResult(tuple(argv), completed.returncode, completed.stdout, completed.stderr)
        if check and not result.ok:
            raise UvError(f"uv {' '.join(args[:2])} failed", result)
        return result

    def pip(self, args: list[str], *, check: bool = True, timeout: float | None = None) -> UvResult:
        """``uv pip <args> --python <app interpreter>``."""
        return self.run(["pip", *args, "--python", str(self.python)], check=check, timeout=timeout)

    def freeze(self) -> list[str]:
        """``uv pip freeze`` as a sorted list of ``name==version`` requirement strings."""
        result = self.pip(["freeze"])
        return sorted(line.strip() for line in result.stdout.splitlines() if line.strip())


__all__ = [
    "UV_ASSETS",
    "UV_ENV_VAR",
    "UvError",
    "UvNotFoundError",
    "UvResult",
    "UvRunner",
    "download_uv",
    "find_uv",
]
