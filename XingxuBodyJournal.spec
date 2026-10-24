# Windows one-folder distribution. Keep this resource list explicit: never copy
# data/, previews/, user photos, private backups, or the whole assets directory.
from pathlib import Path
from importlib import metadata
import sys

project = Path(SPECPATH)
resources = [
    ("index.html", "."),
    ("assets/app.css", "assets"),
    ("assets/app.js", "assets"),
    ("assets/armor-theme.css", "assets"),
    ("assets/armor-scan.svg", "assets"),
    ("assets/chart.js", "assets"),
    ("assets/effects.css", "assets"),
    ("assets/effects.js", "assets"),
    ("scripts/windows_ocr.ps1", "scripts"),
]
for source, _ in resources:
    if not (project / source).is_file():
        raise FileNotFoundError(f"Missing distribution resource: {source}")

# Read third-party notices from this build's actual runtimes. The separate
# directories preserve their original filenames and make the owner explicit.
python_license = Path(sys.base_prefix) / "LICENSE.txt"
pyinstaller_distribution = metadata.distribution("pyinstaller")
pyinstaller_license_entry = next(
    (
        entry for entry in (pyinstaller_distribution.files or [])
        if str(entry).replace("\\", "/").lower().endswith(".dist-info/licenses/copying.txt")
    ),
    None,
)
if not python_license.is_file() or pyinstaller_license_entry is None:
    raise FileNotFoundError("Python or PyInstaller third-party license notice is missing.")
pyinstaller_license = Path(pyinstaller_distribution.locate_file(pyinstaller_license_entry))
if not pyinstaller_license.is_file():
    raise FileNotFoundError("PyInstaller COPYING.txt is missing from the build environment.")
license_resources = [
    (str(python_license), "licenses/Python"),
    (str(pyinstaller_license), "licenses/PyInstaller"),
]

a = Analysis(
    [str(project / "desktop.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / source), target) for source, target in resources] + license_resources,
    hiddenimports=["analysis", "ocr"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="XingxuBodyJournal",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="XingxuBodyJournal",
)
