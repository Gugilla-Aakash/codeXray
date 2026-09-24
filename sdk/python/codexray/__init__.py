"""CodeXRay SDK — turn any Python ASGI app into a live system graph.

Zero dependencies. Failures to reach the API never propagate to your app.
"""

from .middleware import CodeXRayMiddleware
from .tracer import Span, Tracer, current_span, default_tracer, set_default_tracer

__version__ = "0.1.0"
__all__ = [
    "Tracer",
    "Span",
    "CodeXRayMiddleware",
    "current_span",
    "default_tracer",
    "set_default_tracer",
    "__version__",
]
