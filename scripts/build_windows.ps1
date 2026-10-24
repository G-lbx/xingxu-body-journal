param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $Python) { $Python = Join-Path $taskRoot '.venv-build\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Build Python not found. Create .venv-build and install requirements-build.txt, or provide -Python with an interpreter path.'
}
$taskPython = [System.IO.Path]::GetFullPath($Python)
& $taskPython -c "import sys, struct, platform; assert sys.platform == 'win32' and struct.calcsize('P') == 8 and platform.machine().upper() in ('AMD64', 'X86_64'), 'Build requires Windows x64 Python'; import PyInstaller"
if ($LASTEXITCODE -ne 0) { throw 'Windows x64 Python with PyInstaller is required.' }
Push-Location $taskRoot
try {
    & $taskPython -m PyInstaller --noconfirm --clean --distpath (Join-Path $taskRoot 'dist') --workpath (Join-Path $taskRoot 'build') (Join-Path $taskRoot 'XingxuBodyJournal.spec')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    & $taskPython (Join-Path $PSScriptRoot 'package_windows.py')
    if ($LASTEXITCODE -ne 0) { throw 'Windows ZIP packaging failed.' }
}
finally { Pop-Location }
