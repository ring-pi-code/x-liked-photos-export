"""Tests for config file loading and settings resolution.

These tests do not require X credentials; they only verify that the
config file is read correctly and produces the expected settings.
"""

import contextlib
import json
import logging
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import main  # noqa: E402

VALID_CONFIG = {
    "ct0": "test-ct0",
    "auth_token": "test-auth-token",
    "twid": "u=123456",
    "likes_query_id": "test-likes-id",
    "bookmarks_query_id": "test-bookmarks-id",
}


@contextlib.contextmanager
def chdir(path):
    """Temporarily change the working directory."""
    import os

    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def write_config(directory, config) -> pathlib.Path:
    path = pathlib.Path(directory) / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class ResolveSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def resolve(self, argv):
        return main.resolve_settings(main.parse_args(argv))

    def test_loads_full_config_from_current_directory(self):
        out = pathlib.Path(self.dir) / "out"
        out.mkdir()
        write_config(self.dir, {
            **VALID_CONFIG,
            "download": True,
            "path": str(out),
        })

        with chdir(self.dir):
            settings = self.resolve([])

        self.assertEqual(settings["ct0"], "test-ct0")
        self.assertEqual(settings["cookies"]["auth_token"], "test-auth-token")
        self.assertEqual(settings["cookies"]["ct0"], "test-ct0")
        self.assertEqual(settings["cookies"]["twid"], "u=123456")
        self.assertTrue(settings["download"])
        self.assertEqual(settings["path"], out / "likes")

    def test_cli_args_override_config_values(self):
        write_config(self.dir, {**VALID_CONFIG, "ct0": "config-ct0", "download": True})

        with chdir(self.dir):
            settings = self.resolve([
                "--ct0", "cli-ct0",
                "--auth-token", "cli-auth-token",
            ])

        self.assertEqual(settings["ct0"], "cli-ct0")
        self.assertEqual(settings["cookies"]["auth_token"], "cli-auth-token")
        self.assertTrue(settings["download"])

    def test_defaults_when_config_minimal(self):
        write_config(self.dir, VALID_CONFIG)

        with chdir(self.dir):
            settings = self.resolve([])

        self.assertFalse(settings["download"])
        self.assertEqual(settings["mode"], "likes")
        self.assertEqual(settings["path"], pathlib.Path("likes"))

    def test_bookmarks_mode_needs_no_twid(self):
        write_config(self.dir, {
            "ct0": "test-ct0",
            "auth_token": "test-auth-token",
            "mode": "bookmarks",
            "bookmarks_query_id": "test-bookmarks-id",
        })

        with chdir(self.dir):
            settings = self.resolve([])

        self.assertEqual(settings["mode"], "bookmarks")
        self.assertNotIn("twid", settings["cookies"])
        self.assertEqual(settings["path"], pathlib.Path("bookmarks"))

    def test_bookmarks_flag_overrides_config_mode(self):
        write_config(self.dir, VALID_CONFIG)

        with chdir(self.dir):
            settings = self.resolve(["--bookmarks"])

        self.assertEqual(settings["mode"], "bookmarks")
        self.assertEqual(settings["path"], pathlib.Path("bookmarks"))

    def test_query_id_comes_from_config(self):
        with chdir(self.dir):
            write_config(self.dir, VALID_CONFIG)
            settings = self.resolve([])

        self.assertEqual(settings["query_id"], "test-likes-id")

    def test_bookmarks_query_id_used_in_bookmarks_mode(self):
        write_config(self.dir, {**VALID_CONFIG, "mode": "bookmarks"})

        with chdir(self.dir):
            settings = self.resolve([])

        self.assertEqual(settings["query_id"], "test-bookmarks-id")

    def test_missing_query_id_errors(self):
        config = {k: v for k, v in VALID_CONFIG.items() if not k.endswith("_query_id")}
        write_config(self.dir, config)

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        self.assertIn("'likes_query_id'", "".join(logs.output))

    def test_explicit_config_path_via_flag(self):
        config_dir = pathlib.Path(self.dir) / "elsewhere"
        config_dir.mkdir()
        (config_dir / "my.json").write_text(json.dumps(VALID_CONFIG))

        settings = self.resolve(["--config", str(config_dir / "my.json")])

        self.assertEqual(settings["ct0"], "test-ct0")

    def test_missing_explicit_config_file_errors(self):
        with self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve(["--config", str(pathlib.Path(self.dir) / "nope.json")])

        self.assertIn("Config file not found", "".join(logs.output))

    def test_invalid_json_errors(self):
        (pathlib.Path(self.dir) / "config.json").write_text("{not json")

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        self.assertIn("invalid JSON", "".join(logs.output))

    def test_unknown_keys_warn_but_are_ignored(self):
        write_config(self.dir, {**VALID_CONFIG, "ct00": "typo"})

        with chdir(self.dir), self.assertLogs(level=logging.WARNING) as logs:
            settings = self.resolve([])

        self.assertIn("ct00", "".join(logs.output))
        self.assertEqual(settings["ct0"], "test-ct0")

    def test_non_boolean_download_errors(self):
        write_config(self.dir, {**VALID_CONFIG, "download": "yes"})

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        self.assertIn("'download' must be true or false", "".join(logs.output))

    def test_4k_defaults_to_false(self):
        write_config(self.dir, VALID_CONFIG)

        with chdir(self.dir):
            settings = self.resolve([])

        self.assertFalse(settings["4k"])

    def test_4k_loaded_from_config(self):
        write_config(self.dir, {**VALID_CONFIG, "4k": True})

        with chdir(self.dir):
            settings = self.resolve([])

        self.assertTrue(settings["4k"])

    def test_4k_cli_flag_overrides_config(self):
        write_config(self.dir, VALID_CONFIG)

        with chdir(self.dir):
            settings = self.resolve(["--4k"])

        self.assertTrue(settings["4k"])

    def test_non_boolean_4k_errors(self):
        write_config(self.dir, {**VALID_CONFIG, "4k": "yes"})

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        self.assertIn("'4k' must be true or false", "".join(logs.output))

    def test_concurrency_defaults_to_4(self):
        write_config(self.dir, VALID_CONFIG)

        with chdir(self.dir):
            settings = self.resolve([])

        self.assertEqual(settings["concurrency"], 4)

    def test_concurrency_loaded_from_config(self):
        write_config(self.dir, {**VALID_CONFIG, "concurrency": 8})

        with chdir(self.dir):
            settings = self.resolve([])

        self.assertEqual(settings["concurrency"], 8)

    def test_concurrency_cli_flag_overrides_config(self):
        write_config(self.dir, {**VALID_CONFIG, "concurrency": 8})

        with chdir(self.dir):
            settings = self.resolve(["--concurrency", "2"])

        self.assertEqual(settings["concurrency"], 2)

    def test_invalid_concurrency_errors(self):
        for bad in ("4", True, 3, 0):
            with self.subTest(concurrency=bad):
                write_config(self.dir, {**VALID_CONFIG, "concurrency": bad})

                with chdir(self.dir), \
                        self.assertRaises(SystemExit), \
                        self.assertLogs(level=logging.ERROR) as logs:
                    self.resolve([])

                self.assertIn("'concurrency' must be one of", "".join(logs.output))

    def test_skip_fetch_defaults_to_false(self):
        write_config(self.dir, VALID_CONFIG)

        with chdir(self.dir):
            settings = self.resolve([])

        self.assertFalse(settings["skip_fetch"])

    def test_skip_fetch_forces_download_and_needs_no_credentials(self):
        out = pathlib.Path(self.dir) / "out"
        out.mkdir()
        write_config(self.dir, {"skip_fetch": True, "path": str(out)})

        with chdir(self.dir):
            settings = self.resolve([])

        self.assertTrue(settings["skip_fetch"])
        self.assertTrue(settings["download"])
        self.assertEqual(settings["path"], out / "likes")

    def test_skip_fetch_cli_flag(self):
        write_config(self.dir, VALID_CONFIG)

        with chdir(self.dir):
            settings = self.resolve(["--skip-fetch"])

        self.assertTrue(settings["skip_fetch"])

    def test_non_boolean_skip_fetch_errors(self):
        write_config(self.dir, {**VALID_CONFIG, "skip_fetch": "yes"})

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        self.assertIn("'skip_fetch' must be true or false", "".join(logs.output))

    def test_missing_ct0_errors(self):
        write_config(self.dir, {"auth_token": "a", "twid": "u=1"})

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        output = "".join(logs.output)
        self.assertIn("'ct0'", output)
        self.assertIn("x-csrf-token", output)

    def test_missing_auth_token_errors(self):
        write_config(self.dir, {"ct0": "t", "twid": "u=1"})

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        self.assertIn("'auth_token'", "".join(logs.output))

    def test_likes_mode_missing_twid_errors(self):
        write_config(self.dir, {"ct0": "t", "auth_token": "a"})

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        self.assertIn("'twid'", "".join(logs.output))

    def test_nonexistent_output_path_errors(self):
        write_config(self.dir, {
            **VALID_CONFIG,
            "path": str(pathlib.Path(self.dir) / "missing"),
        })

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        self.assertIn("not a directory", "".join(logs.output))


class MainIntegrationTest(unittest.TestCase):
    """Verify main() uses the config-driven settings end-to-end (network mocked)."""

    def test_main_writes_post_details_to_data_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out"
            out.mkdir()
            write_config(tmp, {**VALID_CONFIG, "path": str(out)})

            post = {
                "author": "Alice",
                "handle": "alice",
                "date": "2026-07-30T13:26:30+00:00",
                "text": "hello world",
                "post_url": "https://x.com/alice/status/100",
                "images": ["https://pbs.twimg.com/media/a.jpg"],
                "videos": [],
            }
            fake_posts = [post, dict(post)]  # duplicate, as pagination can repeat a post
            mock_progress = mock.MagicMock()

            with chdir(tmp), \
                    mock.patch.object(sys, "argv", ["x-liked-photos-export"]), \
                    mock.patch.object(main, "tqdm", return_value=mock_progress), \
                    mock.patch.object(main, "collect_posts",
                                      new=mock.AsyncMock(return_value=fake_posts)) as fetch:
                import asyncio
                asyncio.run(main.main())

            fetch.assert_awaited_once()
            _, kwargs = fetch.call_args
            self.assertEqual(kwargs["progress"], mock_progress)
            cookies_arg, ct0_arg = fetch.call_args.args
            self.assertEqual(ct0_arg, "test-ct0")
            self.assertEqual(cookies_arg["auth_token"], "test-auth-token")

            data_file = out / "likes" / "data.json"
            self.assertTrue(data_file.is_file())
            self.assertEqual(json.loads(data_file.read_text()), [post])

    def test_main_rewrites_image_urls_to_4k_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out"
            out.mkdir()
            write_config(tmp, {**VALID_CONFIG, "path": str(out), "4k": True})

            post = {
                "author": "Alice",
                "handle": "alice",
                "date": "2026-07-30T13:26:30+00:00",
                "text": "hello world",
                "post_url": "https://x.com/alice/status/100",
                "images": ["https://pbs.twimg.com/media/a.jpg"],
                "videos": [],
            }
            mock_progress = mock.MagicMock()

            with chdir(tmp), \
                    mock.patch.object(sys, "argv", ["x-liked-photos-export"]), \
                    mock.patch.object(main, "tqdm", return_value=mock_progress), \
                    mock.patch.object(main, "collect_posts",
                                      new=mock.AsyncMock(return_value=[post])):
                import asyncio
                asyncio.run(main.main())

            data = json.loads((out / "likes" / "data.json").read_text())
            self.assertEqual(data[0]["images"],
                             ["https://pbs.twimg.com/media/a.jpg?format=jpg&name=4096x4096"])

    def test_main_passes_concurrency_to_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out"
            out.mkdir()
            write_config(tmp, {**VALID_CONFIG, "path": str(out),
                               "download": True, "concurrency": 8})

            post = {
                "author": "Alice",
                "handle": "alice",
                "date": "2026-07-30T13:26:30+00:00",
                "text": "hello world",
                "post_url": "https://x.com/alice/status/100",
                "images": ["https://pbs.twimg.com/media/a.jpg"],
                "videos": [],
            }
            mock_progress = mock.MagicMock()

            with chdir(tmp), \
                    mock.patch.object(sys, "argv", ["x-liked-photos-export"]), \
                    mock.patch.object(main, "tqdm", return_value=mock_progress), \
                    mock.patch.object(main, "collect_posts",
                                      new=mock.AsyncMock(return_value=[post])), \
                    mock.patch.object(main, "download_images",
                                      new=mock.AsyncMock()) as download:
                import asyncio
                asyncio.run(main.main())

            download.assert_awaited_once()
            args, kwargs = download.call_args
            self.assertEqual(args[0], [post])
            self.assertEqual(kwargs["concurrency"], 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
