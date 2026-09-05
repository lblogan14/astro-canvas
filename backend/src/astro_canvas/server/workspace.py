"""``/api/workspace``: select the workspace folder, list files, upload, inspect and download."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Literal

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from astro_canvas.server.deps import get_runtime
from astro_canvas.server.runtime import EngineRuntime
from astro_canvas.server.sniff import KIND_NODES, Kind, sniff_kind
from astro_canvas.store.files import Entry, FileInfo, list_dir
from astro_canvas.store.workspace import (
    SHARED_DIR,
    PathOutsideWorkspaceError,
    ReadOnlyPathError,
    Workspace,
)

router = APIRouter(tags=["workspace"])

UPLOAD_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
READ_CHUNK = 4 * 1024 * 1024


class WorkspaceInfo(BaseModel):
    """The active workspace and the user's recent ones."""

    root: str
    name: str
    recent: list[str] = []
    samples_dir: str = "samples"
    downloads_dir: str = "downloads"
    uploads_dir: str = "uploads"
    shared_dir: str | None = Field(
        default=None, description="Read-only mount on a lab server (design 12); ``null`` locally."
    )
    can_select: bool = Field(
        default=True, description="False when the server pins each user to their own workspace."
    )
    available: bool = Field(
        default=True,
        description="False when the workspace folder is gone (unplugged drive, unmounted "
        "share, deleted while the app was open). Everything else in this response still "
        "describes it, so the UI can name what it lost.",
    )


class SelectRequest(BaseModel):
    path: str = Field(description="Absolute path of the folder to open as the workspace.")
    create: bool = False


class EntryModel(BaseModel):
    path: str
    name: str
    is_dir: bool
    size: int = 0
    mtime: float = 0.0
    mime: str | None = None
    children: list[EntryModel] | None = Field(
        default=None, description="``None`` for folders not yet listed (lazy)."
    )


class TreeResponse(BaseModel):
    path: str
    entries: list[EntryModel]


class FileInfoModel(BaseModel):
    path: str
    name: str
    size: int
    mtime: float
    blake3: str | None = None
    mime: str | None = None


class UploadResult(BaseModel):
    upload_id: str | None = None
    received: int
    complete: bool
    file: FileInfoModel | None = None


class MkdirRequest(BaseModel):
    path: str


class SniffResult(BaseModel):
    path: str
    kind: Kind
    node: str | None = None
    detail: str = ""


def _workspace(request: Request) -> Workspace:
    return get_runtime(request).workspace


def _resolve(workspace: Workspace, relative: str, *, write: bool = False) -> Path:
    try:
        return workspace.safe_path(relative, write=write)
    except ReadOnlyPathError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except PathOutsideWorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


def _entry(entry: Entry) -> EntryModel:
    return EntryModel(
        path=entry.path,
        name=entry.name,
        is_dir=entry.is_dir,
        size=entry.size,
        mtime=entry.mtime,
        mime=entry.mime,
        children=None if entry.children is None else [_entry(c) for c in entry.children],
    )


def _file_info(info: FileInfo) -> FileInfoModel:
    return FileInfoModel(
        path=info.path,
        name=info.name,
        size=info.size,
        mtime=info.mtime,
        blake3=info.blake3,
        mime=info.mime,
    )


def _info(request: Request, runtime: EngineRuntime) -> WorkspaceInfo:
    workspace = runtime.workspace
    root = workspace.root
    pinned = getattr(request.app.state, "users", None) is not None
    return WorkspaceInfo(
        root=str(root),
        name=root.name or str(root),
        recent=[] if pinned else runtime.recent.list(),
        shared_dir=SHARED_DIR if workspace.shared is not None else None,
        can_select=not pinned,
        available=root.is_dir(),
    )


@router.get("/workspace", response_model=WorkspaceInfo)
async def workspace_info(request: Request) -> WorkspaceInfo:
    """The active workspace folder and recently used ones."""
    return _info(request, get_runtime(request))


@router.post("/workspace/select", response_model=WorkspaceInfo)
async def select_workspace(request: Request, body: SelectRequest) -> WorkspaceInfo:
    """Switch the server to another workspace folder (closing every open workflow)."""
    if getattr(request.app.state, "users", None) is not None:
        raise HTTPException(
            status_code=403,
            detail="this server keeps each user in their own workspace; it cannot be changed",
        )
    runtime = get_runtime(request)
    target = Path(body.path).expanduser()
    if not target.is_absolute():
        raise HTTPException(status_code=400, detail="workspace path must be absolute")
    try:
        await runtime.switch_workspace(target, create=body.create)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"no such folder: {target}") from None
    except NotADirectoryError:
        raise HTTPException(status_code=400, detail=f"not a folder: {target}") from None
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"cannot open workspace: {exc}") from None
    return _info(request, runtime)


@router.get("/workspace/tree", response_model=TreeResponse)
async def workspace_tree(
    request: Request,
    path: str = Query(default="", description="Workspace-relative folder (``''`` = root)."),
    depth: int = Query(default=1, ge=1, le=6),
    hidden: bool = False,
) -> TreeResponse:
    """Entries of a folder, folders first; nested folders beyond ``depth`` are listed lazily."""
    workspace = _workspace(request)
    directory = _resolve(workspace, path)
    if not directory.is_dir():
        if not workspace.root.is_dir():
            # The whole workspace has gone, not just this folder: say which one, because the
            # answer is to plug the drive back in or switch workspaces, not to retry.
            raise HTTPException(
                status_code=410,
                detail=f"the workspace folder is gone: {workspace.root}",
            )
        raise HTTPException(status_code=404, detail=f"no such folder: {path}")
    root, prefix = workspace.mount_for(directory)
    entries = [
        _entry(e)
        for e in await run_in_threadpool(
            list_dir, root, directory, depth=depth, hidden=hidden, prefix=prefix
        )
    ]
    relative = path.replace("\\", "/").strip("/")
    if not relative and workspace.shared is not None:
        entries.insert(0, _shared_entry(workspace))
    return TreeResponse(path=relative, entries=entries)


def _shared_entry(workspace: Workspace) -> EntryModel:
    """The read-only mount as one folder row at the top of the root listing."""
    shared = workspace.shared
    assert shared is not None  # noqa: S101 - only called when the mount exists
    mtime = shared.stat().st_mtime if shared.is_dir() else 0.0
    return EntryModel(path=SHARED_DIR, name=SHARED_DIR, is_dir=True, mtime=mtime)


@router.get("/workspace/info", response_model=FileInfoModel)
async def file_info(
    request: Request,
    path: str = Query(description="Workspace-relative file path."),
    hash: bool = Query(default=True, alias="hash"),  # noqa: A002
) -> FileInfoModel:
    """Size, mtime, MIME and blake3 (cached by path + mtime) of one file."""
    workspace = _workspace(request)
    target = _resolve(workspace, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"no such file: {path}")
    root, _ = workspace.mount_for(target)
    info = await run_in_threadpool(
        workspace.files.info, root, target, hash=hash, rel=workspace.relative(target)
    )
    return _file_info(info)


@router.get("/workspace/file", response_model=None)
async def download_file(
    request: Request, path: str = Query(description="Workspace-relative file path.")
) -> Response:
    """Download a workspace file."""
    workspace = _workspace(request)
    target = _resolve(workspace, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"no such file: {path}")
    return FileResponse(target, filename=target.name)


@router.get("/workspace/sniff", response_model=SniffResult)
async def sniff_file(
    request: Request, path: str = Query(description="Workspace-relative file path.")
) -> SniffResult:
    """Guess the data kind of a file and the ``core.io.load_*`` node that reads it."""
    workspace = _workspace(request)
    target = _resolve(workspace, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"no such file: {path}")
    kind, detail = await run_in_threadpool(sniff_kind, target)
    return SniffResult(
        path=workspace.relative(target), kind=kind, node=KIND_NODES.get(kind), detail=detail
    )


@router.post("/workspace/mkdir", response_model=EntryModel, status_code=status.HTTP_201_CREATED)
async def make_directory(request: Request, body: MkdirRequest) -> EntryModel:
    """Create a folder (and parents) inside the workspace."""
    workspace = _workspace(request)
    target = _resolve(workspace, body.path, write=True)
    if target == workspace.root:
        raise HTTPException(status_code=400, detail="cannot create the root")
    target.mkdir(parents=True, exist_ok=True)
    stat = target.stat()
    return EntryModel(
        path=workspace.relative(target), name=target.name, is_dir=True, mtime=stat.st_mtime
    )


@router.delete("/workspace/file", status_code=status.HTTP_204_NO_CONTENT)
async def delete_path(
    request: Request,
    path: str = Query(description="Workspace-relative file or (empty) folder."),
    recursive: bool = False,
) -> Response:
    """Delete a file, or a folder (``recursive=true`` removes its contents)."""
    workspace = _workspace(request)
    target = _resolve(workspace, path, write=True)
    if target in (workspace.root, workspace.state_dir):
        raise HTTPException(status_code=400, detail="refusing to delete that folder")
    if target.is_dir():
        if recursive:
            await run_in_threadpool(shutil.rmtree, target)
        else:
            try:
                target.rmdir()
            except OSError:
                raise HTTPException(status_code=409, detail="folder is not empty") from None
    elif target.is_file():
        target.unlink()
        workspace.files.forget(workspace.relative(target))
    else:
        raise HTTPException(status_code=404, detail=f"no such path: {path}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _unique_name(directory: Path, name: str) -> Path:
    candidate = directory / name
    stem, suffix = os.path.splitext(name)
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


@router.post("/workspace/upload", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_file(  # noqa: PLR0917 - multipart form fields
    request: Request,
    file: UploadFile = File(description="The file (or one chunk of it)."),  # noqa: B008
    dir: str = Form(default="uploads", description="Target folder, workspace-relative."),  # noqa: A002
    filename: str | None = Form(default=None),
    overwrite: bool = Form(default=False),
    on_conflict: Literal["error", "rename", "overwrite"] = Form(default="error"),
    upload_id: str | None = Form(default=None, description="Set for chunked uploads."),
    chunk_index: int = Form(default=0, ge=0),
    chunk_count: int = Form(default=1, ge=1),
) -> UploadResult:
    """Store an uploaded file in the workspace.

    Files above 100 MB should be sent as ordered chunks sharing an ``upload_id``; the file lands
    at its final path when the last chunk (``chunk_index == chunk_count - 1``) arrives.
    """
    workspace = _workspace(request)
    directory = _resolve(workspace, dir, write=True)
    directory.mkdir(parents=True, exist_ok=True)
    raw_name = filename or file.filename or "upload.bin"
    if raw_name in ("", ".", "..") or any(ch in raw_name for ch in ("/", "\\", chr(0))):
        raise HTTPException(status_code=400, detail="file name must not contain path separators")
    name = raw_name
    target = _resolve(
        workspace,
        f"{workspace.relative(directory)}/{name}" if directory != workspace.root else name,
        write=True,
    )
    conflict = "overwrite" if overwrite else on_conflict

    if chunk_count > 1:
        if upload_id is None or not UPLOAD_ID.match(upload_id):
            raise HTTPException(status_code=400, detail="chunked uploads need a valid upload_id")
        if chunk_index >= chunk_count:
            raise HTTPException(status_code=400, detail="chunk_index out of range")
        parts_dir = workspace.state_dir / "uploads"
        parts_dir.mkdir(parents=True, exist_ok=True)
        part = parts_dir / f"{upload_id}.part"
        mode = "wb" if chunk_index == 0 else "ab"
        if chunk_index > 0 and not part.exists():
            raise HTTPException(status_code=409, detail="chunk 0 was never received")
        received = await _write_stream(file, part, mode)
        if chunk_index < chunk_count - 1:
            return UploadResult(upload_id=upload_id, received=received, complete=False)
        target = _final_target(target, conflict)
        os.replace(part, target)
    else:
        target = _final_target(target, conflict)
        received = await _write_stream(file, target, "wb")

    workspace.files.forget(workspace.relative(target))
    info = await run_in_threadpool(
        workspace.files.info, workspace.root, target, hash=True, rel=workspace.relative(target)
    )
    return UploadResult(
        upload_id=upload_id, received=received, complete=True, file=_file_info(info)
    )


def _final_target(target: Path, conflict: str) -> Path:
    if target.exists():
        if target.is_dir():
            raise HTTPException(status_code=409, detail=f"{target.name} is a folder")
        if conflict == "error":
            raise HTTPException(status_code=409, detail=f"{target.name} already exists")
        if conflict == "rename":
            return _unique_name(target.parent, target.name)
    return target


async def _write_stream(file: UploadFile, target: Path, mode: str) -> int:
    total = 0
    with target.open(mode) as handle:
        while chunk := await file.read(READ_CHUNK):
            handle.write(chunk)
            total += len(chunk)
    return total


__all__ = ["router"]
