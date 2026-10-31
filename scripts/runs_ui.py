"""Local web UI for browsing Harness² run outputs (harnesses, trajectories, answers, reports).

Stdlib only; read-only. Usage:

    python scripts/runs_ui.py [--root runs] [--host 127.0.0.1] [--port 8765]
"""

from __future__ import annotations

import argparse
import html
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".py", ".sh", ".yaml", ".yml", ".log", ".csv"}
MAX_BYTES = 2_000_000
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Harness² runs</title>
<style>
body{{margin:0;font:14px system-ui,sans-serif;display:flex;height:100vh;color:#222}}
nav{{width:360px;overflow:auto;border-right:1px solid #ddd;padding:8px;background:#fafafa}}
main{{flex:1;overflow:auto;padding:16px 24px}}
nav a{{text-decoration:none;color:#1a56db}} nav a.cur{{font-weight:bold;color:#000}}
details{{margin-left:10px}} summary{{cursor:pointer}} .f{{margin-left:22px;display:block}}
pre{{white-space:pre-wrap;background:#f6f8fa;padding:12px;border-radius:6px}}
h1{{font-size:18px}} .muted{{color:#777}} table{{border-collapse:collapse}}
td,th{{border:1px solid #ddd;padding:4px 8px;text-align:left}}
</style></head><body><nav><h1>Harness² runs</h1><div class="muted">{root}</div>{tree}</nav>
<main>{body}</main></body></html>"""


def build_tree(root: Path, cur: Path, d: Path) -> str:
    out = []
    try:
        entries = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
    except OSError as exc:
        return f"<span class='f muted'>unreadable: {html.escape(exc.strerror or str(exc))}</span>"
    for p in entries:
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            continue
        if p.is_dir():
            opened = " open" if cur == p or p in cur.parents else ""
            out.append(f"<details{opened}><summary>{html.escape(p.name)}/</summary>"
                       f"{build_tree(root, cur, p)}</details>")
        else:
            cls = ' class="cur"' if p == cur else ""
            q = urllib.parse.quote(rel)
            out.append(f'<a class="f"{cls} href="/?f={q}">{html.escape(p.name)}</a>')
    return "".join(out)


def demo_summary(data: dict) -> str:
    rows = "".join(
        f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(json.dumps(v)[:300])}</td></tr>"
        for k, v in data.items() if not isinstance(v, (dict, list)) or len(json.dumps(v)) < 300
    )
    return f"<table>{rows}</table>" if rows else ""


def render_file(path: Path) -> str:
    title = f"<h1>{html.escape(path.name)}</h1>"
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return title + "<p class='muted'>Binary or unsupported file type.</p>"
    with path.open("rb") as fh:
        raw = fh.read(MAX_BYTES).decode("utf-8", errors="replace")
    extra = ""
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(raw)
            raw = json.dumps(data, indent=2)
            if isinstance(data, dict):
                extra = demo_summary(data)
        except ValueError:
            pass
    return title + extra + f"<pre>{html.escape(raw)}</pre>"


def host_allowed(header: str | None, allowed: set[str] | None) -> bool:
    """Reject foreign Host headers so DNS-rebinding pages cannot read local runs."""
    if allowed is None:
        return True
    host = (header or "").strip().lower()
    if host.startswith("["):
        host = host[1:].split("]", 1)[0]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host in allowed


def make_handler(root: Path, allowed_hosts: set[str] | None = LOCAL_HOSTS):
    root = root.resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if not host_allowed(self.headers.get("Host"), allowed_hosts):
                return self.send_error(403, "Host not allowed")
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            rel = qs.get("f", [""])[0]
            try:
                target = (root / rel).resolve()
            except (OSError, ValueError):
                return self.send_error(400, "Invalid path")
            if target != root and root not in target.parents:
                return self.send_error(403)
            if not root.is_dir():
                body = "<p>No runs yet. Run <code>harness2-demo</code> first.</p>"
                tree = ""
            else:
                tree = build_tree(root, target, root)
                if target.is_file():
                    try:
                        body = render_file(target)
                    except OSError as exc:
                        body = f"<p class='muted'>Cannot read file: {html.escape(str(exc))}</p>"
                elif rel and not target.exists():
                    return self.send_error(404)
                else:
                    body = ("<h1>Select a file</h1><p class='muted'>Start with "
                            "<code>demo/demo.json</code> or a run's <code>trajectory.md</code>.</p>")
            data = PAGE.format(root=html.escape(str(root)), tree=tree, body=body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    return Handler


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--root", type=Path, default=Path("runs"))
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()
    root = args.root.expanduser().resolve()
    allowed = None if args.host in ("0.0.0.0", "::") else LOCAL_HOSTS | {args.host.lower()}
    server = ThreadingHTTPServer((args.host, args.port), make_handler(root, allowed))
    print(f"Harness2 runs UI: http://{args.host}:{args.port}/  (root: {root})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
