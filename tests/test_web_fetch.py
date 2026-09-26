"""Offline tests for the web_fetch tool.

Two layers, deliberately kept apart:
  - The SSRF guard (is_private_address / check_url_is_safe) is tested directly, with real IPs and
    with socket.getaddrinfo monkeypatched for the "resolves to a private address" cases — no
    network involved.
  - The actual fetch/redirect/HTML-conversion/size-cap behaviour is tested against a real
    http.server on 127.0.0.1. That address is loopback, so it's exactly what check_url_is_safe is
    designed to block — these tests monkeypatch check_url_is_safe itself out (via the
    `bypass_ssrf_check` fixture) to exercise the rest of the tool. That's fine: it's the same
    function unit-tested on its own above, we're just not re-triggering it here.
"""
import http.server
import json as json_mod
import socket
import threading

import pytest

from forge.tools import web_fetch
from forge.tools.base import ToolError


# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ip", [
    "127.0.0.1", "169.254.169.254", "169.254.1.1", "10.1.2.3", "192.168.1.1",
    "172.16.0.5", "0.0.0.0", "::1", "fe80::1",
])
def test_is_private_address_blocks_private_ranges(ip):
    assert web_fetch.is_private_address(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_is_private_address_allows_public_ranges(ip):
    assert web_fetch.is_private_address(ip) is False


def test_check_url_is_safe_rejects_non_http_scheme():
    with pytest.raises(ToolError, match="http"):
        web_fetch.check_url_is_safe("ftp://example.com/file")


def test_check_url_is_safe_rejects_file_scheme():
    with pytest.raises(ToolError):
        web_fetch.check_url_is_safe("file:///etc/passwd")


def test_check_url_is_safe_rejects_javascript_scheme():
    with pytest.raises(ToolError):
        web_fetch.check_url_is_safe("javascript:alert(1)")


def test_check_url_is_safe_rejects_metadata_ip(monkeypatch):
    # Simulate a hostname that resolves to the cloud metadata address.
    monkeypatch.setattr(
        web_fetch.socket, "getaddrinfo",
        lambda host, port: [(socket.AF_INET, 1, 6, "", ("169.254.169.254", 0))],
    )
    with pytest.raises(ToolError, match="private|SSRF"):
        web_fetch.check_url_is_safe("http://metadata.google.internal/latest/")


def test_check_url_is_safe_allows_public_ip(monkeypatch):
    monkeypatch.setattr(
        web_fetch.socket, "getaddrinfo",
        lambda host, port: [(socket.AF_INET, 1, 6, "", ("93.184.216.34", 0))],
    )
    web_fetch.check_url_is_safe("https://example.com/")  # must not raise


def test_check_url_is_safe_dns_failure(monkeypatch):
    def raise_gaierror(host, port):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(web_fetch.socket, "getaddrinfo", raise_gaierror)
    with pytest.raises(ToolError, match="resolve"):
        web_fetch.check_url_is_safe("http://nonexistent.invalid/")


# ---------------------------------------------------------------------------
# HTML -> text conversion
# ---------------------------------------------------------------------------
def test_html_to_text_strips_script_and_style():
    html = "<html><head><style>.x{color:red}</style></head><body>" \
           "<script>evil()</script><p>Hello</p></body></html>"
    out = web_fetch.html_to_text(html)
    assert "evil()" not in out
    assert "color:red" not in out
    assert "Hello" in out


def test_html_to_text_drops_nav():
    html = "<body><nav>Home | About</nav><p>Real content</p></body>"
    out = web_fetch.html_to_text(html)
    assert "Home" not in out
    assert "Real content" in out


def test_html_to_text_keeps_headings_and_links():
    html = "<h1>Title</h1><p>See <a href=\"https://x.test/y\">this link</a>.</p>"
    out = web_fetch.html_to_text(html)
    assert "# Title" in out
    assert "this link" in out
    assert "https://x.test/y" in out


def test_html_to_text_collapses_whitespace():
    html = "<p>a   b\n\n\n\nc</p>"
    out = web_fetch.html_to_text(html)
    assert "a b" in out
    assert "\n\n\n" not in out


# ---------------------------------------------------------------------------
# Local http.server for exercising the actual fetch path
# ---------------------------------------------------------------------------
class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # keep test output quiet

    def _send(self, status, body: bytes, content_type: str, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/html":
            body = (
                b"<html><head><style>.x{}</style><script>evil()</script></head>"
                b"<body><nav>NAVIGATION</nav><h1>Title</h1>"
                b"<p>Hello <a href=\"/x\">world</a>.</p></body></html>"
            )
            self._send(200, body, "text/html; charset=utf-8")
        elif self.path == "/json":
            body = json_mod.dumps({"a": 1, "b": [1, 2, 3]}).encode()
            self._send(200, body, "application/json")
        elif self.path == "/plain":
            self._send(200, b"hello   world\n\n\n\nagain", "text/plain")
        elif self.path == "/redirect-once":
            self._send(302, b"", "text/plain", {"Location": "/html"})
        elif self.path == "/redirect-loop":
            self._send(302, b"", "text/plain", {"Location": "/redirect-loop"})
        elif self.path == "/big":
            self._send(200, b"x" * (3 * 1024 * 1024), "text/plain")
        else:
            self._send(404, b"not found", "text/plain")


@pytest.fixture
def local_server():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def bypass_ssrf_check(monkeypatch):
    """127.0.0.1 is loopback, so check_url_is_safe would (correctly) refuse it. Bypass it here to
    test the rest of web_fetch against a real local server; the guard itself is tested above."""
    monkeypatch.setattr(web_fetch, "check_url_is_safe", lambda url: None)


# ---------------------------------------------------------------------------
# web_fetch end-to-end against the local server
# ---------------------------------------------------------------------------
def test_web_fetch_converts_html_to_text(local_server, bypass_ssrf_check):
    out = web_fetch.web_fetch(f"{local_server}/html")
    assert "untrusted data" in out
    assert local_server in out
    assert "NAVIGATION" not in out
    assert "evil()" not in out
    assert "Title" in out
    assert "world" in out
    assert "/x" in out


def test_web_fetch_json_pretty_printed(local_server, bypass_ssrf_check):
    out = web_fetch.web_fetch(f"{local_server}/json")
    assert '"a": 1' in out
    assert '"b"' in out


def test_web_fetch_plain_text_passthrough(local_server, bypass_ssrf_check):
    out = web_fetch.web_fetch(f"{local_server}/plain")
    assert "hello" in out
    assert "again" in out


def test_web_fetch_follows_redirect(local_server, bypass_ssrf_check):
    out = web_fetch.web_fetch(f"{local_server}/redirect-once")
    assert "Title" in out  # landed on /html


def test_web_fetch_caps_redirects(local_server, bypass_ssrf_check):
    with pytest.raises(ToolError, match="redirect"):
        web_fetch.web_fetch(f"{local_server}/redirect-loop")


def test_web_fetch_size_cap(local_server, bypass_ssrf_check):
    out = web_fetch.web_fetch(f"{local_server}/big", max_chars=10_000_000)
    assert len(out) < web_fetch.MAX_BYTES + 1000
    assert "truncated" in out


def test_web_fetch_max_chars_truncates(local_server, bypass_ssrf_check):
    out = web_fetch.web_fetch(f"{local_server}/plain", max_chars=5)
    assert "chars truncated" in out


def test_web_fetch_404_raises_tool_error(local_server, bypass_ssrf_check):
    with pytest.raises(ToolError, match="404"):
        web_fetch.web_fetch(f"{local_server}/missing")


def test_web_fetch_rejects_non_http_scheme_without_server():
    # No local server / bypass needed: the scheme check happens before any network access.
    with pytest.raises(ToolError):
        web_fetch.web_fetch("ftp://example.com/file")


def test_web_fetch_blocks_loopback_by_default(local_server):
    # Without the bypass fixture, the real SSRF guard should refuse 127.0.0.1.
    with pytest.raises(ToolError, match="private|SSRF|loopback"):
        web_fetch.web_fetch(f"{local_server}/html")
