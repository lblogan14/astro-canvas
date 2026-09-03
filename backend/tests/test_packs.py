"""Workspace packs are installed editable alongside the app."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize("name", ["astro_canvas_core", "astro_canvas_rbcodes"])
def test_pack_imports_cleanly(name: str) -> None:
    module = importlib.import_module(name)
    assert module.__version__ == "0.1.0a0"
