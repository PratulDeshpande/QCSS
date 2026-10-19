"""Address helpers shared by the server's bind guard and the client's token guard."""
from __future__ import annotations

import ipaddress


def is_local_address(address: str) -> bool:
    """True for loopback TCP addresses ('127.0.0.1:50051', 'localhost:1', '[::1]:1') and unix sockets."""
    if address.startswith(("unix:", "unix-abstract:")):
        return True
    host = address.rsplit(":", 1)[0].strip("[]")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False                                       # a hostname other than localhost may resolve anywhere
