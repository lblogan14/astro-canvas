"""``python -m astro_canvas.cli`` — the same entry point as the ``astro-canvas`` script.

Worth having on its own: it is how the wheel is smoke-tested without a console script on PATH,
and how anyone can run the app straight out of a virtual environment.
"""

from __future__ import annotations

from astro_canvas.cli import main

if __name__ == "__main__":
    main()
