"""``--auth users``: logins, per-user isolation and the admin-only pack manager (design 12).

The acceptance case is the last three tests: two accounts log in, each sees only its own
workflows and its own workspace folder, and only the admin can reach ``/api/manager``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.app import create_app
from astro_canvas.server.users import COOKIE_NAME, ensure_secret, workspace_root
from astro_canvas.settings import Settings

ADMIN = {"email": "pi@lab.example", "password": "correct horse staple"}
MEMBER = {"email": "student@lab.example", "password": "another good phrase"}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace=tmp_path / "data",
        users_dir=tmp_path / "data" / "users",
        shared_dir=tmp_path / "data" / "shared",
        config_dir=tmp_path / "cfg",
        auth="users",
        # Its own SQLite file per test, even when the environment points at a shared Postgres.
        database_url="",
        host="0.0.0.0",
        process_pool=False,
        watch_workspace=False,
        admin_emails="PI@lab.example",
    )


@pytest.fixture
def client(settings: Settings, discovery: DiscoveryResult) -> Iterator[TestClient]:
    (Path(settings.shared_dir or "")).mkdir(parents=True, exist_ok=True)
    (Path(settings.shared_dir or "") / "atlas.txt").write_text("shared line list", encoding="utf-8")
    with TestClient(create_app(settings, discovery)) as client:
        yield client


def register(client: TestClient, who: dict[str, str], **extra: object) -> dict:
    response = client.post("/api/auth/register", json={**who, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, who: dict[str, str]) -> str:
    response = client.post(
        "/api/auth/login", data={"username": who["email"], "password": who["password"]}
    )
    assert response.status_code in (200, 204), response.text
    cookie = client.cookies.get(COOKIE_NAME)
    assert cookie, "the login did not set a session cookie"
    return cookie


def logout(client: TestClient) -> None:
    client.post("/api/auth/logout")
    client.cookies.clear()


# --- the login surface ----------------------------------------------------------------------


def test_health_and_auth_info_are_public(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    info = client.get("/api/auth/info")
    assert info.status_code == 200
    assert info.json() == {"mode": "users", "registration": True, "providers": []}


def test_everything_else_needs_a_login(client: TestClient) -> None:
    for path in ("/api/workflows", "/api/nodes", "/api/system", "/api/workspace", "/api/runs"):
        assert client.get(path).status_code == 401, path


def test_a_short_password_is_refused(client: TestClient) -> None:
    response = client.post("/api/auth/register", json={"email": "a@b.example", "password": "abc"})
    assert response.status_code == 400
    assert "at least 8" in response.text


def test_registering_creates_the_users_workspace(client: TestClient, settings: Settings) -> None:
    created = register(client, MEMBER, display_name="A Student")
    assert created["display_name"] == "A Student"
    assert created["is_superuser"] is False
    assert workspace_root(settings, uuid.UUID(created["id"])).is_dir()


def test_a_configured_address_becomes_an_admin(client: TestClient) -> None:
    """``admin_emails`` is matched case-insensitively so the operator cannot mistype it."""
    assert register(client, ADMIN)["is_superuser"] is True


def test_login_sets_a_cookie_and_me_answers(client: TestClient) -> None:
    register(client, MEMBER)
    login(client, MEMBER)
    me = client.get("/api/users/me")
    assert me.status_code == 200 and me.json()["email"] == MEMBER["email"]


def test_the_session_cookie_is_httponly_and_lax(client: TestClient, settings: Settings) -> None:
    register(client, MEMBER)
    response = client.post(
        "/api/auth/login", data={"username": MEMBER["email"], "password": MEMBER["password"]}
    )
    header = response.headers["set-cookie"].lower()
    assert "httponly" in header and "samesite=lax" in header
    # Plain HTTP in the test; behind TLS ``public_url`` turns the Secure flag on.
    assert "secure" not in header
    assert settings.secure_cookies is False


def test_https_deployment_marks_the_cookie_secure(tmp_path: Path) -> None:
    settings = Settings(
        workspace=tmp_path / "d",
        config_dir=tmp_path / "c",
        auth="users",
        public_url="https://canvas.lab.example",
    )
    assert settings.https and settings.secure_cookies


def test_a_bearer_token_works_for_scripts(client: TestClient) -> None:
    """The CLI and CI have no cookie jar, so the same JWT is accepted as a bearer token."""
    register(client, MEMBER)
    issued = client.post(
        "/api/auth/bearer/login",
        data={"username": MEMBER["email"], "password": MEMBER["password"]},
    )
    assert issued.status_code == 200, issued.text
    token = issued.json()["access_token"]
    client.cookies.clear()
    me = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["email"] == MEMBER["email"]


def test_a_forged_cookie_is_rejected(client: TestClient) -> None:
    register(client, MEMBER)
    client.cookies.set(COOKIE_NAME, "not.a.jwt")
    assert client.get("/api/users/me").status_code == 401


def test_registration_can_be_turned_off(tmp_path: Path, discovery: DiscoveryResult) -> None:
    settings = Settings(
        workspace=tmp_path / "d",
        config_dir=tmp_path / "c",
        auth="users",
        database_url="",
        registration=False,
        process_pool=False,
        watch_workspace=False,
    )
    with TestClient(create_app(settings, discovery)) as client:
        assert client.get("/api/auth/info").json()["registration"] is False
        assert client.post("/api/auth/register", json=MEMBER).status_code == 404


def test_the_signing_secret_survives_a_restart(tmp_path: Path) -> None:
    settings = Settings(
        workspace=tmp_path / "d", config_dir=tmp_path / "c", auth="users", database_url=""
    )
    first = ensure_secret(settings)
    assert (tmp_path / "c" / "secret").read_text(encoding="utf-8") == first
    assert ensure_secret(settings) == first


# --- isolation ------------------------------------------------------------------------------


def test_each_user_gets_their_own_workspace_and_workflows(
    client: TestClient, settings: Settings
) -> None:
    """Acceptance: two users log in, each sees only their own workspace."""
    member = register(client, MEMBER)
    admin = register(client, ADMIN)

    login(client, MEMBER)
    created = client.post(
        "/api/workflows", json={"id": "wf-mine", "name": "Student work", "nodes": {}, "edges": {}}
    )
    assert created.status_code == 201, created.text
    assert [w["id"] for w in client.get("/api/workflows").json()] == ["wf-mine"]
    member_root = client.get("/api/workspace").json()["root"]
    assert Path(member_root) == workspace_root(settings, uuid.UUID(member["id"]))
    logout(client)

    login(client, ADMIN)
    assert client.get("/api/workflows").json() == []
    assert client.get("/api/workflows/wf-mine").status_code == 404
    admin_root = client.get("/api/workspace").json()["root"]
    assert Path(admin_root) == workspace_root(settings, uuid.UUID(admin["id"]))
    assert admin_root != member_root


def test_a_user_cannot_repoint_the_server_at_another_folder(
    client: TestClient, tmp_path: Path
) -> None:
    register(client, MEMBER)
    login(client, MEMBER)
    response = client.post("/api/workspace/select", json={"path": str(tmp_path), "create": False})
    assert response.status_code == 403
    assert client.get("/api/workspace").json()["can_select"] is False


def test_the_shared_folder_is_visible_and_read_only(client: TestClient) -> None:
    register(client, MEMBER)
    login(client, MEMBER)
    info = client.get("/api/workspace").json()
    assert info["shared_dir"] == "shared"

    tree = client.get("/api/workspace/tree").json()
    assert any(entry["path"] == "shared" and entry["is_dir"] for entry in tree["entries"])

    listing = client.get("/api/workspace/tree?path=shared").json()
    assert [entry["path"] for entry in listing["entries"]] == ["shared/atlas.txt"]

    read = client.get("/api/workspace/file?path=shared/atlas.txt")
    assert read.status_code == 200 and read.text == "shared line list"

    for refused in (
        client.post("/api/workspace/mkdir", json={"path": "shared/new"}),
        client.delete("/api/workspace/file?path=shared/atlas.txt"),
    ):
        assert refused.status_code == 403, refused.text


def test_a_shared_file_keeps_its_prefix_in_its_metadata(client: TestClient) -> None:
    register(client, MEMBER)
    login(client, MEMBER)
    info = client.get("/api/workspace/info?path=shared/atlas.txt").json()
    assert info["path"] == "shared/atlas.txt" and info["blake3"]


# --- authority ------------------------------------------------------------------------------


def test_only_an_admin_reaches_the_pack_manager(client: TestClient) -> None:
    """Acceptance: the manager installs into the server's environment, so it is admin-only."""
    register(client, MEMBER)
    register(client, ADMIN)

    login(client, MEMBER)
    assert client.get("/api/manager/packs").status_code == 403
    logout(client)

    login(client, ADMIN)
    packs = client.get("/api/manager/packs")
    assert packs.status_code == 200
    assert {p["name"] for p in packs.json()} >= {"core"}


def test_trust_decisions_stay_with_the_user_who_made_them(client: TestClient) -> None:
    """A trust decision runs code, so it must not be shared the way an install is."""
    register(client, MEMBER)
    register(client, ADMIN)

    login(client, MEMBER)
    recorded = client.post("/api/manager/trust", json={"hash": "a" * 64, "decision": "trusted"})
    assert recorded.status_code == 200, recorded.text
    assert [r["hash"] for r in client.get("/api/manager/trust").json()] == ["a" * 64]
    logout(client)

    login(client, ADMIN)
    assert client.get("/api/manager/trust").json() == []


def test_the_websocket_needs_a_session(client: TestClient) -> None:
    register(client, MEMBER)
    with (
        pytest.raises(WebSocketDisconnect) as denied,
        client.websocket_connect("/ws?client_id=nobody"),
    ):
        pass  # pragma: no cover - the handshake must fail
    assert denied.value.code == 4401


def test_the_websocket_serves_the_users_own_engine(client: TestClient) -> None:
    """The event stream is per user too: the cookie decides which engine it is bound to."""
    register(client, MEMBER)
    login(client, MEMBER)
    created = client.post(
        "/api/workflows", json={"id": "wf-ws", "name": "Mine", "nodes": {}, "edges": {}}
    )
    assert created.status_code == 201, created.text
    with client.websocket_connect("/ws?client_id=t1") as socket:
        assert socket.receive_json()["type"] == "hello"
        socket.send_json({"type": "subscribe", "workflow_id": "wf-ws"})
        subscribed = socket.receive_json()
        assert subscribed["type"] == "subscribed" and subscribed["workflow_id"] == "wf-ws"
        # A workflow the *other* user stored is not reachable on this connection.
        socket.send_json({"type": "subscribe", "workflow_id": "wf-somebody-else"})
        for _ in range(20):
            event = socket.receive_json()
            if event["type"] == "error":
                assert "unknown workflow" in event["message"]
                break
        else:  # pragma: no cover - the error always arrives
            pytest.fail("no error event for the other user's workflow")
