"""Archive the explicit app bundle using ditto to preserve permissions/symlinks."""
import hashlib
from pathlib import Path
import platform
import subprocess
import sys

def package(root):
    if sys.platform != 'darwin':
        raise RuntimeError('macOS packaging requires macOS.')
    root = Path(root).resolve()
    app = root / 'dist' / 'XingxuBodyJournal.app'
    if not (app / 'Contents/MacOS/XingxuBodyJournal').is_file():
        raise FileNotFoundError('Build the app first.')
    for path in app.rglob('*'):
        parts = {part.lower() for part in path.relative_to(app).parts}
        if parts & {'data', 'uploads', 'preview', 'private-fixtures', '.git', '.env', 'automatic-backups'} or path.suffix.lower() in {'.sqlite3', '.db', '.jpg', '.jpeg', '.webp'} or path.name.startswith('body-report-'):
            raise RuntimeError(f'Unexpected non-distribution resource: {path.relative_to(app)}')
    arch = platform.machine()
    suffix = {'arm64': 'AppleSilicon', 'x86_64': 'Intel'}[arch]
    output = root / 'dist' / f'XingxuBodyJournal-macOS-{suffix}.zip'
    subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app), str(output)], check=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(f'{digest}  {output.name}\n', encoding='utf-8')
    print(f'{output.name}: {output.stat().st_size} bytes, SHA256 {digest}', flush=True)
    return output

if __name__ == '__main__':
    package(Path(__file__).resolve().parent.parent)
