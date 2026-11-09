"""Read a maker's own shop page to bring in her range (/open, "From your website").

This is an outbound call whose target a visitor types, so it is guarded like one (our rule, 03.11):
- https only, port 443, no user:password in the URL;
- the host is resolved once; every address it resolves to must be public (no private, loopback, link-local or cloud
  metadata, CGNAT, multicast or reserved ranges, IPv4 or IPv6), and the connection goes to that vetted address (with
  the certificate checked against the host name), so a DNS answer that changes between the check and the connect
  (DNS rebinding) can't send it anywhere else;
- at most 3 redirects, each one checked from scratch the same way;
- about 8 seconds (a deadline checked between reads, plus socket timeouts), 2 MB at most (counted after any gzip), text/html only, no cookies sent or kept.
Products come from the page's schema.org JSON-LD (Product / Offer) first; without it, the page's visible text goes
to the same price-list reader as a pasted list (a price is kept only if it is written on the page).
"""
from __future__ import annotations

import gzip
import html as htmllib
import ipaddress
import json
import re
import socket
import ssl
import time
import zlib
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 2_000_000
TIMEOUT_S = 8.0
MAX_REDIRECTS = 3
UA = "OpenCounter-RangeReader/1.0 (+https://open-counter.onrender.com/open; reads one page the shop owner asked for)"


class Refused(ValueError):
    """A URL or response we won't read; the message is shown to the maker."""


def _resolve(host: str) -> list[str]:
    """Every address the host resolves to (monkeypatched in tests)."""
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


def public_ip(a: str) -> bool:
    try:
        ip = ipaddress.ip_address(a.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour or ip.teredo):
        inner = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if inner is not None and not public_ip(str(inner)):
            return False
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local
                                 or ip.is_private or ip.is_unspecified)


def check_url(url: str) -> tuple[str, str, str]:
    """(host, path?query, vetted address) for a URL we may read, or Refused."""
    u = str(url or "").strip()
    if len(u) > 2000:
        raise Refused("That address is too long.")
    if not re.match(r"^https://", u, re.I):
        raise Refused("Use your shop's https:// address.")
    p = urlsplit(u)
    host = (p.hostname or "").rstrip(".").lower()
    if p.username or p.password or "@" in p.netloc:
        raise Refused("Use the shop's plain address, without a user name or password in it.")
    try:
        port = p.port
    except ValueError:
        raise Refused("That address has a port we can't read.")
    if port not in (None, 443):
        raise Refused("Use the shop's normal https address (no port number).")
    if not host or not re.fullmatch(r"[a-z0-9.-]+|\[?[0-9a-f:.]+\]?", host):
        raise Refused("That doesn't look like a web address.")
    if is_instagram(host):
        raise Refused(INSTAGRAM_SAYS)
    if host in ("localhost",) or host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".corp")):
        raise Refused("That address isn't on the public internet.")
    try:
        addrs = [str(ipaddress.ip_address(host.strip("[]")))]   # an IP literal: checked as it is, no DNS
    except ValueError:
        addrs = None
    try:
        addrs = addrs or _resolve(host)
    except (socket.gaierror, UnicodeError, OSError):
        raise Refused("We couldn't find that website.")
    if not addrs or not all(public_ip(a) for a in addrs):
        raise Refused("That address isn't on the public internet.")
    path = (p.path or "/") + (("?" + p.query) if p.query else "")
    return host, path, addrs[0]


INSTAGRAM_SAYS = ("Instagram doesn't let other sites read its pages, and we don't scrape it. For Instagram, add "
                  "screenshots of your posts instead (the \"Instagram screenshots\" tab).")


def is_instagram(host: str) -> bool:
    h = (host or "").lower().rstrip(".")
    return h in ("instagram.com", "instagr.am") or h.endswith((".instagram.com", ".instagr.am"))


def _request(ip: str, host: str, path: str, deadline: float):
    """GET over TLS to the vetted address with the host's name for SNI and certificate checks. Returns
    (status, headers dict lower-case, body bytes capped). Monkeypatched in tests."""
    import http.client

    class Pinned(http.client.HTTPSConnection):
        def connect(self):
            sock = socket.create_connection((ip, 443), timeout=max(0.5, deadline - time.time()))
            self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)

    conn = Pinned(host, 443, timeout=max(0.5, deadline - time.time()))
    try:
        conn.request("GET", path, headers={"Host": host, "User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
                                           "Accept-Encoding": "gzip, identity", "Connection": "close"})
        r = conn.getresponse()
        headers = {k.lower(): v for k, v in r.getheaders()}
        if r.status in (301, 302, 303, 307, 308):
            return r.status, headers, b""
        body = bytearray()
        while len(body) <= MAX_BYTES:
            if time.time() > deadline:
                raise Refused("That page took too long to load.")
            chunk = r.read(65536)
            if not chunk:
                break
            body += chunk
        return r.status, headers, bytes(body)
    finally:
        conn.close()


def _decoded(headers: dict, body: bytes) -> bytes:
    enc = (headers.get("content-encoding") or "identity").lower().strip()
    if enc in ("", "identity"):
        return body
    if enc in ("gzip", "x-gzip", "deflate"):
        d = zlib.decompressobj(16 + zlib.MAX_WBITS if "gzip" in enc else zlib.MAX_WBITS)
        out = d.decompress(body, MAX_BYTES + 1)
        if len(out) > MAX_BYTES:
            raise Refused("That page is too big to read (over 2 MB).")
        return out
    raise Refused("That page came back in a format we can't read.")


def fetch(url: str) -> tuple[str, str]:
    """(final URL, HTML text) of one public web page, or Refused."""
    deadline = time.time() + TIMEOUT_S
    for _ in range(MAX_REDIRECTS + 1):
        host, path, ip = check_url(url)
        try:
            status, headers, body = _request(ip, host, path, deadline)
        except Refused:
            raise
        except (socket.timeout, TimeoutError):
            raise Refused("That page took too long to load.")
        except ssl.SSLError:
            raise Refused("That site's https certificate didn't check out.")
        except OSError:
            raise Refused("We couldn't reach that website.")
        if status in (301, 302, 303, 307, 308):
            loc = headers.get("location") or ""
            if not loc:
                raise Refused("That page redirects nowhere.")
            url = urljoin(f"https://{host}{path}", loc)
            continue
        if status != 200:
            raise Refused(f"That page answered {status}.")
        if int(headers.get("content-length") or 0) > MAX_BYTES or len(body) > MAX_BYTES:
            raise Refused("That page is too big to read (over 2 MB).")
        ctype = (headers.get("content-type") or "").lower()
        if not ctype.startswith(("text/html", "application/xhtml+xml")):
            raise Refused("That address isn't a web page (we read HTML pages only).")
        raw = _decoded(headers, body)
        m = re.search(r"charset=([\w-]+)", ctype)
        try:
            return f"https://{host}{path}", raw.decode(m.group(1) if m else "utf-8", errors="replace")
        except LookupError:
            return f"https://{host}{path}", raw.decode("utf-8", errors="replace")
    raise Refused("That page redirects too many times.")


# ---- what's on the page ----
def _walk(x, out: list):
    if isinstance(x, list):
        for v in x:
            _walk(v, out)
    elif isinstance(x, dict):
        t = x.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(str(v).lower() in ("product", "productgroup") for v in types):
            out.append(x)
        for k in ("@graph", "itemListElement", "item", "mainEntity"):   # not hasVariant: one line per product
            if k in x:
                _walk(x[k], out)


def _offer_price(offers) -> tuple[str | None, str]:
    for o in offers if isinstance(offers, list) else [offers]:
        if not isinstance(o, dict):
            continue
        cur = str(o.get("priceCurrency") or (o.get("priceSpecification") or {}).get("priceCurrency") or "USD").upper()
        p = o.get("price") or o.get("lowPrice") or (o.get("priceSpecification") or {}).get("price")
        if p not in (None, ""):
            return str(p), cur
    return None, ""


def products_from_jsonld(page: str) -> list[dict]:
    """schema.org Products with a USD price, as raw items for pricelist.finish()."""
    found: list = []
    for m in re.finditer(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", page, re.I | re.S):
        try:
            _walk(json.loads(htmllib.unescape(m.group(1).strip())), found)
        except (json.JSONDecodeError, RecursionError):
            continue
    items = []
    for p in found[:60]:
        offers = p.get("offers")
        if not offers and isinstance(p.get("hasVariant"), list) and p["hasVariant"] and isinstance(p["hasVariant"][0], dict):
            offers = p["hasVariant"][0].get("offers")   # a product group: the first variant's price
        price, cur = _offer_price(offers)
        if price is None or cur != "USD":
            continue
        desc = p.get("description")
        items.append({"name": htmllib.unescape(str(p.get("name") or "")), "price_usd": price,
                      "description": htmllib.unescape(str(desc))[:400] if isinstance(desc, str) else None})
    return items


def visible_text(page: str) -> str:
    t = re.sub(r"<(script|style|noscript|svg|template|head|select|nav|footer|header|form|dialog)\b.*?</\1\s*>", " ",
               page, flags=re.I | re.S)
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<(br|/p|/div|/li|/tr|/h\d|/section|/article)\b[^>]*>", "\n", t, flags=re.I)
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", t))
    lines = [re.sub(r"[ \t ]+", " ", x).strip() for x in t.splitlines()]
    return "\n".join(x for x in lines if x)


_PRICED = re.compile(r"\$\s?\d|\d(?:\.\d\d)?\s?USD\b", re.I)


def priced_lines(text: str) -> str:
    """Only the parts of a page that carry a price: each priced line with the two lines before it (where a product's
    name usually is). Menus, country pickers and footers drop out, so the reader's 6,000 characters go to products."""
    lines = text.splitlines()
    keep = sorted({j for i, x in enumerate(lines) if _PRICED.search(x) for j in range(max(0, i - 2), i + 1)})
    return "\n".join(lines[j] for j in keep) if keep else text


def from_url(url: str, who=()) -> dict:
    """A maker's shop page → items to confirm (JSON-LD first, then the page's text through the list reader)."""
    from . import pricelist
    t0 = time.time()
    final, page = fetch(url)
    items, dropped = pricelist.finish(products_from_jsonld(page))
    if items:
        return {"items": items, "dropped": dropped, "read_by": "the page's schema.org product data (no AI)",
                "source": "website", "url": final, "seconds": round(time.time() - t0, 1)}
    text = priced_lines(visible_text(page))[:pricelist.MAX_TEXT]
    if not text.strip():
        raise Refused("That page has no text we can read (it may build itself with JavaScript). Paste your price list instead.")
    out = pricelist.from_text(text, who)
    return {**out, "source": "website", "url": final, "seconds": round(time.time() - t0, 1)}
