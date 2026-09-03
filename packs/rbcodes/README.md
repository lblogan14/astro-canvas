# astro-canvas-rbcodes

Node pack exposing [rbcodes](https://github.com/rongmon/rbcodes) (Rongmon Bordoloi) as Astro Canvas nodes.
Registers through the `astro_canvas.nodes` entry point `rbcodes` but ships no nodes until phase 05. Importing the
package pins `MPLBACKEND=Agg` and never imports `rbcodes` itself (Qt side effects); node modules import it lazily. See `docs/dev/rbcodes-compat.md` for the Python 3.12 compatibility status.
