"""The registry client: schema validation, search, the 1 h cache, ETag revalidation, fallbacks."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from astro_canvas.manager.registry import (
    BUILTIN_INDEX,
    RegistryClient,
    parse_index,
)

REPO_SEED = Path(__file__).resolve().parents[3] / "registry" / "index.json"
URL = "https://registry.example/index.json"

SAMPLE = [
    {
        "name": "astro-canvas-demo",
        "display_name": "Demo pack",
        "publisher": "someone",
        "description": "A demonstration pack with spectra nodes.",
        "source": "astro-canvas-demo>=0.2",
        "latest": "0.2.0",
        "categories": ["Spectra"],
        "templates": [{"id": "demo.hello", "name": "Hello"}],
    },
    {"name": "astro-canvas-other", "source": "astro-canvas-other", "categories": ["IFU"]},
]


def test_the_repo_seed_and_the_shipped_copy_are_identical() -> None:
    """``registry/index.json`` is the source of truth; the wheel ships a byte-identical copy."""
    assert json.loads(BUILTIN_INDEX.read_text(encoding="utf-8")) == json.loads(
        REPO_SEED.read_text(encoding="utf-8")
    )


def test_the_seed_lists_both_first_party_packs() -> None:
    index = parse_index(json.loads(REPO_SEED.read_text(encoding="utf-8")))
    assert {e.name for e in index.entries} == {"astro-canvas-core", "astro-canvas-rbcodes"}
    rbcodes = next(e for e in index.entries if e.name == "astro-canvas-rbcodes")
    assert {t.id for t in rbcodes.templates} == {
        "rbcodes.absorption",
        "rbcodes.redshift",
        "rbcodes.multispec",
        "rbcodes.ifu",
    }


def test_an_object_wrapper_is_accepted_too() -> None:
    assert len(parse_index({"packs": SAMPLE}).entries) == 2


def test_a_malformed_entry_is_skipped_not_fatal() -> None:
    index = parse_index([*SAMPLE, {"display_name": "no name, no source"}])
    assert [e.name for e in index.entries] == ["astro-canvas-demo", "astro-canvas-other"]


def test_a_payload_that_is_not_a_list_is_rejected() -> None:
    with pytest.raises(ValueError, match="list of pack entries"):
        parse_index("nope")


def test_search_matches_name_description_and_category() -> None:
    index = parse_index(SAMPLE)
    assert [e.name for e in index.search("demonstration")] == ["astro-canvas-demo"]
    assert [e.name for e in index.search("", "IFU")] == ["astro-canvas-other"]
    assert index.search("nothing here") == []
    assert len(index.search("")) == 2


def test_a_local_file_url_is_read_directly(tmp_path: Path) -> None:
    path = tmp_path / "index.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    client = RegistryClient(str(path))
    assert [e.name for e in client.fetch().entries] == [
        "astro-canvas-demo",
        "astro-canvas-other",
    ]
    assert client.entry("astro_canvas_demo") is not None


@respx.mock
def test_a_fetch_is_cached_for_an_hour_and_revalidated_with_an_etag(tmp_path: Path) -> None:
    route = respx.get(URL).mock(
        return_value=httpx.Response(200, json=SAMPLE, headers={"ETag": '"v1"'})
    )
    client = RegistryClient(URL, tmp_path)

    assert len(client.fetch().entries) == 2
    assert client.fetch().entries  # inside the TTL: no second request
    assert route.call_count == 1

    route.mock(return_value=httpx.Response(304))
    assert len(client.fetch(refresh=True).entries) == 2
    assert route.call_count == 2
    assert route.calls[1].request.headers["If-None-Match"] == '"v1"'


@respx.mock
def test_the_cache_survives_a_new_client(tmp_path: Path) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=SAMPLE, headers={"ETag": '"v1"'}))
    RegistryClient(URL, tmp_path).fetch()

    offline = RegistryClient(URL, tmp_path)
    assert (tmp_path / "registry-cache.json").is_file()
    assert len(offline.fetch().entries) == 2


@respx.mock
def test_a_network_failure_serves_the_stale_cache(tmp_path: Path) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json=SAMPLE))
    client = RegistryClient(URL, tmp_path)
    client.fetch()

    respx.get(URL).mock(side_effect=httpx.ConnectError("offline"))
    index = client.fetch(refresh=True)
    assert index.stale and index.error
    assert len(index.entries) == 2


@respx.mock
def test_a_first_fetch_that_fails_falls_back_to_the_shipped_index(tmp_path: Path) -> None:
    """The Registry tab is useful on a machine that has never reached the network."""
    respx.get(URL).mock(side_effect=httpx.ConnectError("offline"))
    index = RegistryClient(URL, tmp_path).fetch()
    assert index.stale and index.error == "offline"
    assert {e.name for e in index.entries} == {"astro-canvas-core", "astro-canvas-rbcodes"}
