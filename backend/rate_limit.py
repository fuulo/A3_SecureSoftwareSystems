"""Per-client request limits (slowapi).

Behind the load balancer (docker-compose.yml) every API instance keeps its
counts in one shared Redis, so a client has the same limit whichever instance
answers. The client is then the address the edge proxy puts in
X-Forwarded-For, not the proxy itself.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from backend.config import RATE_LIMIT_STORAGE_URI, TRUST_PROXY_HEADERS


def client_address(request: Request) -> str:
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            # The edge proxy replaces, not appends to, this header (infra/haproxy.cfg)
            return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=client_address,
    storage_uri=RATE_LIMIT_STORAGE_URI,
    # If Redis is unreachable, each instance counts on its own instead of
    # failing every request
    in_memory_fallback_enabled=True,
)
