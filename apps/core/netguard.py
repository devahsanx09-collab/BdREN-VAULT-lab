"""Resolve SSH / ping targets and reject destinations the server must never connect to.

Always refused: loopback, link-local, multicast, unspecified and reserved addresses.
Optional allow-list: when DBMS_ALLOWED_NETWORKS is set (comma-separated networks, for example
10.0.0.0/8,103.28.121.0/24), a device is used only when EVERY address it resolves to lies inside
one of them. Unset = any ordinary address is allowed. DNS is resolved once and the chosen
address is pinned for the SSH connection.
"""
import ipaddress
import socket


def _resolve(host):
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        try:
            return sorted({ipaddress.ip_address(info[4][0])
                           for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)},
                          key=lambda a: (a.version, int(a)))
        except (OSError, ValueError):
            return []


def _networks():
    """The allow-list from settings; [] when none is configured. Raises ValueError for a bad entry."""
    from django.conf import settings
    return [ipaddress.ip_network(item, strict=False) for item in getattr(settings, "ALLOWED_DEVICE_NETWORKS", [])]


def resolve_allowed_host(host):
    """Return a pinned destination IP, or None for an invalid, special-use or not-allowed address."""
    addresses = _resolve(host)
    if not addresses:
        return None
    # "::ffff:127.0.0.1" is the IPv4 loopback written as IPv6; Python before 3.13 does not call it loopback,
    # so judge the IPv4 address inside it.
    addresses = [getattr(a, "ipv4_mapped", None) or a for a in addresses]
    forbidden = lambda a: (a.is_loopback or a.is_link_local or a.is_multicast
                           or a.is_unspecified or a.is_reserved)
    if any(forbidden(address) for address in addresses):
        return None
    try:
        networks = _networks()
    except ValueError:
        return None                      # a broken allow-list must not silently allow everything
    if networks and not all(any(a.version == n.version and a in n for n in networks) for a in addresses):
        return None
    return str(addresses[0])


def host_allowed(host):
    """Compatibility helper: true when host resolves to a usable destination."""
    return resolve_allowed_host(host) is not None
