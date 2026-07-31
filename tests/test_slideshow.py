"""Tests for the slideshow server, end to end over real HTTP."""

import json
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import slideshow  # noqa: E402


def get(url):
    with urllib.request.urlopen(url) as res:
        return res.status, res.read(), res.headers


def get_json(url):
    status, body, _ = get(url)
    return status, json.loads(body)


def get_status(url):
    try:
        with urllib.request.urlopen(url) as res:
            return res.status
    except urllib.error.HTTPError as e:
        return e.code


class SlideshowServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)
        self.images = self.dir / "images"
        self.images.mkdir()
        (self.images / "b.jpg").write_bytes(b"jpeg-b")
        (self.images / "a.png").write_bytes(b"png-a")
        (self.images / "notes.txt").write_bytes(b"not an image")

        self.server = slideshow.make_server("127.0.0.1", 0, str(self.images))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def test_api_config_returns_default_folder(self):
        status, data = get_json(f"{self.base}/api/config")

        self.assertEqual(status, 200)
        self.assertEqual(data["default_folder"], str(self.images))

    def test_api_images_lists_images_sorted(self):
        status, data = get_json(f"{self.base}/api/images?folder={self.images}")

        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 2)
        self.assertEqual([i["name"] for i in data["images"]], ["a.png", "b.jpg"])

    def test_api_images_missing_folder_errors(self):
        status = get_status(f"{self.base}/api/images?folder={self.dir}/nope")

        self.assertEqual(status, 404)

    def test_api_image_serves_file_bytes(self):
        status, body, headers = get(f"{self.base}/api/image?path={self.images}/b.jpg")

        self.assertEqual(status, 200)
        self.assertEqual(body, b"jpeg-b")
        self.assertEqual(headers["Content-Type"], "image/jpeg")

    def test_api_image_rejects_non_image_extension(self):
        status = get_status(f"{self.base}/api/image?path={self.images}/notes.txt")

        self.assertEqual(status, 400)

    def test_api_image_rejects_file_outside_loaded_folder(self):
        outside = self.dir / "outside.jpg"
        outside.write_bytes(b"secret")

        status = get_status(f"{self.base}/api/image?path={outside}")

        self.assertEqual(status, 403)

    def test_api_image_missing_file_errors(self):
        status = get_status(f"{self.base}/api/image?path={self.images}/nope.jpg")

        self.assertEqual(status, 404)

    def test_index_is_served(self):
        status, body, _ = get(f"{self.base}/")

        self.assertEqual(status, 200)
        self.assertIn(b"slideshow", body.lower())


class DefaultFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)

    def test_resolves_path_and_mode_from_config(self):
        config = self.dir / "config.json"
        config.write_text(json.dumps({"path": str(self.dir / "out"), "mode": "bookmarks"}))

        folder = slideshow.default_folder(config)

        self.assertEqual(folder, self.dir / "out" / "bookmarks")

    def test_defaults_to_likes_without_config(self):
        folder = slideshow.default_folder(self.dir / "missing.json")

        self.assertEqual(folder, pathlib.Path("likes"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
