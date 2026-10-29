"""Small network checks for roles/network_verify, using only Python's
standard library, so they run on the VMs and on this machine alike.

    probe.py tcp HOST PORT [TIMEOUT]
        open, refused, timeout or unreachable
    probe.py https HOST PORT NAME [TIMEOUT]
        the HTTP status code of GET https://NAME/ sent to HOST:PORT, or
        closed (connection dropped without an answer), refused, timeout,
        unreachable, or error:<reason>. Certificates aren't checked.
    probe.py resolve NAME
        the first IPv4 address of NAME, or nothing
"""

import socket
import ssl
import sys


def classify(error):
    if isinstance(error, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(error, ConnectionRefusedError):
        return "refused"
    if isinstance(error, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, ssl.SSLEOFError)):
        return "closed"
    if isinstance(error, OSError) and error.errno in (101, 113):  # network / host unreachable
        return "unreachable"
    return f"error:{type(error).__name__}"


def tcp(host, port, timeout=5):
    try:
        with socket.create_connection((host, int(port)), timeout=float(timeout)):
            return "open"
    except OSError as error:
        return classify(error)


def https(host, port, name, timeout=10):
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, int(port)), timeout=float(timeout)) as raw:
            with context.wrap_socket(raw, server_hostname=name) as conn:
                conn.sendall(f"GET / HTTP/1.1\r\nHost: {name}\r\nConnection: close\r\n\r\n".encode())
                line = conn.recv(64).decode(errors="replace")
                if not line:
                    return "closed"
                parts = line.split()
                return parts[1] if len(parts) > 1 and parts[0].startswith("HTTP/") else "error:not-http"
    except ssl.SSLError as error:
        # An abort during the handshake shows up as an SSL error.
        return "closed" if "EOF" in str(error) or "reset" in str(error).lower() else f"error:{error.reason}"
    except OSError as error:
        return classify(error)


def resolve(name):
    try:
        return socket.getaddrinfo(name, None, socket.AF_INET)[0][4][0]
    except OSError:
        return ""


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    print({"tcp": tcp, "https": https, "resolve": resolve}[mode](*args))
