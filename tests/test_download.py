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

import main  # noqa: E402


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serve files, ignoring any query string, without logging."""

    def translate_path(self, path):
        return super().translate_path(path.split("?", 1)[0])

    def log_message(self, *args):
        pass


class DownloadImagesTest(unittest.TestCase):
    def test_downloads_images_under_clean_filenames(self):
        with tempfile.TemporaryDirectory() as serve_dir, \
                tempfile.TemporaryDirectory() as out_dir:
            content_a = b"fake-jpeg-bytes-a"
            content_b = b"fake-jpeg-bytes-b"
            (pathlib.Path(serve_dir) / "a.jpg").write_bytes(content_a)
            (pathlib.Path(serve_dir) / "b.jpg").write_bytes(content_b)

            handler = functools.partial(QuietHandler, directory=serve_dir)
            server = http.server.HTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            port = server.server_address[1]

            posts = [
                {"images": [f"http://127.0.0.1:{port}/a.jpg?format=jpg&name=4096x4096"]},
                {"images": [f"http://127.0.0.1:{port}/b.jpg"]},
            ]

            asyncio.run(main.download_images(posts, pathlib.Path(out_dir)))

            # The query string must not leak into the saved filename.
            self.assertEqual((pathlib.Path(out_dir) / "a.jpg").read_bytes(), content_a)
            self.assertEqual((pathlib.Path(out_dir) / "b.jpg").read_bytes(), content_b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
