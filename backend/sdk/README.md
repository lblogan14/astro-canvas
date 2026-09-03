# astro-canvas-sdk

The node SDK for [Astro Canvas](https://github.com/lblogan14/astro-canvas) packs: the `@node`
decorator, `Param`, `NodeContext`, `@port_type`, `NodeSpec` and the registry. It provides the
`astro_canvas.sdk` namespace portion so packs can depend on it without pulling in the FastAPI app.

```python
from typing import Annotated
from astro_canvas.sdk import Param, node


@node(id="mypack.math.scale", name="Scale", category="Math")
def scale(x: float, factor: Annotated[float, Param(min=0, max=10)] = 2.0) -> float:
    """Multiply ``x`` by ``factor``.

    Args:
        x: Input value.
        factor: Multiplier.
    """
    return x * factor
```

Managed with uv as a member of the `backend/` workspace; published separately as `astro-canvas-sdk`.
