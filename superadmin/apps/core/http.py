"""HTTP helpers shared across apps."""

from django.conf import settings

# Set by EdgeProxyMiddleware only for a request that carried the edge Worker's secret.
EDGE_CLIENT_IP_KEY = "vitalos.edge_client_ip"


def client_ip(request, *args, **kwargs) -> str:
    """Resolve the client IP, trusting X-Forwarded-For only for the configured proxy hops.

    Behind the Cloudflare edge Worker the last hop is Cloudflare's egress address, shared by every visitor, so a
    verified edge request uses the CF-Connecting-IP value the middleware recorded instead.
    """
    edge_ip = request.META.get(EDGE_CLIENT_IP_KEY)
    if edge_ip:
        return edge_ip
    remote_addr = request.META.get("REMOTE_ADDR", "")
    proxies = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if proxies > 0 and forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if len(hops) >= proxies:
            return hops[-proxies]
    return remote_addr
