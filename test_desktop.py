import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import zipfile

import desktop
import server


def get_json(port, path="/api/health"):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}{path}", timeout=4) as response:
        return json.load(response)


class DesktopTests(unittest.TestCase):
    def test_mac_frozen_data_stays_outside_app_bundle(self):
        with patch.object(server.sys, 'platform', 'darwin'), patch.object(server.sys, 'frozen', True, create=True):
            self.assertEqual(server.default_data_dir(), Path.home() / 'Library/Application Support/XingxuBodyJournal/data')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.services = []

    def tearDown(self):
        for service in reversed(self.services):
            service.stop()
        self.temp.cleanup()

    def start(self, **kwargs):
        service = desktop.start_service(data_dir=self.directory, **kwargs)
        self.services.append(service)
        return service

    def test_server_serves_on_loopback_and_stops_cleanly(self):
        service = self.start(port=0)
        self.assertTrue(service.owned)
        self.assertEqual(service.server.server_address[0], "127.0.0.1")
        self.assertEqual(get_json(service.port)["desktop_instance"], service.token)
        state = get_json(service.port, "/api/state")
        self.assertEqual(state["records"], [])
        self.assertEqual(state["profile"]["name"], "")
        service.stop()
        self.assertFalse(service.thread.is_alive())
        self.assertFalse((self.directory / desktop.INSTANCE_FILE).exists())
        with socket.socket() as probe:
            probe.settimeout(0.4)
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", service.port)), 0)
        service.stop()  # An already stopped controller is harmless.

    def test_second_window_reuses_same_data_without_stopping_owner(self):
        owner = self.start(port=0)
        other = self.start(port=0)
        self.assertFalse(other.owned)
        self.assertEqual(other.port, owner.port)
        other.stop()
        self.assertEqual(get_json(owner.port)["desktop_instance"], owner.token)

    def test_busy_port_falls_back_without_touching_unrelated_listener(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            preferred = occupied.getsockname()[1]
            service = self.start(port=preferred)
            self.assertNotEqual(service.port, preferred)
            self.assertGreater(service.port, preferred)
            self.assertLessEqual(service.port, preferred + 15)
            service.stop()
            self.assertEqual(occupied.getsockname()[1], preferred)

    def test_port_exhaustion_is_clear(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            preferred = occupied.getsockname()[1]
            with self.assertRaisesRegex(RuntimeError, "端口均不可用"):
                self.start(port=preferred, max_port=preferred)

    def test_stale_or_wrong_metadata_never_reuses_another_server(self):
        first = self.start(port=0)
        metadata = self.directory / desktop.INSTANCE_FILE
        metadata.write_text(json.dumps({"port": first.port, "token": "0" * 32}), encoding="utf-8")
        second = self.start(port=first.port)
        self.assertTrue(second.owned)
        self.assertNotEqual(second.port, first.port)
        # Stopping the first server must not remove the second server's metadata.
        first.stop()
        self.assertEqual(json.loads(metadata.read_text())["token"], second.token)

    def test_invalid_metadata_does_not_trigger_external_requests(self):
        for value in ({}, {"port": True, "token": "a" * 32}, {"port": 65536, "token": "a" * 32}, {"port": 8765, "token": "invalid"}):
            self.assertFalse(desktop._matching_instance(value))

    def test_invalid_ports_rejected(self):
        for port in (-1, 65536, "8765", True):
            with self.assertRaises(ValueError):
                self.start(port=port)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / "dist" / "XingxuBodyJournal"
        self.folder.mkdir(parents=True)
        (self.folder / "XingxuBodyJournal.exe").write_bytes(b"test-build")
        spec = importlib.util.spec_from_file_location("package_windows", Path(__file__).parent / "scripts" / "package_windows.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def tearDown(self):
        self.temp.cleanup()

    def test_zip_contains_app_folder_and_instructions_not_workspace_data(self):
        (self.root / "data").mkdir()
        (self.root / "data" / "secret.jpg").write_bytes(b"private")
        archive_path = self.module.package(self.root)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertEqual(set(archive.namelist()), {"XingxuBodyJournal/XingxuBodyJournal.exe", "XingxuBodyJournal/开始使用.txt"})
        self.assertTrue(archive_path.with_suffix(".zip.sha256").is_file())

    def test_packaging_fails_if_private_data_was_copied_into_build(self):
        (self.folder / "data").mkdir()
        (self.folder / "data" / "body.sqlite3").write_bytes(b"private")
        with self.assertRaisesRegex(RuntimeError, "non-distribution"):
            self.module.package(self.root)


if __name__ == "__main__":
    unittest.main()
