"""Checks for the local runs browser in scripts/runs_ui.py."""

import importlib.util
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "runs_ui.py"
spec = importlib.util.spec_from_file_location("runs_ui", SCRIPT)
runs_ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runs_ui)


class RunsUiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.root = base / "runs"
        (self.root / "demo").mkdir(parents=True)
        (self.root / "demo" / "demo.json").write_text('{"done": 2, "failed": 0}')
        (self.root / "demo" / "notes.md").write_text("<script>x</script>")
        (base / "secret.txt").write_text("outside")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), runs_ui.make_handler(self.root))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/"

    def get(self, query=""):
        with urllib.request.urlopen(self.base + query) as response:
            return response.status, response.read().decode()

    def test_index_lists_files(self):
        status, body = self.get()
        self.assertEqual(status, 200)
        self.assertIn("demo.json", body)

    def test_json_is_rendered_with_summary(self):
        _, body = self.get("?f=demo/demo.json")
        self.assertIn("<th>done</th><td>2</td>", body)

    def test_file_content_is_escaped(self):
        _, body = self.get("?f=demo/notes.md")
        self.assertIn("&lt;script&gt;", body)
        self.assertNotIn("<script>x", body)

    def test_paths_outside_root_are_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("?f=../secret.txt")
        self.assertEqual(caught.exception.code, 403)

    def test_missing_file_returns_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("?f=demo/nope.md")
        self.assertEqual(caught.exception.code, 404)

    def test_foreign_host_header_is_rejected(self):
        request = urllib.request.Request(self.base, headers={"Host": "evil.example:8765"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)

    def test_host_allowed_parsing(self):
        allowed = runs_ui.LOCAL_HOSTS
        self.assertTrue(runs_ui.host_allowed("localhost:8765", allowed))
        self.assertTrue(runs_ui.host_allowed("[::1]:8765", allowed))
        self.assertFalse(runs_ui.host_allowed("evil.example", allowed))
        self.assertFalse(runs_ui.host_allowed(None, allowed))
        self.assertTrue(runs_ui.host_allowed("anything", None))


if __name__ == "__main__":
    unittest.main()
