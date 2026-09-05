"""The page a click-to-run launcher shows while the app is still coming up.

The honest scope of this: PyApp downloads the interpreter and a few hundred megabytes of
scientific wheels *before* any of our Python runs, and only its own console output can report
that. What this covers is everything after -- importing astropy, pyarrow and both packs, running
the workspace migrations, and binding the port -- which on a cold cache is still long enough to
look broken.

So ``astro-canvas open --first-run`` writes a self-contained page next to the token file and
opens it immediately. The page polls ``/api/health`` and replaces itself with the app the moment
the server answers. No extra server, no port to fight over, and it works from a ``file://`` URL.
"""

from __future__ import annotations

from pathlib import Path

SPLASH_FILE = "starting.html"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Starting Astro Canvas</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    margin: 0; min-height: 100vh; display: grid; place-items: center;
    font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: #f6f7f9; color: #16181d;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0f1115; color: #e7e9ee; }}
    .card {{ background: #171a20; border-color: #262b34; }}
    .bar {{ background: #262b34; }}
  }}
  .card {{
    width: min(30rem, calc(100vw - 3rem));
    padding: 2rem; border: 1px solid #e2e5ea; border-radius: 12px; background: #fff;
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
  }}
  h1 {{ margin: 0 0 .35rem; font-size: 1.05rem; letter-spacing: -0.01em; }}
  p {{ margin: 0 0 1.25rem; opacity: .7; font-size: .875rem; }}
  .bar {{ height: 4px; border-radius: 999px; background: #e8ebf0; overflow: hidden; }}
  .bar span {{
    display: block; height: 100%; width: 35%; border-radius: 999px; background: #3b82f6;
    animation: slide 1.4s ease-in-out infinite;
  }}
  @keyframes slide {{
    0%   {{ transform: translateX(-100%); }}
    100% {{ transform: translateX(300%); }}
  }}
  .status {{
    margin-top: 1.25rem; font-size: .8125rem; opacity: .6;
    font-variant-numeric: tabular-nums;
  }}
  a {{ color: #3b82f6; }}
</style>
</head>
<body>
  <main class="card">
    <h1>Starting Astro Canvas</h1>
    <p>Loading the node packs and opening your workspace. The first start is the slow one.</p>
    <div class="bar" role="progressbar" aria-label="Starting"><span></span></div>
    <div class="status" id="status">waiting for the server…</div>
  </main>
<script>
  const target = {target!r};
  const health = {health!r};
  const status = document.getElementById('status');
  const started = Date.now();
  let attempts = 0;

  async function poll() {{
    attempts += 1;
    try {{
      const response = await fetch(health, {{ cache: 'no-store' }});
      if (response.ok) {{
        status.textContent = 'ready';
        window.location.replace(target);
        return;
      }}
    }} catch {{
      // Not listening yet: that is the normal case for the first few seconds.
    }}
    const seconds = Math.round((Date.now() - started) / 1000);
    status.textContent =
      seconds > 90
        ? `still starting after ${{seconds}}s — check the terminal window for errors`
        : `waiting for the server… ${{seconds}}s`;
    setTimeout(poll, attempts < 20 ? 400 : 1000);
  }}
  poll();
</script>
</body>
</html>
"""


def write_splash(config_dir: Path, url: str) -> Path:
    """Write the splash page for ``url`` into ``config_dir`` and return its path.

    Args:
        config_dir: Where the token file lives; the page goes next to it.
        url: The app URL to hand over to (token query parameter included).

    Returns:
        The path of the written page, or a page in a temporary directory if that folder is
        unwritable -- a splash screen is never worth failing a launch over.
    """
    base = url.split("?", 1)[0].rstrip("/") or url
    body = PAGE.format(target=url, health=f"{base}/api/health")
    path = Path(config_dir) / SPLASH_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path
    except OSError:
        import tempfile  # noqa: PLC0415 - only the fallback path needs it

        fallback = Path(tempfile.gettempdir()) / SPLASH_FILE
        fallback.write_text(body, encoding="utf-8")
        return fallback


def splash_url(path: Path) -> str:
    """``file://`` URL for a written splash page."""
    return Path(path).resolve().as_uri()


__all__ = ["SPLASH_FILE", "splash_url", "write_splash"]
