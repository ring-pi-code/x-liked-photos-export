"""Tests for config file loading and settings resolution.

These tests do not require X credentials; they only verify that the
config file is read correctly and produces the expected settings.
"""

import contextlib
import io
import json
import logging
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import main  # noqa: E402

VALID_COOKIES = "auth_token=abc; ct0=def; twid=u%3D123456"


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
            "token": "test-token",
            "cookies": VALID_COOKIES,
            "download": True,
            "path": str(out),
        })

        with chdir(self.dir):
            settings = self.resolve([])

        self.assertEqual(settings["token"], "test-token")
        self.assertEqual(settings["cookies"]["auth_token"], "abc")
        self.assertEqual(settings["cookies"]["ct0"], "def")
        self.assertEqual(settings["cookies"]["twid"], "u%3D123456")
        self.assertTrue(settings["download"])
        self.assertEqual(settings["path"], out)

    def test_cli_args_override_config_values(self):
        write_config(self.dir, {"token": "config-token", "download": True})

        with chdir(self.dir):
            settings = self.resolve([
                "--token", "cli-token",
                "--cookies", VALID_COOKIES,
            ])

        self.assertEqual(settings["token"], "cli-token")
        self.assertTrue(settings["download"])

    def test_defaults_when_config_minimal(self):
        write_config(self.dir, {"token": "test-token"})

        with chdir(self.dir), \
                mock.patch.object(main, "get_browser_cookies",
                                  return_value={"auth_token": "a", "ct0": "b", "twid": "c"}) as m:
            settings = self.resolve([])

        m.assert_called_once()
        self.assertFalse(settings["download"])
        self.assertEqual(settings["path"], pathlib.Path("."))

    def test_empty_cookies_string_falls_back_to_browser(self):
        write_config(self.dir, {"token": "test-token", "cookies": ""})

        with chdir(self.dir), \
                mock.patch.object(main, "get_browser_cookies",
                                  return_value={"auth_token": "a", "ct0": "b", "twid": "c"}) as m:
            self.resolve([])

        m.assert_called_once()

    def test_explicit_config_path_via_flag(self):
        config_dir = pathlib.Path(self.dir) / "elsewhere"
        config_dir.mkdir()
        (config_dir / "my.json").write_text(
            json.dumps({"token": "flag-token", "cookies": VALID_COOKIES})
        )

        settings = self.resolve(["--config", str(config_dir / "my.json")])

        self.assertEqual(settings["token"], "flag-token")

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
        write_config(self.dir, {
            "token": "test-token",
            "cookies": VALID_COOKIES,
            "tocken": "typo",
        })

        with chdir(self.dir), self.assertLogs(level=logging.WARNING) as logs:
            settings = self.resolve([])

        self.assertIn("tocken", "".join(logs.output))
        self.assertEqual(settings["token"], "test-token")

    def test_non_boolean_download_errors(self):
        write_config(self.dir, {"token": "t", "download": "yes"})

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        self.assertIn("'download' must be true or false", "".join(logs.output))

    def test_missing_token_errors(self):
        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve(["--cookies", VALID_COOKIES])

        self.assertIn("x-csrf-token", "".join(logs.output))

    def test_missing_required_cookies_errors(self):
        write_config(self.dir, {"token": "t", "cookies": "auth_token=abc"})

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        output = "".join(logs.output)
        self.assertIn("ct0", output)
        self.assertIn("twid", output)

    def test_nonexistent_output_path_errors(self):
        write_config(self.dir, {
            "token": "t",
            "cookies": VALID_COOKIES,
            "path": str(pathlib.Path(self.dir) / "missing"),
        })

        with chdir(self.dir), \
                self.assertRaises(SystemExit), \
                self.assertLogs(level=logging.ERROR) as logs:
            self.resolve([])

        self.assertIn("not a directory", "".join(logs.output))


class MainIntegrationTest(unittest.TestCase):
    """Verify main() uses the config-driven settings end-to-end (network mocked)."""

    def test_main_uses_config_file_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "out"
            out.mkdir()
            write_config(tmp, {
                "token": "test-token",
                "cookies": VALID_COOKIES,
                "path": str(out),
            })

            fake_images = ["https://pbs.twimg.com/media/a.jpg", "https://pbs.twimg.com/media/b.jpg"]
            mock_progress = mock.MagicMock()

            with chdir(tmp), \
                    mock.patch.object(sys, "argv", ["x-liked-photos-export"]), \
                    mock.patch.object(main, "tqdm", return_value=mock_progress), \
                    mock.patch.object(main, "collect_images_urls",
                                      new=mock.AsyncMock(return_value=fake_images)) as fetch:
                import asyncio
                asyncio.run(main.main())

            fetch.assert_awaited_once()
            _, kwargs = fetch.call_args
            self.assertEqual(kwargs["progress"], mock_progress)
            cookies_arg, token_arg = fetch.call_args.args
            self.assertEqual(token_arg, "test-token")
            self.assertEqual(cookies_arg["auth_token"], "abc")

            data_file = out / "data.json"
            self.assertTrue(data_file.is_file())
            self.assertEqual(json.loads(data_file.read_text()), fake_images)


if __name__ == "__main__":
    unittest.main(verbosity=2)
