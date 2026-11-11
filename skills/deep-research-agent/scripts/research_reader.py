"""Bounded public-page reader, with DNS-pinned connections and no script execution."""
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit, urljoin, quote
from urllib.robotparser import RobotFileParser
import hashlib
import http.client
import ipaddress
import io
import re
import socket
import ssl
import threading
import time
from datetime import datetime, timezone


class ReadError(RuntimeError):
    pass


def canonical_url(url):
    if not isinstance(url, str) or any(ord(c) < 33 for c in url) or "\\" in url:
        raise ReadError("URL 包含无效字符")
    u = urlsplit(url)
    if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password:
        raise ReadError("仅允许不含凭据的 HTTP 或 HTTPS 页面")
    try:
        port = u.port
    except ValueError:
        raise ReadError("URL 端口无效") from None
    if port and port not in {80, 443}:
        raise ReadError("只允许公开网页的标准端口")
    hostname = u.hostname.encode("idna").decode().lower()
    authority = f"[{hostname}]" if ":" in hostname else hostname
    if port and port != (443 if u.scheme == "https" else 80):
        authority += f":{port}"
    return urlunsplit((u.scheme, authority, quote(u.path or "/", safe="/%:@!$&'()*+,;=-._~"),
                      quote(u.query, safe="%=&?/:@!$'()*+,;[]-._~"), ""))


def public_addresses(host, port):
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ReadError("DNS 解析失败") from None
    if not rows:
        raise ReadError("域名没有可连接地址")
    for row in rows:
        address = ipaddress.ip_address(row[4][0].split("%")[0])
        mapped = getattr(address, "ipv4_mapped", None)
        if not address.is_global or (mapped is not None and not mapped.is_global):
            raise ReadError("拒绝本地、内网或保留地址")
    return rows


def connect_public(host, port, timeout):
    # The socket connects to the validated address, without a second DNS lookup.
    rows = public_addresses(host, port)
    for family, kind, protocol, _, address in rows:
        sock = socket.socket(family, kind, protocol)
        sock.settimeout(timeout)
        try:
            sock.connect(address)
            return sock
        except OSError:
            sock.close()
    raise ReadError("无法连接页面主机")


class PublicHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock = connect_public(self.host, self.port, self.timeout)


class PublicHTTPS(http.client.HTTPSConnection):
    def connect(self):
        sock = connect_public(self.host, self.port, self.timeout)
        try:
            self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


class TextHTML(HTMLParser):
    skipped = {"script", "style", "nav", "footer", "header", "form", "noscript", "svg"}
    breaks = {"p", "div", "section", "article", "main", "li", "tr", "h1", "h2", "h3", "h4", "pre", "blockquote", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts = []
        self.title_parts = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.skipped:
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if not self.skip and tag in self.breaks:
            self.parts.append("\n\n")
        if not self.skip and tag in {"td", "th"}:
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.skipped:
            self.skip = max(0, self.skip - 1)
        if tag == "title":
            self.in_title = False
        if not self.skip and tag in self.breaks:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if self.in_title:
            self.title_parts.append(data)
        elif not self.skip:
            self.parts.append(data)

    def paragraphs(self):
        return [re.sub(r"\s+", " ", s).strip() for s in "".join(self.parts).split("\n\n")
                if len(re.sub(r"\s+", " ", s).strip()) >= 20]


def make_passages(text, page_ranges=None, size=1600):
    result = []
    # Offsets address the persisted normalized Unicode text, not raw HTML bytes.
    for match in re.finditer(r"[^\n]+", text):
        for start in range(match.start(), match.end(), size):
            end = min(start + size, match.end())
            if end - start < 20:
                continue
            page = next((p for a, b, p in page_ranges or [] if a <= start < b), None)
            result.append({"id": f"P{len(result)+1:04}", "start": start, "end": end,
                           "page": page, "text": text[start:end]})
    return result


def parse_article_xml(raw):
    import xml.etree.ElementTree as ET
    if b"<!ENTITY" in raw.upper():raise ReadError("拒绝包含自定义实体的 XML")
    try:root=ET.fromstring(raw)
    except ET.ParseError:raise ReadError("XML 解析失败") from None
    for node in root.iter():node.tag=node.tag.split("}")[-1]
    title=root.find(".//article-title")
    title=" ".join(title.itertext()).strip() if title is not None else ""
    chunks=[]
    if title:chunks.append(title)
    def flatten(node):
        if node.tag in {"title","article-title"}:
            return "\n\n## "+" ".join(node.itertext()).strip()+"\n\n"
        text=node.text or ""
        for child in node:
            text+=flatten(child)+(child.tail or "")
        return text+("\n\n" if node.tag in {"p","sec","table-wrap","fig","list-item"} else " ")
    for abstract in root.findall(".//article-meta/abstract"):
        chunks.append("## Abstract\n\n"+flatten(abstract))
    body=root.find(".//body")
    if body is not None:chunks.append(flatten(body))
    back=root.find(".//back")
    if back is not None:chunks.append(flatten(back))
    text="\n\n".join(chunks) if chunks else " ".join(root.itertext())
    text=re.sub(r"[ \t]+"," ",text)
    text=re.sub(r"\n{3,}","\n\n",text).strip()
    return title,text


class Reader:
    def __init__(self, timeout=30, max_bytes=8_000_000, max_chars=100000):
        self.timeout = min(timeout, 35)
        self.max_bytes = max_bytes
        self.max_chars = max_chars
        self.guard = threading.Lock()
        self.locks = {}
        self.robots = {}

    def _request(self, url, redirects=4, byte_limit=None, enforce_robots=False):
        url = canonical_url(url)
        for _ in range(redirects + 1):
            if enforce_robots and not self._allowed(url):
                raise ReadError("robots.txt 不允许读取此页面或重定向目标")
            u = urlsplit(url)
            cls = PublicHTTPS if u.scheme == "https" else PublicHTTP
            conn = cls(u.hostname, port=u.port or (443 if u.scheme == "https" else 80), timeout=self.timeout)
            try:
                path = u.path + ("?" + u.query if u.query else "")
                conn.request("GET", path, headers={"User-Agent": "EvidenceDeepSearch/0.1",
                             "Accept": "text/html,text/plain,application/pdf", "Accept-Encoding": "identity"})
                response = conn.getresponse()
                headers = response.headers
                if response.status in {301, 302, 303, 307, 308}:
                    location = headers.get("Location")
                    if not location:
                        raise ReadError("重定向没有 Location")
                    url = canonical_url(urljoin(url, location))
                    continue
                limit = byte_limit or self.max_bytes
                body = response.read(limit + 1)
                if len(body) > limit:
                    raise ReadError("页面超过读取大小上限")
                return response.status, headers, body, url
            finally:
                conn.close()
        raise ReadError("重定向次数超过上限")

    def _allowed(self, url):
        u = urlsplit(url)
        origin = f"{u.scheme}://{u.netloc}"
        if origin not in self.robots:
            status, _, body, _ = self._request(origin + "/robots.txt", byte_limit=500000)
            robot = RobotFileParser()
            if status == 404:
                robot.parse([])
            elif status in {401, 403}:
                robot.parse(["User-agent: *", "Disallow: /"])
            elif 200 <= status < 300:
                robot.parse(body.decode("utf-8", errors="replace").splitlines())
            else:
                raise ReadError("暂时无法确认 robots 访问规则")
            self.robots[origin] = robot
        return self.robots[origin].can_fetch("EvidenceDeepSearch", url)

    def read(self, url):
        url = canonical_url(url)
        with self.guard:
            lock = self.locks.setdefault(urlsplit(url).hostname, threading.Lock())
        with lock:
            if not self._allowed(url):
                raise ReadError("robots.txt 不允许读取此页面")
            status, headers, raw, final_url = self._request(url, enforce_robots=True)
            time.sleep(0.25)
        if not 200 <= status < 300:
            raise ReadError(f"页面 HTTP {status}")
        # Check permission again for a cross-origin final destination.
        if urlsplit(final_url).netloc != urlsplit(url).netloc and not self._allowed(final_url):
            raise ReadError("最终页面 robots 规则不允许使用")
        mime = headers.get_content_type()
        page_ranges = []
        truncated = False
        if mime == "application/pdf" or raw.startswith(b"%PDF-"):
            try:
                from pypdf import PdfReader
            except ImportError:
                raise ReadError("PDF 需要 python -m pip install pypdf；未把摘要作为全文") from None
            pdf = PdfReader(io.BytesIO(raw))
            pieces = []
            cursor = 0
            for i, page in enumerate(pdf.pages[:40]):
                text = re.sub(r"[ \t]+", " ", page.extract_text() or "").strip()
                pieces.append(text)
                page_ranges.append((cursor, cursor + len(text), i + 1))
                cursor += len(text) + 2
            body_text = "\n\n".join(pieces)
            truncated = len(pdf.pages) > 40
            title = str((pdf.metadata or {}).get("/Title", ""))
            extraction = "pdf_text"
        else:
            encoding = headers.get_content_charset() or "utf-8"
            decoded = raw.decode(encoding, errors="replace")
            if mime in {"application/xml","text/xml","application/jats+xml"}:
                title,body_text=parse_article_xml(raw)
                extraction="article_xml"
            elif mime in {"text/html", "application/xhtml+xml"}:
                parser = TextHTML(); parser.feed(decoded)
                body_text = "\n\n".join(parser.paragraphs())
                title = "".join(parser.title_parts).strip()
                extraction = "html_text"
            elif mime.startswith("text/"):
                body_text = decoded
                title = ""
                extraction = "plain_text"
            else:
                raise ReadError("页面类型不支持")
        from research_providers import looks_blocked
        if looks_blocked(body_text):
            raise ReadError("页面可能是登录、验证或访问限制页，未作为原文保存")
        if len(body_text) < 120:
            raise ReadError("正文过少，可能需要浏览器或 OCR")
        truncated = truncated or len(body_text) > self.max_chars
        body_text = body_text[:self.max_chars]
        return {"url": final_url, "title": title[:500], "text": body_text,
                "passages": make_passages(body_text, page_ranges), "extraction": extraction,
                "read_scope": "partial_text" if truncated else "parsed_text",
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "text_sha256": hashlib.sha256(body_text.encode()).hexdigest()}
