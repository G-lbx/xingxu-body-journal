"""Run with: python -m unittest test_server -v. No production data is used."""
import base64
import contextlib
import io
import json
import socket
import sqlite3
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

import server

# Fictional data and a neutral 1 x 1 PNG; no personal screenshots are required.
TEST_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7TYAAAAASUVORK5CYII="
)
TEST_PROFILE = {
    **server.DEFAULT_PROFILE, "name": "虚构测试用户", "age": 30, "height": 175,
    "sex": "male", "training_days": 3, "training_focus": "全身力量训练",
}


class ServerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="body-journal-test-")
        self.data_dir = Path(self.temporary.name)
        self.httpd = server.create_server(port=0, data_dir=self.data_dir, seed=False)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.ocr_patch = patch.dict("sys.modules", {"ocr": types.SimpleNamespace(available=lambda: False, engine_name=lambda: "test", extract_image=lambda path: {"fields": {"weight": 75.0}, "raw_text": "test", "warnings": [], "engine": "test"})})
        self.ocr_patch.start()

    def tearDown(self):
        self.ocr_patch.stop()
        self.httpd.shutdown()
        self.thread.join(timeout=3)
        self.httpd.server_close()
        self.temporary.cleanup()

    def request(self, method="GET", path="/api/state", payload=None, headers=None, raw=None):
        request_headers = dict(headers or {})
        data = raw
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(self.url + path, data=data, method=method, headers=request_headers)
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            content = response.read()
            result = json.loads(content) if "application/json" in response.headers.get("Content-Type", "") else content
            return response.status, result, response.headers

    def record(self, measured_at="2024-03-01T10:36", **kwargs):
        result = {"measured_at": measured_at, "weight": 75.0, "body_fat": 20.0, "source": "manual"}
        result.update(kwargs)
        return result

    def upload(self):
        image = TEST_IMAGE
        payload = {"name": "fictional-test.png", "dataUrl": "data:image/png;base64," + base64.b64encode(image).decode()}
        return self.request("POST", "/api/upload", payload)

    def test_crud_and_restart_persistence(self):
        status, saved, _ = self.request("POST", "/api/records", self.record())
        self.assertEqual(status, 201)
        record_id = saved["record"]["id"]
        status, saved, _ = self.request("PUT", f"/api/records/{record_id}", {"weight": 75.2, "waist": 73, "note": "已核对"})
        self.assertEqual(status, 200)
        self.assertEqual(saved["record"]["body_fat"], 20.0)
        reopened = server.Store(self.data_dir, seed=False)
        self.assertEqual(reopened.export()["records"][0]["weight"], 75.2)
        status, _, _ = self.request("DELETE", f"/api/records/{record_id}", {})
        self.assertEqual(status, 200)
        self.assertEqual(reopened.export()["records"], [])
        self.assertEqual(self.request("DELETE", f"/api/records/{record_id}", {})[0], 404)

    def test_new_installation_is_blank_for_all_legacy_seed_options(self):
        for seed in (True, False):
            with self.subTest(seed=seed):
                directory = self.data_dir / str(seed)
                store = server.Store(directory, seed=seed)
                exported = store.export()
                self.assertEqual(exported["records"], [])
                self.assertEqual(exported["checkins"], [])
                self.assertEqual(exported["profile"], server.DEFAULT_PROFILE)
                for field in ("age", "height", "training_days"):
                    self.assertIsNone(exported["profile"][field])
                self.assertEqual(list(store.uploads.iterdir()), [])
                self.assertEqual(server.Store(directory).export(), exported)

    def test_upgrade_preserves_existing_profile_records_checkins_and_images(self):
        status, uploaded, _ = self.upload()
        self.assertEqual(status, 201)
        self.request("POST", "/api/records", self.record(id="legacy-record", upload_id=uploaded["upload_id"]))
        self.request("PUT", "/api/profile", TEST_PROFILE)
        self.request("PUT", "/api/checkins/2024-03-01", {"minutes": 40, "training": "strength"})
        before = self.httpd.store.export()
        image_path = self.httpd.store.uploads / uploaded["upload_id"]
        image_before = image_path.read_bytes()
        # Even an installation without the initialization marker must not be reseeded.
        with self.httpd.store.connection() as db:
            db.execute("DELETE FROM metadata WHERE key='initialized'")
        reopened = server.Store(self.data_dir)
        self.assertEqual(reopened.export(), before)
        self.assertEqual(image_path.read_bytes(), image_before)
        reopened.delete_record("legacy-record")
        self.assertEqual(server.Store(self.data_dir).export()["records"], [])

    def test_default_data_path_separates_bundle_and_persistent_storage(self):
        with patch.object(server.sys, "frozen", False, create=True):
            self.assertEqual(server.default_data_dir(), server.ROOT / "data")
        with patch.object(server.sys, "frozen", True, create=True), patch.object(server.sys, "platform", "win32"):
            with patch.dict(server.os.environ, {"LOCALAPPDATA": str(self.data_dir)}):
                self.assertEqual(server.default_data_dir(), self.data_dir / "XingxuBodyJournal" / "data")
        with patch.object(server.sys, "frozen", True, create=True), patch.object(server.sys, "platform", "win32"):
            with patch.dict(server.os.environ, {}, clear=True), patch.object(server.Path, "home", return_value=self.data_dir):
                self.assertEqual(server.default_data_dir(), self.data_dir / "AppData" / "Local" / "XingxuBodyJournal" / "data")

    def test_incomplete_profile_can_remain_unknown(self):
        status, result, _ = self.request("PUT", "/api/profile", {"training_days": None})
        self.assertEqual(status, 200)
        self.assertEqual(result["profile"], server.DEFAULT_PROFILE)
        for invalid in (-1, 8, True, 1.5):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.request("PUT", "/api/profile", {"training_days": invalid})[0], 400)

    def test_timestamp_duplicate_and_update_exclusion(self):
        status, saved, _ = self.request("POST", "/api/records", self.record())
        self.assertEqual(status, 201)
        record_id = saved["record"]["id"]
        status, error, _ = self.request("POST", "/api/records", self.record("2024-03-01T10:36:00"))
        self.assertEqual(status, 409)
        self.assertEqual(error["existing_id"], record_id)
        self.assertEqual(self.request("PUT", f"/api/records/{record_id}", {"weight": 63})[0], 200)

    def test_invalid_values_are_rejected_without_writes(self):
        invalid = [self.record(weight=None), self.record(weight=True), self.record(body_fat=101), self.record(weight=10 ** 350), self.record("2024-02-30T10:00"), self.record("2024-03-01T99:00"), self.record(upload_id="../private.png")]
        for record in invalid:
            with self.subTest(record=record):
                self.assertEqual(self.request("POST", "/api/records", record)[0], 400)
        self.assertEqual(self.request("POST", "/api/records", raw=b'{"weight":NaN}', headers={"Content-Type": "application/json"})[0], 400)
        self.assertEqual(self.httpd.store.export()["records"], [])

    def test_profile_and_checkins_persist(self):
        status, saved, _ = self.request("PUT", "/api/profile", {"name": "测试", "age": 30, "height": 175, "sex": "male", "training_days": 3, "training_focus": "全身力量训练"})
        self.assertEqual(status, 200)
        self.assertEqual(saved["profile"]["training_focus"], "全身力量训练")
        payload = {"training": "strength", "minutes": 45, "sleep": 7.5, "steps": 6000, "energy": "good", "nutrition": True, "tasks": ["walk", "sleep", "walk"]}
        status, saved, _ = self.request("PUT", "/api/checkins/2024-03-01", payload)
        self.assertEqual(status, 200)
        self.assertEqual(saved["checkin"]["tasks"], ["walk", "sleep"])
        payload["minutes"] = 50
        self.request("PUT", "/api/checkins/2024-03-01", payload)
        exported = server.Store(self.data_dir, seed=False).export()
        self.assertEqual(len(exported["checkins"]), 1)
        self.assertEqual(exported["checkins"][0]["minutes"], 50)
        self.assertEqual(self.request("PUT", "/api/checkins/2024-02-30", payload)[0], 400)

    def test_uploaded_image_duplicate_and_safe_serving(self):
        status, upload, _ = self.upload()
        self.assertEqual(status, 201)
        self.assertEqual(upload["fields"]["weight"], 75.0)
        self.assertEqual(self.request("GET", upload["image_url"])[0], 200)
        status, saved, _ = self.request("POST", "/api/records", self.record(upload_id=upload["upload_id"], source="ocr_confirmed"))
        self.assertEqual(status, 201)
        status, duplicate, _ = self.upload()
        self.assertEqual(duplicate["upload_id"], upload["upload_id"])
        self.assertEqual(duplicate["duplicate_record_id"], saved["record"]["id"])
        status, error, _ = self.request("POST", "/api/records", self.record("2024-03-02T10:36", upload_id=upload["upload_id"]))
        self.assertEqual(status, 409)
        self.assertEqual(error["existing_id"], saved["record"]["id"])

    def test_invalid_image_and_ocr_failure(self):
        payload = {"name": "evil.jpg", "dataUrl": "data:image/jpeg;base64," + base64.b64encode(b"not an image").decode()}
        self.assertEqual(self.request("POST", "/api/upload", payload)[0], 400)
        fake = types.SimpleNamespace(available=lambda: False, engine_name=lambda: "test", extract_image=lambda path: (_ for _ in ()).throw(RuntimeError("secret internal details")))
        with patch.dict("sys.modules", {"ocr": fake}):
            status, uploaded, _ = self.upload()
        self.assertEqual(status, 201)
        self.assertEqual(uploaded["fields"], {})
        self.assertTrue(uploaded["warnings"])
        self.assertNotIn("secret", json.dumps(uploaded))

    def test_local_only_security_and_private_files(self):
        self.assertEqual(self.request(headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request(headers={"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.request(headers={"Origin": "null"})[0], 403)
        self.assertEqual(self.request(headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.request(headers={"Origin": self.url})[0], 200)
        for path in ["/server.py", "/test_server.py", "/data/journal.sqlite3", "/uploads/../journal.sqlite3", "/assets/%2e%2e/server.py", "/assets/%2e%2e%5cserver.py", "/preview/check.png"]:
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path)[0], 404)
        self.assertEqual(self.request(path="/assets/armor-theme.css")[0], 200)
        self.assertEqual(self.request("POST", "/api/records", raw=b'{}', headers={"Content-Type": "text/plain"})[0], 415)

    def test_export_merge_conflicts_and_validation_are_atomic(self):
        self.request("POST", "/api/records", self.record(id="original"))
        exported = self.httpd.store.export()
        exported["records"][0]["weight"] = 70
        exported["records"].append({**self.record("2024-03-02T10:00"), "id": "next"})
        status, imported, _ = self.request("POST", "/api/import", exported)
        self.assertEqual(status, 200)
        self.assertEqual((imported["imported"], imported["skipped"]), (1, 1))
        self.assertEqual(self.httpd.store.export()["records"][0]["weight"], 75.0)
        invalid = {**exported, "records": [{**self.record("2024-03-03T10:00"), "id": "valid"}, {**self.record("2024-03-04T10:00", weight=-2), "id": "invalid"}]}
        self.assertEqual(self.request("POST", "/api/import", invalid)[0], 400)
        self.assertEqual(len(self.httpd.store.export()["records"]), 2)
        conflict = {**exported, "records": [{**self.record(), "id": "different-id"}]}
        result = self.request("POST", "/api/import", conflict)[1]
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["conflicts"][0]["existing_id"], "original")

    def test_json_import_reports_missing_original(self):
        exported = {"schema_version": 1, "records": [{**self.record(), "id": "from-json", "upload_id": "missing.jpg"}], "profile": server.DEFAULT_PROFILE, "checkins": []}
        result = self.request("POST", "/api/import", exported)
        self.assertEqual(result[0], 200)
        self.assertTrue(any("原图" in message for message in result[1]["warnings"]))
        status, _, _ = self.request("PUT", "/api/records/from-json", {"weight": 63})
        self.assertEqual(status, 200)

    def test_complete_zip_backup_and_restore(self):
        uploaded = self.upload()[1]
        self.request("POST", "/api/records", self.record(id="with-picture", upload_id=uploaded["upload_id"]))
        self.request("PUT", "/api/profile", {"age": 30, "height": 175, "training_days": 3})
        self.request("PUT", "/api/checkins/2024-03-01", {"minutes": 35, "training": "strength"})
        status, archive, headers = self.request(path="/api/backup")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        fresh = server.Store(self.data_dir / "restored", seed=False)
        result = fresh.restore_archive({"dataBase64": base64.b64encode(archive).decode()})
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["images_restored"], 1)
        self.assertEqual(fresh.export()["profile"]["training_days"], 3)
        self.assertEqual(fresh.export()["checkins"][0]["minutes"], 35)
        self.assertTrue((fresh.uploads / uploaded["upload_id"]).is_file())
        duplicate = fresh.restore_archive({"dataBase64": base64.b64encode(archive).decode()})
        self.assertEqual(duplicate["imported"], 0)
        self.assertEqual(duplicate["skipped"], 1)

    def test_restore_rejects_zip_traversal_before_mutation(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("export.json", json.dumps({"schema_version": 1, "records": [{**self.record(), "id": "would-add"}], "profile": server.DEFAULT_PROFILE, "checkins": []}))
            archive.writestr("uploads/../../escaped.jpg", b"\xff\xd8\xff\xd9")
        status, _, _ = self.request("POST", "/api/restore", {"dataBase64": base64.b64encode(buffer.getvalue()).decode()})
        self.assertEqual(status, 400)
        self.assertEqual(self.httpd.store.export()["records"], [])
        self.assertFalse((self.data_dir / "escaped.jpg").exists())

    def test_inferred_import_cannot_be_promoted_to_actual_data(self):
        for marker in ({"inferred": True}, {"is_estimated": True}, {"derived": True}, {"is_inferred": True}, {"source_type": "derived"}, {"kind": "device_comparison"}, {"record_type": "estimated"}, {"type": "inferred"}, {"provenance": {"kind": "derived"}}):
            with self.subTest(marker=marker):
                payload = {"schema_version": 1, "records": [{**self.record("2024-02-29T10:00"), "id": "valid"}, {**self.record(), "id": "inferred", **marker}], "profile": server.DEFAULT_PROFILE, "checkins": []}
                status, error, _ = self.request("POST", "/api/import", payload)
                self.assertEqual(status, 400)
                self.assertIn("推算", error["error"])
                self.assertEqual(self.httpd.store.export()["records"], [])

    def test_restore_transaction_failure_rolls_back_rows_and_new_images(self):
        with self.httpd.store.connection() as database:
            database.execute("CREATE TRIGGER reject_import BEFORE INSERT ON records WHEN NEW.id='reject' BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
        image = TEST_IMAGE
        exported = {"schema_version": 1, "records": [{**self.record("2024-02-29T10:00"), "id": "valid", "upload_id": "restored.png"}, {**self.record(), "id": "reject"}], "profile": {**server.DEFAULT_PROFILE, "age": 30}, "checkins": []}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("export.json", json.dumps(exported))
            archive.writestr("uploads/restored.png", image)
        status, error, _ = self.request("POST", "/api/restore", {"dataBase64": base64.b64encode(buffer.getvalue()).decode()})
        self.assertEqual(status, 500)
        self.assertNotIn("test rollback", error["error"])
        self.assertEqual(self.httpd.store.export()["records"], [])
        self.assertEqual(self.httpd.store.export()["profile"], server.DEFAULT_PROFILE)
        self.assertEqual(list(self.httpd.store.uploads.iterdir()), [])
        with self.httpd.store.connection() as database:
            self.assertEqual(database.execute("SELECT count(*) FROM uploads").fetchone()[0], 0)

    def test_edit_preserves_or_explicitly_updates_source_and_device_comparison(self):
        comparison = {"measured_at": "2024-02-15T13:24", "weight_delta": -0.45, "body_fat_delta": -0.3}
        self.request("POST", "/api/records", self.record(id="provenance", source="assistant_verified", device_comparison=comparison))
        status, saved, _ = self.request("PUT", "/api/records/provenance", {"note": "添加备注"})
        self.assertEqual(status, 200)
        self.assertEqual(saved["record"]["source"], "assistant_verified")
        self.assertEqual(saved["record"]["device_comparison"], comparison)
        status, saved, _ = self.request("PUT", "/api/records/provenance", {"weight": 75.1, "source": "manual"})
        self.assertEqual(status, 200)
        self.assertEqual(saved["record"]["source"], "manual")
        self.assertEqual(saved["record"]["device_comparison"], comparison)

    def test_daily_backup_precedes_first_mutation(self):
        self.request("POST", "/api/records", self.record())
        backups = list((self.data_dir / "automatic-backups").glob("*.sqlite3"))
        self.assertEqual(len(backups), 1)
        with contextlib.closing(sqlite3.connect(backups[0])) as database:
            self.assertEqual(database.execute("SELECT count(*) FROM records").fetchone()[0], 0)
        self.request("POST", "/api/records", self.record("2024-03-02T10:00"))
        self.assertEqual(len(list((self.data_dir / "automatic-backups").glob("*.sqlite3"))), 1)

    def test_state_schema_and_health(self):
        status, state, _ = self.request()
        self.assertEqual(status, 200)
        for key in ("records", "profile", "checkins", "analysis", "ocr_available", "today", "server_time"):
            self.assertIn(key, state)
        self.assertEqual(state["today"], server.today_string())
        self.assertTrue(state["server_time"].endswith("+08:00"))
        self.assertEqual(self.request(path="/api/health")[1]["app"], "body-journal")

    def test_health_reports_optional_desktop_instance_without_paths(self):
        status, health, _ = self.request(path="/api/health")
        self.assertEqual(status, 200)
        self.assertNotIn("desktop_instance", health)
        instance = "b3208d56fae942428a16c46a0d67812e"
        self.httpd.desktop_instance = instance
        status, health, _ = self.request(path="/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["desktop_instance"], instance)
        self.assertNotIn(str(self.data_dir), json.dumps(health))

    def test_active_port_cannot_be_shared_by_another_server(self):
        with self.assertRaises(OSError):
            server.create_server(port=self.httpd.server_port, data_dir=self.data_dir / "second-instance")
        self.assertEqual(self.request(path="/api/health")[0], 200)

    @unittest.skipUnless(server.os.name == "nt", "Windows exclusive binding")
    def test_windows_socket_is_exclusive_even_against_reuse_address(self):
        self.assertFalse(self.httpd.allow_reuse_address)
        self.assertFalse(self.httpd.allow_reuse_port)
        self.assertEqual(self.httpd.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE), 1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as challenger:
            challenger.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with self.assertRaises(OSError):
                challenger.bind(("127.0.0.1", self.httpd.server_port))


if __name__ == "__main__":
    unittest.main()
