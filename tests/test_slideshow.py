"""Tests for the slideshow server, end to end over real HTTP."""

import http.client
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

    def test_vendored_oat_css_is_served(self):
        status, body, headers = get(f"{self.base}/vendor/oat.min.css")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/css")
        self.assertIn(b"@layer", body)

    def test_static_path_traversal_is_rejected(self):
        # Raw "../" must not escape the public directory. http.client sends
        # the path verbatim, unlike urllib/curl which normalize it away.
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1])
        conn.request("GET", "/../slideshow.py")
        res = conn.getresponse()
        res.read()
        conn.close()

        self.assertEqual(res.status, 404)


class TimelineApiTest(unittest.TestCase):
    """Tests for /api/posts, end to end over real HTTP."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)

        # a.jpg and c.jpg exist locally; missing.jpg does not.
        (self.dir / "a.jpg").write_bytes(b"jpeg-a")
        (self.dir / "c.jpg").write_bytes(b"jpeg-c")
        posts = [
            {
                "author": "Alice", "handle": "alice",
                "date": "2024-01-15T12:00:00+00:00", "text": "hello",
                "post_url": "https://x.com/alice/status/100",
                "images": ["https://pbs.twimg.com/media/a.jpg"],
                "videos": [],
            },
            {
                "author": "Bob", "handle": "bob",
                "date": "2024-06-01T09:00:00+00:00", "text": "world",
                "post_url": "https://x.com/bob/status/200",
                "images": ["https://pbs.twimg.com/media/missing.jpg"],
                "videos": ["https://video.twimg.com/amplify_video/1/vid/x.mp4?tag=29"],
            },
            {
                "author": "Carol", "handle": "carol",
                "date": "2022-03-10T00:00:00+00:00", "text": "old",
                "post_url": "https://x.com/carol/status/300",
                "images": ["https://pbs.twimg.com/media/c.jpg"],
                "videos": [],
            },
        ]
        (self.dir / "data.json").write_text(json.dumps(posts), encoding="utf-8")

        self.server = slideshow.make_server("127.0.0.1", 0, str(self.dir))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def posts(self, query=""):
        status, data = get_json(f"{self.base}/api/posts?folder={self.dir}{query}")
        self.assertEqual(status, 200, data)
        return data

    def handles(self, query=""):
        return [p["handle"] for p in self.posts(query)["posts"]]

    def test_posts_sorted_newest_first_by_default(self):
        self.assertEqual(self.handles(), ["bob", "alice", "carol"])

    def test_sort_ascending(self):
        self.assertEqual(self.handles("&sort=asc"), ["carol", "alice", "bob"])

    def test_filter_before(self):
        self.assertEqual(self.handles("&to=2023-12-31"), ["carol"])

    def test_filter_after(self):
        self.assertEqual(self.handles("&from=2024-01-01"), ["bob", "alice"])

    def test_filter_between(self):
        self.assertEqual(self.handles("&from=2022-01-01&to=2024-01-31"), ["alice", "carol"])

    def test_pagination(self):
        page1 = self.posts("&limit=2")
        self.assertEqual(page1["total"], 3)
        self.assertEqual(page1["limit"], 2)
        self.assertEqual([p["handle"] for p in page1["posts"]], ["bob", "alice"])

        page2 = self.posts("&limit=2&offset=2")
        self.assertEqual([p["handle"] for p in page2["posts"]], ["carol"])

    def test_media_mapping(self):
        posts = {p["handle"]: p for p in self.posts()["posts"]}

        alice_media = posts["alice"]["media"]
        self.assertEqual(alice_media[0]["kind"], "image")
        self.assertEqual(alice_media[0]["name"], "a.jpg")
        self.assertTrue(alice_media[0]["path"].endswith("a.jpg"))

        bob_media = posts["bob"]["media"]
        kinds = [m["kind"] for m in bob_media]
        self.assertEqual(kinds, ["missing", "video"])

    def test_invalid_sort_errors(self):
        status = get_status(f"{self.base}/api/posts?folder={self.dir}&sort=sideways")
        self.assertEqual(status, 400)

    def test_invalid_date_errors(self):
        status = get_status(f"{self.base}/api/posts?folder={self.dir}&from=not-a-date")
        self.assertEqual(status, 400)

    def test_missing_data_file_errors(self):
        empty = self.dir / "empty"
        empty.mkdir()
        status = get_status(f"{self.base}/api/posts?folder={empty}")
        self.assertEqual(status, 404)

    def test_missing_folder_errors(self):
        status = get_status(f"{self.base}/api/posts?folder={self.dir}/nope")
        self.assertEqual(status, 404)


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
