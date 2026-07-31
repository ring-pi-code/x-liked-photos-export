"""Tests for image downloading, end to end against a real local HTTP server."""

import asyncio
import functools
import http.server
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

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


class TrackingHandler(QuietHandler):
    """Serve files with a small delay, tracking simultaneous requests."""

    delay = 0.05
    in_flight = 0
    max_in_flight = 0
    lock = threading.Lock()

    def do_GET(self):
        cls = type(self)
        with cls.lock:
            cls.in_flight += 1
            cls.max_in_flight = max(cls.max_in_flight, cls.in_flight)
        try:
            time.sleep(cls.delay)
            super().do_GET()
        finally:
            with cls.lock:
                cls.in_flight -= 1


class DownloadImagesTest(unittest.TestCase):
    def setUp(self):
        QuietHandler.requests = []
        TrackingHandler.in_flight = 0
        TrackingHandler.max_in_flight = 0
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
        if issubclass(handler_cls, http.server.SimpleHTTPRequestHandler):
            handler = functools.partial(handler_cls, directory=self.serve_dir.name)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
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
        (self.out_path / ".a.jpg.part").write_bytes(b"partial")
        port = self.start_server()

        posts = [{"images": [f"http://127.0.0.1:{port}/a.jpg"]}]

        asyncio.run(main.download_images(posts, self.out_path))

        self.assertEqual((self.out_path / "a.jpg").read_bytes(), content_a)
        self.assertFalse((self.out_path / ".a.jpg.part").exists())

    def test_crash_leaves_no_partial_image(self):
        port = self.start_server(TruncatingHandler)

        posts = [{"images": [f"http://127.0.0.1:{port}/a.jpg"]}]

        with self.assertRaises(aiohttp.ClientPayloadError):
            asyncio.run(main.download_images(posts, self.out_path))

        # Nothing is written before the body arrives complete, so a crash
        # leaves no trace. The missing final file makes the next run retry.
        self.assertFalse((self.out_path / "a.jpg").exists())
        self.assertFalse((self.out_path / ".a.jpg.part").exists())

    def test_downloads_in_parallel_when_concurrency_allows(self):
        contents = {f"{c}.jpg": f"bytes-{c}".encode() for c in "abcdefgh"}
        for name, content in contents.items():
            self.serve_file(name, content)
        port = self.start_server(TrackingHandler)

        posts = [{"images": [f"http://127.0.0.1:{port}/{name}"]} for name in contents]

        asyncio.run(main.download_images(posts, self.out_path, concurrency=4))

        for name, content in contents.items():
            self.assertEqual((self.out_path / name).read_bytes(), content)
        self.assertGreaterEqual(TrackingHandler.max_in_flight, 2)

    def test_downloads_sequentially_when_concurrency_is_1(self):
        contents = {f"{c}.jpg": f"bytes-{c}".encode() for c in "abcd"}
        for name, content in contents.items():
            self.serve_file(name, content)
        port = self.start_server(TrackingHandler)

        posts = [{"images": [f"http://127.0.0.1:{port}/{name}"]} for name in contents]

        asyncio.run(main.download_images(posts, self.out_path, concurrency=1))

        for name, content in contents.items():
            self.assertEqual((self.out_path / name).read_bytes(), content)
        self.assertEqual(TrackingHandler.max_in_flight, 1)


class LoadPostsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)

    def write_data(self, content):
        self.dir.joinpath("data.json").write_text(content, encoding="utf-8")

    def test_loads_posts_from_data_file(self):
        posts = [{"author": "Alice", "images": ["https://pbs.twimg.com/media/a.jpg"], "videos": []}]
        self.write_data(json.dumps(posts))

        self.assertEqual(main.load_posts(self.dir), posts)

    def test_missing_data_file_errors(self):
        with self.assertRaises(main.ConfigError) as ctx:
            main.load_posts(self.dir)

        self.assertIn("Run a normal fetch first", str(ctx.exception))

    def test_invalid_json_errors(self):
        self.write_data("{not json")

        with self.assertRaises(main.ConfigError) as ctx:
            main.load_posts(self.dir)

        self.assertIn("invalid JSON", str(ctx.exception))

    def test_old_format_data_file_errors(self):
        self.write_data(json.dumps(["https://pbs.twimg.com/media/a.jpg"]))

        with self.assertRaises(main.ConfigError) as ctx:
            main.load_posts(self.dir)

        self.assertIn("unexpected format", str(ctx.exception))

    def test_non_list_data_file_errors(self):
        self.write_data(json.dumps({"posts": []}))

        with self.assertRaises(main.ConfigError) as ctx:
            main.load_posts(self.dir)

        self.assertIn("unexpected format", str(ctx.exception))


class SkipFetchEndToEndTest(unittest.TestCase):
    """Run main() in skip-fetch mode against a real local server (no mocks)."""

    def test_downloads_from_existing_data_file_without_api(self):
        with tempfile.TemporaryDirectory() as serve_dir, \
                tempfile.TemporaryDirectory() as out_dir, \
                tempfile.TemporaryDirectory() as config_dir:
            serve_path = pathlib.Path(serve_dir)
            out_path = pathlib.Path(out_dir)
            content_a = b"bytes-a"
            (serve_path / "a.jpg").write_bytes(content_a)
            (serve_path / "b.jpg").write_bytes(b"server-version-b")

            handler = functools.partial(QuietHandler, directory=serve_dir)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            port = server.server_address[1]

            likes_dir = out_path / "likes"
            likes_dir.mkdir()
            (likes_dir / "b.jpg").write_bytes(b"already-downloaded")
            posts = [
                {
                    "author": "Alice", "handle": "alice",
                    "date": "2026-07-30T13:26:30+00:00", "text": "hi",
                    "post_url": "https://x.com/alice/status/100",
                    "images": [f"http://127.0.0.1:{port}/a.jpg"],
                    "videos": [],
                },
                {
                    "author": "Bob", "handle": "bob",
                    "date": "2026-07-30T13:26:30+00:00", "text": "hey",
                    "post_url": "https://x.com/bob/status/200",
                    "images": [f"http://127.0.0.1:{port}/b.jpg"],
                    "videos": [],
                },
            ]
            (likes_dir / "data.json").write_text(json.dumps(posts), encoding="utf-8")

            # No credentials: skip-fetch mode must not require them.
            config_path = pathlib.Path(config_dir) / "config.json"
            config_path.write_text(json.dumps({
                "skip_fetch": True,
                "path": str(out_path),
            }), encoding="utf-8")

            QuietHandler.requests = []
            with mock.patch.object(
                sys, "argv", ["x-liked-photos-export", "--config", str(config_path)]
            ):
                asyncio.run(main.main())

            self.assertEqual((likes_dir / "a.jpg").read_bytes(), content_a)
            # The already-downloaded file is skipped (resume still applies).
            self.assertEqual((likes_dir / "b.jpg").read_bytes(), b"already-downloaded")
            self.assertEqual(QuietHandler.requests, ["/a.jpg"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
