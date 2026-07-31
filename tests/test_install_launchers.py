"""Tests for the cross-platform launcher installer."""

import os
import pathlib
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

import install_launchers  # noqa: E402

REPO = pathlib.Path("/home/user/x-liked-photos-export")


class LauncherContentTest(unittest.TestCase):
    def test_posix_export_wrapper_runs_main_py_from_repo_root(self):
        scripts = install_launchers.posix_scripts()

        export = scripts["export.sh"]
        self.assertIn('cd "$(dirname "$0")/.."', export)
        self.assertIn(".venv/bin/python src/main.py", export)
        self.assertIn("Press any key to close", export)

    def test_posix_slideshow_wrapper_opens_browser(self):
        scripts = install_launchers.posix_scripts()

        slideshow = scripts["slideshow.sh"]
        self.assertIn('cd "$(dirname "$0")/.."', slideshow)
        self.assertIn(".venv/bin/python src/slideshow.py --open-browser", slideshow)

    def test_linux_desktop_files_point_at_wrappers(self):
        launchers = install_launchers.linux_launchers(REPO)

        self.assertIn("X Export.desktop", launchers)
        self.assertIn("X Slideshow.desktop", launchers)
        export = launchers["X Export.desktop"]
        self.assertIn(f'Exec="{REPO}/launch/export.sh"', export)
        self.assertIn("Terminal=true", export)
        slideshow = launchers["X Slideshow.desktop"]
        self.assertIn(f'Exec="{REPO}/launch/slideshow.sh"', slideshow)

    def test_mac_commands_are_posix_wrappers(self):
        launchers = install_launchers.mac_launchers(REPO)

        self.assertEqual(set(launchers), {"X Export.command", "X Slideshow.command"})
        self.assertIn(".venv/bin/python src/main.py", launchers["X Export.command"])
        self.assertIn("--open-browser", launchers["X Slideshow.command"])

    def test_windows_bats_use_venv_scripts_python(self):
        launchers = install_launchers.windows_launchers(REPO)

        self.assertEqual(set(launchers), {"X Export.bat", "X Slideshow.bat"})
        export = launchers["X Export.bat"]
        self.assertIn('cd /d "%~dp0\\.."', export)
        self.assertIn(".venv\\Scripts\\python.exe src\\main.py", export)
        self.assertIn("pause", export)
        self.assertIn("--open-browser", launchers["X Slideshow.bat"])


class InstallTest(unittest.TestCase):
    def test_install_writes_files_and_marks_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch_dir = pathlib.Path(tmp) / "launch"

            written = install_launchers.install(launch_dir, "linux")

            self.assertTrue(launch_dir.is_dir())
            self.assertEqual(len(written), 4)
            for path in written:
                self.assertTrue(path.is_file(), path)
                self.assertTrue(os.access(path, os.X_OK), f"not executable: {path}")

    def test_install_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch_dir = pathlib.Path(tmp) / "launch"

            first = install_launchers.install(launch_dir, "linux")
            second = install_launchers.install(launch_dir, "linux")

            self.assertEqual(first, second)

    def test_install_windows_does_not_require_executable_bit(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch_dir = pathlib.Path(tmp) / "launch"

            written = install_launchers.install(launch_dir, "win32")

            self.assertEqual(len(written), 2)
            for path in written:
                self.assertTrue(path.is_file(), path)
                self.assertFalse(path.stat().st_mode & stat.S_IXUSR, path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
