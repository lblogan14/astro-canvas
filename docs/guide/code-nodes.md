# The Python code node (phase 11)

`core.code.python` runs a snippet you write as a node on the canvas. It is the escape hatch for
the step no pack has a node for yet — and the fastest way to find out whether an idea is worth
turning into one.

## Declaring its ports

A code node has no fixed shape: **you declare its ports**, and the canvas grows handles to match.

- **Inputs** — one row per input port: a name and a port type. The name is bound to that value
  inside your snippet.
- **Outputs** — the same, read back from the name after the snippet runs.

A name must be a plain Python identifier. A row you have not finished typing is simply ignored,
so the node stays editable; the compiler reports the missing port instead.

```python
# inputs:  spec (astro.Spectrum1D),  z (astro.Float)
# outputs: rest (astro.Spectrum1D)
import numpy as np

rest = spec.model_copy(update={"wave": np.asarray(spec.wave) / (1 + z)})
```

Scalar-ish types (`astro.Float`, `astro.Int`, `astro.Str`, `astro.Bool`, `astro.Json`,
`astro.Any`) arrive as the plain Python value. Every other port type arrives as its model, so
`spec.wave`, `spec.flux` and `spec.model_copy(...)` work as they do inside a pack.

## What else is in scope

- `ctx` — the usual node context: `ctx.progress(0.5, "halfway")`, `ctx.log("info", …)`,
  `ctx.is_cancelled()`, `ctx.scratch_dir`, `ctx.workspace`.
- `print(...)` — captured and shown in the node's log rather than the server's.
- Anything you import, within the restrictions below.

The node's cost is `auto`, so a snippet that stays fast runs reactively, and one that grows past
two seconds stops re-running on every keystroke and waits for **Run**.

## The restrictions

Outside the `permissive` security level, a snippet may not import the process-, filesystem- and
network-shaped modules (`os`, `sys`, `subprocess`, `socket`, `pathlib`, `shutil`, `pickle`,
`urllib`, `httpx`, `requests`, `ctypes`, `importlib`, …), and `open`, `eval`, `exec` and
`compile` are not in scope. Imports are refused twice over: statically, so the error names the
line, and again at import time, so `__import__("os")` fails too.

`numpy`, `astropy`, `scipy` and everything else scientific import normally.

Raise the level in **Manager ▸ Settings ▸ Security** to *Permissive* to lift all of it.

This is a speed bump, not a jail: Python cannot be made safe against a determined attacker
in-process. It keeps honest snippets honest and makes the common mistakes loud. The protection
that actually matters is the trust gate.

## The trust gate

Code **you** write is trusted the moment you save it. Code that arrives from outside — inside an
imported [bundle](bundles.md) — does not run until you have read it: the workflow opens
quarantined, the code nodes report why, and *Review code* shows each snippet in full before
asking for a decision.

Decisions are per **snippet hash**, not per node or per workflow. Trusting a snippet enables
every node carrying exactly that text, and changing one character makes it a different snippet
that needs deciding again.

## Errors

A failure is reported against the snippet, not against the engine:

```
line 3: ZeroDivisionError: division by zero
```

A syntax error is caught before anything runs; an unassigned output says which name is missing.

## When to stop using it

A code node is a fine place to prototype and a poor place to keep science. When a snippet
settles, move it into a pack: a `@node`-decorated function gets a docstring the UI shows, typed
ports, a version, caching by content, and tests. See
[the node schema](../formats/node-schema.md) and
[publishing a pack](../packs/publishing.md).
