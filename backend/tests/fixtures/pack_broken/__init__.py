"""Fixture pack whose import fails (simulates a missing optional dependency)."""

raise ImportError("pack_broken needs the module 'definitely_not_installed'")
