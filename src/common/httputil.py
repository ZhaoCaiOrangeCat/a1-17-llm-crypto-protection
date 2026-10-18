import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import urllib.parse


_local = threading.local()


def _connection(host, port, timeout):
    conns = getattr(_local, "conns", None)
    if conns is None:
        conns = {}
        _local.conns = conns
    key = (host, port)
    conn = conns.get(key)
    if conn is None:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conns[key] = conn
    conn.timeout = timeout
    return conn


def _drop(host, port):
    conns = getattr(_local, "conns", None)
    if not conns:
        return
    conn = conns.pop((host, port), None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            return


def _request(method, url, data, timeout):
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or "/"
    if parsed.query:
        path = path + "?" + parsed.query
    headers = {"Connection": "close"}
    if data is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        headers["Content-Length"] = str(len(data))
    last = None
    for _ in range(2):
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            raw = resp.read()
            conn.close()
            return status, raw
        except Exception as exc:
            last = exc
            try:
                conn.close()
            except Exception:
                pass
    raise RuntimeError(f"HTTP {url} {last}")


def post_json(url, obj, timeout=30):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    status, raw = _request("POST", url, data, timeout)
    text = raw.decode("utf-8", "replace")
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError:
        payload = {"ok": False, "error": "HTTP", "detail": text[:300]}
    return status, payload


def get_json(url, timeout=10):
    status, raw = _request("GET", url, None, timeout)
    if status >= 400:
        raise RuntimeError(f"HTTP {status} {url}")
    return json.loads(raw.decode("utf-8"))


class PoolHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def process_request(self, request, client_address):
        thread = threading.Thread(
            target=self.process_request_thread,
            args=(request, client_address),
            daemon=True,
        )
        thread.start()


def serve(host, port, routes, wire_sink=None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method):
            path = self.path.split("?", 1)[0]
            query = ""
            if "?" in self.path:
                query = self.path.split("?", 1)[1]
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if length else b""
            sink = getattr(self.server, "wire_sink", None)
            if sink is not None:
                sink(path, raw)
            body = {}
            if raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    self._send(400, {"ok": False, "error": "JSON"})
                    return
            handler = routes.get((method, path))
            if handler is None:
                self._send(404, {"ok": False, "error": "NOT_FOUND", "path": path})
                return
            try:
                status, payload = handler(body, query)
            except Exception as exc:
                status, payload = 200, {"ok": False, "error": "SERVER", "detail": str(exc)}
            self._send(status, payload)

        def _send(self, status, payload):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.close_connection = True
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            return

    httpd = PoolHTTPServer((host, port), Handler)
    httpd.wire_sink = wire_sink
    thread = threading.Thread(target=httpd.serve_forever, name=f"http-{port}", daemon=True)
    thread.start()
    return httpd
