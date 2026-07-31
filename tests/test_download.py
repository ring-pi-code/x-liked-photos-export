"""Tests for image downloading, end to end against a real local HTTP server."""

import asyncio
import functools
import http.server
import pathlib
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import aiohttp  # noqa: E402
import main  # noqa: E402


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serve files, ignoring any query string, without logging.

    Records the requested paths so tests can assert what was fetched.
    """

    requests: list = []

    def do_GET(self):
        type(self).requests.append(self.path)
        super().do_GET()

    def translate_path(self, path):
        return super().translate_path(path.split("?", 1)[0])

    def log_message(self, *args):
        pass


class TruncatingHandler(http.server.BaseHTTPRequestHandler):
    """Send a truncated body to simulate a connection drop mid-download."""

    def do_GET(self):
        body = b"short"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body) + 100))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def log_message(self, *args):
        pass


class DownloadImagesTest(unittest.TestCase):
    def setUp(self):
        QuietHandler.requests = []
        self.serve_dir = tempfile.TemporaryDirectory()
        self.out_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.serve_dir.cleanup)
        self.addCleanup(self.out_dir.cleanup)
        self.serve_path = pathlib.Path(self.serve_dir.name)
        self.out_path = pathlib.Path(self.out_dir.name)

    def serve_file(self, name, content):
        self.serve_path.joinpath(name).write_bytes(content)
        return content

    def start_server(self, handler_cls=QuietHandler):
        handler = handler_cls
        if handler_cls is QuietHandler:
            handler = functools.partial(QuietHandler, directory=self.serve_dir.name)
        server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_downloads_images_under_clean_filenames(self):
        content_a = self.serve_file("a.jpg", b"fake-jpeg-bytes-a")
        content_b = self.serve_file("b.jpg", b"fake-jpeg-bytes-b")
        port = self.start_server()

        posts = [
            {"images": [f"http://127.0.0.1:{port}/a.jpg?format=jpg&name=4096x4096"]},
            {"images": [f"http://127.0.0.1:{port}/b.jpg"]},
        ]

        asyncio.run(main.download_images(posts, self.out_path))

        # The query string must not leak into the saved filename.
        self.assertEqual((self.out_path / "a.jpg").read_bytes(), content_a)
        self.assertEqual((self.out_path / "b.jpg").read_bytes(), content_b)

    def test_existing_file_is_skipped(self):
        self.serve_file("a.jpg", b"server-version-a")
        content_b = self.serve_file("b.jpg", b"server-version-b")
        (self.out_path / "a.jpg").write_bytes(b"already-downloaded")
        port = self.start_server()

        posts = [
            {"images": [f"http://127.0.0.1:{port}/a.jpg"]},
            {"images": [f"http://127.0.0.1:{port}/b.jpg"]},
        ]

        asyncio.run(main.download_images(posts, self.out_path))

        self.assertEqual((self.out_path / "a.jpg").read_bytes(), b"already-downloaded")
        self.assertEqual((self.out_path / "b.jpg").read_bytes(), content_b)
        self.assertEqual(QuietHandler.requests, ["/b.jpg"])

    def test_interrupted_download_is_retried(self):
        content_a = self.serve_file("a.jpg", b"server-version-a")
        (self.out_path / "a.jpg.part").write_bytes(b"partial")
        port = self.start_server()

        posts = [{"images": [f"http://127.0.0.1:{port}/a.jpg"]}]

        asyncio.run(main.download_images(posts, self.out_path))

        self.assertEqual((self.out_path / "a.jpg").read_bytes(), content_a)
        self.assertFalse((self.out_path / "a.jpg.part").exists())

    def test_crash_leaves_no_partial_image(self):
        port = self.start_server(TruncatingHandler)

        posts = [{"images": [f"http://127.0.0.1:{port}/a.jpg"]}]

        with self.assertRaises(aiohttp.ClientPayloadError):
            asyncio.run(main.download_images(posts, self.out_path))

        # Nothing is written before the body arrives complete, so a crash
        # leaves no trace. The missing final file makes the next run retry.
        self.assertFalse((self.out_path / "a.jpg").exists())
        self.assertFalse((self.out_path / "a.jpg.part").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
