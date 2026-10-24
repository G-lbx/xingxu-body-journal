"""Package only the generated one-folder app; never read the user's data."""
from pathlib import Path
import hashlib
import zipfile


def package(root=None):
    root = Path(root or Path(__file__).resolve().parent.parent)
    folder = root / "dist" / "XingxuBodyJournal"
    if not (folder / "XingxuBodyJournal.exe").is_file():
        raise RuntimeError("Build dist/XingxuBodyJournal first.")
    destination = root / "dist" / "XingxuBodyJournal-Windows-x64.zip"
    # Prevent accidental inclusion if a developer previously ran a build with
    # --data-dir inside dist/ or copied real photos there during a local test.
    forbidden_parts = {"data", "uploads", "backups", "preview", ".git", ".qa"}
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(folder)
        if path.is_symlink() or any(part.lower() in forbidden_parts for part in relative.parts):
            raise RuntimeError(f"Refusing to package non-distribution path: {relative}")
        if path.suffix.lower() in {".sqlite", ".sqlite3", ".db", ".jpg", ".jpeg", ".webp"}:
            raise RuntimeError(f"Refusing to package user-data file: {relative}")
    readme = (
        "形序 · 身体控制中心\n\n"
        "1. 请先将整个 ZIP 解压到任意文件夹，再双击 XingxuBodyJournal.exe。\n"
        "2. 程序会打开本机网页。使用期间请保留形序控制窗口。\n"
        "3. 首次使用请填写个人档案，再导入截图并核对后保存。\n"
        "4. 数据保存在 %LOCALAPPDATA%\\XingxuBodyJournal\\data，升级前可在页面导出 ZIP 备份。\n"
        "5. 使用控制窗口的“停止并退出”结束程序；关闭浏览器不会丢失数据。\n\n"
        "需要 Windows 10/11 x64，不需要另外安装 Python。OCR 使用 Windows 本机识别能力。\n"
        "若 Windows OCR 不可用，仍可以手动录入数值。识别后请核对日期、单位和数值。\n"
        "仅监听 127.0.0.1，不会公开网页或上传体测照片。建议由公开指南与本机规则生成。\n"
    )
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, path.relative_to(folder.parent).as_posix())
        archive.writestr("XingxuBodyJournal/开始使用.txt", readme.encode("utf-8-sig"))
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_suffix(destination.suffix + ".sha256")
    checksum.write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    print(destination)
    print(f"SHA256 {digest}")
    return destination


if __name__ == "__main__":
    package()
