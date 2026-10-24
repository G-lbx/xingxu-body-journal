"""Local-only Body Journal server. Python 3.10+, standard library only."""
from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import copy
import hashlib
import importlib
import io
import json
import math
import mimetypes
import os
import re
import socket
import sqlite3
import sys
import threading
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
SHANGHAI = timezone(timedelta(hours=8))
MAX_IMAGE = 12 * 1024 * 1024
MAX_BACKUP = 100 * 1024 * 1024
MAX_JSON = 17 * 1024 * 1024
IMAGE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}\.(?:jpg|jpeg|png|webp)$", re.I)
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::00)?$")
DEFAULT_PROFILE = {"name": "", "age": None, "height": None, "sex": "", "training_level": "", "training_days": None, "training_focus": "", "limitations": "", "health_context": "", "goal": "recomp"}
METRIC_RANGES = {
    "weight": (1, 500), "bmi": (3, 100), "body_fat": (0, 80),
    "fat_mass": (0, 400), "water_pct": (0, 100), "water_mass": (0, 400),
    "muscle_pct": (0, 100), "muscle_mass": (0, 400), "protein_pct": (0, 100),
    "protein_mass": (0, 200), "skeletal_pct": (0, 100), "skeletal_mass": (0, 300),
    "bmr": (100, 10000), "visceral_fat": (0, 100), "bone_mass": (0, 30),
    "fat_free_mass": (0, 500), "score": (0, 100), "body_age": (1, 150),
    "obesity_pct": (-100, 500), "weight_control": (-300, 300),
    "muscle_control": (-300, 300), "fat_control": (-300, 300),
    "standard_weight": (1, 500), "waist": (20, 300),
}


def default_data_dir():
    """Keep persistent data outside a frozen executable's temporary bundle."""
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / "XingxuBodyJournal" / "data"
    return ROOT / "data"


class ApiError(Exception):
    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.status = status
        self.payload = {"error": message, **extra}


def today_string():
    return datetime.now(SHANGHAI).date().isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def loads(text):
    def reject_constant(value):
        raise ValueError("不允许非有限数字")
    return json.loads(text, parse_constant=reject_constant)


def object_value(value, label):
    if not isinstance(value, dict):
        raise ApiError(f"{label}必须是 JSON 对象")
    return value


def number(value, label, minimum, maximum, integer=False):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{label}必须是有效数字")
    if value < minimum or value > maximum:
        raise ApiError(f"{label}须在 {minimum} 至 {maximum} 之间")
    if not math.isfinite(value):
        raise ApiError(f"{label}必须是有效数字")
    if integer and value != int(value):
        raise ApiError(f"{label}须在 {minimum} 至 {maximum} 之间" + ("，并为整数" if integer else ""))
    return int(value) if integer else value


def string(value, label, limit=2000):
    if not isinstance(value, str) or len(value) > limit:
        raise ApiError(f"{label}须为不超过 {limit} 字的文字")
    return value.strip()


def choice(value, choices, label):
    if not isinstance(value, str) or value not in choices:
        raise ApiError(f"{label}的选项无效")
    return value


def validate_date(value):
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise ApiError("日期格式须为 YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ApiError("日期无效") from None
    if not 1900 <= parsed.year <= 2100:
        raise ApiError("日期年份须在 1900 至 2100 之间")
    return value


def validate_time(value):
    if not isinstance(value, str) or not TIME_PATTERN.fullmatch(value):
        raise ApiError("测量时间格式须为 YYYY-MM-DDTHH:MM")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ApiError("测量时间无效") from None
    validate_date(value[:10])
    return parsed.strftime("%Y-%m-%dT%H:%M")


def validate_id(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ApiError("记录编号无效")
    return value


def validate_record(payload, record_id=None):
    obj = object_value(payload, "记录")
    inferred_sources = {"inferred", "derived", "device_comparison", "estimated", "comparison", "推算", "设备对比"}
    inferred_marker = any(obj.get(key) is True for key in ("inferred", "is_estimated", "derived", "is_inferred"))
    for source_key in ("source", "kind", "source_type", "record_type", "type", "provenance"):
        source_value = obj.get(source_key)
        if isinstance(source_value, dict):
            source_value = source_value.get("type") or source_value.get("kind")
        if isinstance(source_value, str) and source_value.lower() in inferred_sources:
            inferred_marker = True
    if inferred_marker:
        raise ApiError("推算数据不能保存为实测记录；请将设备上次对比保留在 device_comparison 中")
    result = {"id": validate_id(record_id or obj.get("id") or uuid.uuid4().hex), "measured_at": validate_time(obj.get("measured_at"))}
    for key, (low, high) in METRIC_RANGES.items():
        result[key] = number(obj.get(key), key, low, high)
    if result["weight"] is None:
        raise ApiError("请填写体重")
    result["note"] = string(obj.get("note", ""), "备注", 4000)
    result["source"] = choice(obj.get("source", "manual"), {"manual", "ocr_confirmed", "assistant_verified"}, "记录来源")
    upload_id = obj.get("upload_id") or None
    if upload_id is not None and (not isinstance(upload_id, str) or not IMAGE_NAME.fullmatch(upload_id)):
        raise ApiError("原图编号无效")
    result["upload_id"] = upload_id
    comparison = obj.get("device_comparison")
    result["device_comparison"] = None
    if comparison is not None:
        comparison = object_value(comparison, "设备对比")
        result["device_comparison"] = {
            "measured_at": validate_time(comparison.get("measured_at")),
            "weight_delta": number(comparison.get("weight_delta"), "体重变化", -300, 300),
            "body_fat_delta": number(comparison.get("body_fat_delta"), "体脂变化", -80, 80),
        }
    return result


def validate_profile(payload):
    obj = object_value(payload, "个人资料")
    result = copy.deepcopy(DEFAULT_PROFILE)
    result.update({key: obj[key] for key in DEFAULT_PROFILE if key in obj})
    result["name"] = string(result["name"], "姓名", 100)
    result["age"] = number(result["age"], "年龄", 1, 120, True)
    result["height"] = number(result["height"], "身高", 50, 250)
    result["sex"] = choice(result["sex"], {"", "male", "female"}, "性别")
    result["training_level"] = choice(result["training_level"], {"", "beginner", "regular", "experienced"}, "训练经验")
    result["training_days"] = number(result["training_days"], "每周训练天数", 0, 7, True)
    result["limitations"] = string(result["limitations"], "运动限制", 2000)
    result["training_focus"] = string(result["training_focus"], "训练重点", 2000)
    result["health_context"] = choice(result["health_context"], {"", "none", "special"}, "健康背景")
    result["goal"] = choice(result["goal"], {"recomp", "fat_loss", "muscle_gain", "maintain"}, "目标")
    return result


def validate_checkin(payload, checkin_date):
    obj = object_value(payload, "打卡")
    result = {"date": validate_date(checkin_date)}
    result["training"] = choice(obj.get("training", "rest"), {"rest", "strength", "cardio", "mixed"}, "训练类型")
    result["minutes"] = number(obj.get("minutes", 0), "训练分钟数", 0, 1440, True)
    if result["minutes"] is None:
        raise ApiError("请填写训练分钟数")
    result["sleep"] = number(obj.get("sleep"), "睡眠时长", 0, 24)
    result["steps"] = number(obj.get("steps"), "步数", 0, 200000, True)
    result["energy"] = choice(obj.get("energy", "normal"), {"normal", "low", "good"}, "精力状态")
    if not isinstance(obj.get("nutrition", False), bool):
        raise ApiError("饮食打卡须为布尔值")
    result["nutrition"] = obj.get("nutrition", False)
    result["note"] = string(obj.get("note", ""), "打卡备注", 4000)
    tasks = obj.get("tasks", [])
    if not isinstance(tasks, list) or len(tasks) > 100:
        raise ApiError("打卡任务无效")
    result["tasks"] = list(dict.fromkeys(string(item, "任务编号", 120) for item in tasks))
    return result


def image_type(content):
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if len(content) >= 4 and content[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise ApiError("只支持有效的 JPG、PNG 或 WebP 图片")


class Store:
    def __init__(self, data_dir, seed=True):
        # seed is accepted for older callers, but every new installation starts empty.
        self.directory = Path(data_dir).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.uploads = self.directory / "uploads"
        self.uploads.mkdir(exist_ok=True)
        self.database = self.directory / "journal.sqlite3"
        self.lock = threading.RLock()
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, measured_at TEXT UNIQUE NOT NULL, image_hash TEXT, payload TEXT NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS records_image_hash ON records(image_hash) WHERE image_hash IS NOT NULL;
                CREATE TABLE IF NOT EXISTS uploads (id TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, mime TEXT NOT NULL, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS checkins (date TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO settings VALUES ('profile', ?)", (dumps(DEFAULT_PROFILE),))
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('initialized', '1')")

    @contextlib.contextmanager
    def connection(self):
        db = sqlite3.connect(self.database, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def backup_daily(self):
        folder = self.directory / "automatic-backups"
        folder.mkdir(exist_ok=True)
        target = folder / f"autobackup-{today_string()}.sqlite3"
        if not target.exists():
            temporary = target.with_suffix(".tmp")
            try:
                with self.connection() as source:
                    with contextlib.closing(sqlite3.connect(temporary)) as destination:
                        source.backup(destination)
                temporary.replace(target)
            finally:
                if temporary.exists():
                    temporary.unlink()
        candidates = sorted(folder.glob("autobackup-????-??-??.sqlite3"))
        for stale in candidates[:-7]:
            stale.unlink()

    def export(self):
        with self.lock, self.connection() as db:
            return {
                "schema_version": 1,
                "records": [loads(row["payload"]) for row in db.execute("SELECT payload FROM records ORDER BY measured_at")],
                "profile": loads(db.execute("SELECT payload FROM settings WHERE key='profile'").fetchone()["payload"]),
                "checkins": [loads(row["payload"]) for row in db.execute("SELECT payload FROM checkins ORDER BY date")],
            }

    def state(self):
        result = self.export()
        result.pop("schema_version")
        try:
            analyzer = importlib.import_module("analysis")
            result["analysis"] = analyzer.build_analysis(result["records"], result["profile"], result["checkins"])
        except ImportError:
            result["analysis"] = {"status": "unavailable", "message": "分析模块尚未安装，测量记录仍可使用。"}
        try:
            result["ocr_available"] = bool(importlib.import_module("ocr").available())
        except ImportError:
            result["ocr_available"] = False
        result["today"] = today_string()
        result["server_time"] = datetime.now(SHANGHAI).isoformat(timespec="seconds")
        return result

    def image_hash(self, db, upload_id):
        if not upload_id:
            return None
        row = db.execute("SELECT sha256 FROM uploads WHERE id=?", (upload_id,)).fetchone()
        return row["sha256"] if row else None

    def conflict(self, db, record, image_hash):
        conflict = db.execute("SELECT id FROM records WHERE measured_at=? AND id<>?", (record["measured_at"], record["id"])).fetchone()
        if conflict:
            return conflict["id"], "这个测量时间已有记录，请编辑已有记录或核对时间"
        if image_hash:
            conflict = db.execute("SELECT id FROM records WHERE image_hash=? AND id<>?", (image_hash, record["id"])).fetchone()
            if conflict:
                return conflict["id"], "这张图片已经保存为测量记录"
        return None

    def save_record(self, payload, record_id=None):
        with self.lock, self.connection() as db:
            if record_id is not None:
                validate_id(record_id)
                old = db.execute("SELECT payload FROM records WHERE id=?", (record_id,)).fetchone()
                if not old:
                    raise ApiError("记录不存在", 404)
                merged = loads(old["payload"])
                merged.update(object_value(payload, "记录"))
                record = validate_record(merged, record_id)
            else:
                record = validate_record(payload)
                if db.execute("SELECT 1 FROM records WHERE id=?", (record["id"],)).fetchone():
                    raise ApiError("记录编号已存在", 409, existing_id=record["id"])
            if record["upload_id"] and not db.execute("SELECT 1 FROM uploads WHERE id=?", (record["upload_id"],)).fetchone():
                old_upload = loads(old["payload"]).get("upload_id") if record_id else None
                if record["upload_id"] != old_upload:
                    raise ApiError("原图尚未上传，请先上传图片")
            digest = self.image_hash(db, record["upload_id"])
            conflict = self.conflict(db, record, digest)
            if conflict:
                raise ApiError(conflict[1], 409, existing_id=conflict[0])
            self.backup_daily()
            db.execute("INSERT INTO records VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET measured_at=excluded.measured_at,image_hash=excluded.image_hash,payload=excluded.payload", (record["id"], record["measured_at"], digest, dumps(record)))
            return record

    def delete_record(self, record_id):
        validate_id(record_id)
        with self.lock, self.connection() as db:
            if not db.execute("SELECT 1 FROM records WHERE id=?", (record_id,)).fetchone():
                raise ApiError("记录不存在", 404)
            self.backup_daily()
            db.execute("DELETE FROM records WHERE id=?", (record_id,))

    def save_profile(self, payload):
        with self.lock, self.connection() as db:
            existing = loads(db.execute("SELECT payload FROM settings WHERE key='profile'").fetchone()["payload"])
            existing.update(object_value(payload, "个人资料"))
            profile = validate_profile(existing)
            self.backup_daily()
            db.execute("UPDATE settings SET payload=? WHERE key='profile'", (dumps(profile),))
            return profile

    def save_checkin(self, payload, checkin_date):
        checkin = validate_checkin(payload, checkin_date)
        with self.lock, self.connection() as db:
            self.backup_daily()
            db.execute("INSERT INTO checkins VALUES (?, ?) ON CONFLICT(date) DO UPDATE SET payload=excluded.payload", (checkin_date, dumps(checkin)))
        return checkin

    def upload(self, payload):
        payload = object_value(payload, "上传内容")
        name = string(payload.get("name", "测量截图"), "文件名", 255)
        data_url = payload.get("dataUrl")
        if not isinstance(data_url, str):
            raise ApiError("图片内容缺失")
        match = re.fullmatch(r"data:(image/(?:jpeg|jpg|png|webp));base64,([A-Za-z0-9+/=\r\n]+)", data_url)
        if not match:
            raise ApiError("图片编码无效，请选择 JPG、PNG 或 WebP 图片")
        try:
            content = base64.b64decode(match.group(2).replace("\r", "").replace("\n", ""), validate=True)
        except (ValueError, binascii.Error):
            raise ApiError("图片编码无效") from None
        if not content or len(content) > MAX_IMAGE:
            raise ApiError("图片须小于或等于 12 MB", 413)
        extension, mime = image_type(content)
        declared = "image/jpeg" if match.group(1) == "image/jpg" else match.group(1)
        if declared != mime:
            raise ApiError("图片内容与文件类型不一致")
        digest = hashlib.sha256(content).hexdigest()
        with self.lock, self.connection() as db:
            prior = db.execute("SELECT id FROM uploads WHERE sha256=?", (digest,)).fetchone()
            upload_id = prior["id"] if prior else f"{uuid.uuid4().hex}.{extension}"
            destination = self.uploads / upload_id
            if not destination.exists():
                destination.write_bytes(content)
            if not prior:
                self.backup_daily()
                db.execute("INSERT INTO uploads VALUES (?, ?, ?, ?)", (upload_id, digest, mime, name))
            record = db.execute("SELECT id FROM records WHERE image_hash=?", (digest,)).fetchone()
        try:
            result = importlib.import_module("ocr").extract_image(destination)
            if not isinstance(result, dict):
                raise ValueError("无效识别结果")
            result = {"fields": result.get("fields", {}), "raw_text": result.get("raw_text", ""), "warnings": result.get("warnings", []), "engine": result.get("engine", "unknown")}
        except Exception:
            result = {"fields": {}, "raw_text": "", "warnings": ["当前无法完成自动识别。图片已保存，请对照原图填写并核对数据。"], "engine": "unavailable"}
        result.update({"upload_id": upload_id, "image_url": f"/uploads/{upload_id}", "filename": name})
        if record:
            result["duplicate_record_id"] = record["id"]
        return result

    def validate_import(self, payload):
        payload = object_value(payload, "备份")
        if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
            raise ApiError("不支持的备份版本，当前仅支持版本 1")
        if not isinstance(payload.get("records"), list) or len(payload["records"]) > 50000:
            raise ApiError("备份中的记录列表无效")
        for item in payload["records"]:
            validate_id(object_value(item, "记录").get("id"))
        records = [validate_record(item) for item in payload["records"]]
        if len({item["id"] for item in records}) != len(records):
            raise ApiError("备份中存在重复的记录编号")
        if len({item["measured_at"] for item in records}) != len(records):
            raise ApiError("备份中存在相同测量时间的重复记录")
        profile = validate_profile(payload.get("profile", DEFAULT_PROFILE))
        raw_checkins = payload.get("checkins", [])
        if not isinstance(raw_checkins, list) or len(raw_checkins) > 50000:
            raise ApiError("备份中的打卡列表无效")
        checkins = [validate_checkin(item, object_value(item, "打卡").get("date")) for item in raw_checkins]
        if len({item["date"] for item in checkins}) != len(checkins):
            raise ApiError("备份中存在重复的打卡日期")
        return {"records": records, "profile": profile, "checkins": checkins}

    def import_data(self, payload, image_files=None):
        validated = self.validate_import(payload)
        image_files = image_files or {}
        result = {"imported": 0, "skipped": 0, "checkins_imported": 0, "checkins_skipped": 0, "images_restored": 0, "profile_updated": False, "conflicts": [], "warnings": []}
        with self.lock:
            self.backup_daily()
            created = []
            try:
                with self.connection() as db:
                    remap = {}
                    for filename, content in image_files.items():
                        extension, mime = image_type(content)
                        digest = hashlib.sha256(content).hexdigest()
                        prior_hash = db.execute("SELECT id FROM uploads WHERE sha256=?", (digest,)).fetchone()
                        if prior_hash:
                            actual_name = prior_hash["id"]
                        else:
                            actual_name = filename
                            target = self.uploads / actual_name
                            if db.execute("SELECT 1 FROM uploads WHERE id=?", (filename,)).fetchone() or (target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest):
                                actual_name = f"{uuid.uuid4().hex}.{extension}"
                            db.execute("INSERT INTO uploads VALUES (?, ?, ?, ?)", (actual_name, digest, mime, filename))
                        target = self.uploads / actual_name
                        if not target.exists():
                            target.write_bytes(content)
                            created.append(target)
                            result["images_restored"] += 1
                        remap[filename] = actual_name
                    for record in validated["records"]:
                        if record["upload_id"] in remap:
                            record["upload_id"] = remap[record["upload_id"]]
                        existing = db.execute("SELECT payload, image_hash FROM records WHERE id=?", (record["id"],)).fetchone()
                        digest = self.image_hash(db, record["upload_id"])
                        conflict = self.conflict(db, record, digest)
                        if existing or conflict:
                            result["skipped"] += 1
                            if existing and not existing["image_hash"] and not conflict and digest:
                                current = loads(existing["payload"])
                                if current.get("upload_id") == record.get("upload_id"):
                                    db.execute("UPDATE records SET image_hash=? WHERE id=?", (digest, record["id"]))
                            if conflict:
                                result["conflicts"].append({"id": record["id"], "existing_id": conflict[0], "reason": conflict[1]})
                            continue
                        db.execute("INSERT INTO records VALUES (?, ?, ?, ?)", (record["id"], record["measured_at"], digest, dumps(record)))
                        result["imported"] += 1
                    for checkin in validated["checkins"]:
                        if db.execute("SELECT 1 FROM checkins WHERE date=?", (checkin["date"],)).fetchone():
                            result["checkins_skipped"] += 1
                        else:
                            db.execute("INSERT INTO checkins VALUES (?, ?)", (checkin["date"], dumps(checkin)))
                            result["checkins_imported"] += 1
                    profile = loads(db.execute("SELECT payload FROM settings WHERE key='profile'").fetchone()["payload"])
                    was_default_profile = profile == DEFAULT_PROFILE
                    for key, value in validated["profile"].items():
                        if profile.get(key) in (None, "") and value not in (None, ""):
                            profile[key] = value
                            result["profile_updated"] = True
                    if was_default_profile:
                        profile = validated["profile"]
                        result["profile_updated"] = profile != DEFAULT_PROFILE
                    db.execute("UPDATE settings SET payload=? WHERE key='profile'", (dumps(profile),))
                    missing = sum(1 for item in validated["records"] if item["upload_id"] and not (self.uploads / item["upload_id"]).is_file())
                    if missing:
                        result["warnings"].append(f"有 {missing} 条记录的原图不在本机。JSON 备份只包含数据；恢复原图请使用完整 ZIP 备份。")
                    result["warnings"].append("合并导入会保留已有记录与同日打卡；个人资料仅补充空白字段。")
            except Exception:
                for path in created:
                    path.unlink(missing_ok=True)
                raise
        return result

    def backup_archive(self):
        with self.lock:
            exported = self.export()
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("export.json", dumps(exported))
                for filename in sorted({item["upload_id"] for item in exported["records"] if item["upload_id"]}):
                    path = self.uploads / filename
                    if path.is_file():
                        archive.write(path, f"uploads/{filename}")
                archive.writestr("README.txt", "个人身体日志完整备份。使用程序中的“恢复 ZIP 备份”导入。export.json 为结构化记录，uploads 为测量原图。\n")
            return buffer.getvalue()

    def restore_archive(self, payload):
        payload = object_value(payload, "恢复内容")
        encoded = payload.get("dataBase64")
        if not isinstance(encoded, str):
            raise ApiError("备份内容缺失")
        if len(encoded) > (MAX_BACKUP + 2) // 3 * 4:
            raise ApiError("备份文件须小于或等于 100 MB", 413)
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ApiError("备份编码无效") from None
        if len(content) > MAX_BACKUP:
            raise ApiError("备份文件须小于或等于 100 MB", 413)
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if len(entries) > 50002 or sum(item.file_size for item in entries) > MAX_BACKUP:
                    raise ApiError("备份解压后超过 100 MB 限制", 413)
                if len({item.filename for item in entries}) != len(entries):
                    raise ApiError("备份中存在重复文件")
                images = {}
                exported = None
                for info in entries:
                    if info.flag_bits & 1:
                        raise ApiError("不支持加密 ZIP 备份")
                    filename = info.filename
                    if filename == "export.json":
                        exported = loads(archive.read(info).decode("utf-8-sig"))
                    elif filename == "README.txt":
                        continue
                    elif filename.startswith("uploads/") and IMAGE_NAME.fullmatch(filename[8:]):
                        if info.file_size > MAX_IMAGE:
                            raise ApiError("备份中有图片超过 12 MB 限制", 413)
                        data = archive.read(info)
                        image_type(data)
                        images[filename[8:]] = data
                    else:
                        raise ApiError("备份包含不支持的文件或不安全路径")
                if exported is None:
                    raise ApiError("备份缺少 export.json")
                return self.import_data(exported, images)
        except (zipfile.BadZipFile, UnicodeDecodeError, ValueError, RuntimeError, EOFError):
            raise ApiError("ZIP 备份已损坏或内容格式无效") from None


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"
    allow_reuse_port = False

    def __init__(self, address, store):
        self.store = store
        super().__init__(address, Handler)

    def server_bind(self):
        # On Windows SO_REUSEADDR permits another process to steal a live listener.
        # Exclusive binding makes a collision fail so the desktop launcher can
        # choose another port without connecting a user to a different database.
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    server_version = "BodyJournal/1.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        # Do not print URLs, record contents, or filenames containing private data.
        return

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def respond(self, payload, status=200):
        content = dumps(payload).encode("utf-8")
        self.send_bytes(content, "application/json; charset=utf-8", status)

    def send_bytes(self, content, content_type, status=200, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def verify_request(self):
        port = self.server.server_port
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed_hosts.update({"127.0.0.1", "localhost"})
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in allowed_hosts:
            raise ApiError("只允许从本机访问此程序", 403)
        origin = self.headers.get("Origin")
        if origin and origin.lower() not in {f"http://{host}" for host in allowed_hosts}:
            raise ApiError("请求来源不被允许，请从本机程序页面操作", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise ApiError("不允许跨站访问本机数据", 403)

    def body(self, maximum=MAX_JSON):
        if self.headers.get_content_type() != "application/json":
            raise ApiError("请求内容须为 application/json", 415)
        if self.headers.get("Transfer-Encoding"):
            raise ApiError("不支持分块上传", 400)
        values = self.headers.get_all("Content-Length", [])
        if len(values) != 1 or not values[0].isdigit():
            raise ApiError("请求缺少有效的内容长度", 411)
        length = int(values[0])
        if length < 1 or length > maximum:
            raise ApiError("请求内容为空或超过大小限制", 413)
        self.connection.settimeout(30)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ApiError("上传内容不完整")
        try:
            return loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise ApiError("JSON 格式无效，请检查数据") from None

    def dispatch(self):
        try:
            self.verify_request()
            path = unquote(urlsplit(self.path).path)
            if "\x00" in path or "\\" in path:
                raise ApiError("路径无效", 404)
            method = self.command
            store = self.server.store
            if method in {"GET", "HEAD"}:
                if path == "/api/health":
                    health = {"status": "ok", "app": "body-journal", "version": 1, "today": today_string()}
                    desktop_instance = getattr(self.server, "desktop_instance", None)
                    if desktop_instance is not None:
                        health["desktop_instance"] = desktop_instance
                    return self.respond(health)
                if path == "/api/state":
                    return self.respond(store.state())
                if path == "/api/export":
                    return self.send_bytes(dumps(store.export()).encode("utf-8"), "application/json; charset=utf-8", filename=f"body-journal-{today_string()}.json")
                if path == "/api/backup":
                    return self.send_bytes(store.backup_archive(), "application/zip", filename=f"body-journal-{today_string()}.zip")
                if path in {"/", "/index.html"}:
                    target = ROOT / "index.html"
                elif path.startswith("/assets/"):
                    base = (ROOT / "assets").resolve()
                    target = (ROOT / path.lstrip("/")).resolve()
                    if not target.is_relative_to(base) or target.suffix.lower() not in {".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2"}:
                        raise ApiError("文件不存在", 404)
                elif path.startswith("/uploads/") and IMAGE_NAME.fullmatch(path[9:]):
                    target = store.uploads / path[9:]
                else:
                    raise ApiError("页面或接口不存在", 404)
                if not target.is_file():
                    raise ApiError("文件不存在", 404)
                content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if target.suffix.lower() in {".html", ".css", ".js", ".svg"}:
                    content_type += "; charset=utf-8"
                return self.send_bytes(target.read_bytes(), content_type)
            if method == "POST" and path == "/api/restore":
                return self.respond(store.restore_archive(self.body((MAX_BACKUP + 2) // 3 * 4 + 1024)))
            if method == "POST" and path == "/api/upload":
                return self.respond(store.upload(self.body()), 201)
            if method == "POST" and path == "/api/records":
                return self.respond({"record": store.save_record(self.body())}, 201)
            if method == "POST" and path == "/api/import":
                return self.respond(store.import_data(self.body()))
            if method == "PUT" and path == "/api/profile":
                return self.respond({"profile": store.save_profile(self.body())})
            if method == "PUT" and path.startswith("/api/checkins/"):
                return self.respond({"checkin": store.save_checkin(self.body(), path[14:])})
            if path.startswith("/api/records/"):
                record_id = path[13:]
                if method == "PUT":
                    return self.respond({"record": store.save_record(self.body(), record_id)})
                if method == "DELETE":
                    self.body()
                    store.delete_record(record_id)
                    return self.respond({"deleted": record_id})
            raise ApiError("接口不存在或请求方法不支持", 404)
        except ApiError as error:
            self.respond(error.payload, error.status)
        except (BrokenPipeError, ConnectionResetError):
            return
        except (TimeoutError, OSError, sqlite3.Error):
            self.respond({"error": "本地文件或数据库操作失败，请检查可用磁盘空间后重试。"}, 500)
        except Exception:
            self.respond({"error": "操作未完成，请刷新后重试。"}, 500)

    do_GET = dispatch
    do_HEAD = dispatch
    do_POST = dispatch
    do_PUT = dispatch
    do_DELETE = dispatch
    do_OPTIONS = dispatch


def create_server(host="127.0.0.1", port=8765, data_dir=None, seed=True):
    if host != "127.0.0.1":
        raise ValueError("此程序仅支持绑定 127.0.0.1")
    return LocalServer((host, port), Store(data_dir or default_data_dir(), seed=seed))


def main():
    parser = argparse.ArgumentParser(description="个人身体日志 — 本机运行")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--no-seed", action="store_true", help="旧版本兼容参数；新数据库始终为空白")
    args = parser.parse_args()
    server = create_server(port=args.port, data_dir=args.data_dir, seed=not args.no_seed)
    print(f"Body Journal: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
