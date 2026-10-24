param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskServer = Join-Path $taskRoot 'server.py'
$taskData = Join-Path $taskRoot 'data'
$taskLogs = Join-Path $taskData 'logs'
$taskProcessFile = Join-Path $taskData 'server-process.json'
$taskPort = 8765
$taskUrl = 'http://127.0.0.1:8765'
$taskStartedProcess = $null
$taskReady = $false

function Test-BodyJournal {
    try {
        $taskHealth = Invoke-RestMethod -Uri ($taskUrl + '/api/health') -TimeoutSec 2
        return ($taskHealth.status -eq 'ok' -and $taskHealth.app -eq 'body-journal')
    }
    catch { return $false }
}

function Test-LocalPort {
    $taskClient = New-Object System.Net.Sockets.TcpClient
    try {
        $taskConnect = $taskClient.BeginConnect('127.0.0.1', $taskPort, $null, $null)
        if (-not $taskConnect.AsyncWaitHandle.WaitOne(500)) { return $false }
        $taskClient.EndConnect($taskConnect)
        return $taskClient.Connected
    }
    catch { return $false }
    finally { $taskClient.Close() }
}

try {
    if (-not (Test-Path -LiteralPath $taskServer -PathType Leaf)) {
        throw '未找到 server.py。请将启动入口放在完整的形序程序文件夹中。'
    }
    if (Test-BodyJournal) {
        Write-Host '形序已经运行，正在打开页面。'
        if (-not $NoBrowser) { Start-Process -FilePath $taskUrl }
        exit 0
    }
    if (Test-LocalPort) {
        throw '本机 8765 端口正在被其他程序使用。请先关闭占用该端口的程序，形序不会自动结束其他进程。'
    }

    $taskPython = $null
    $taskPythonPrefix = @()
    foreach ($taskExecutable in @('python.exe', 'python3.exe', 'py.exe')) {
        $taskCommand = Get-Command $taskExecutable -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $taskCommand) { continue }
        $taskPrefix = @()
        if ($taskExecutable -eq 'py.exe') { $taskPrefix = @('-3') }
        try {
            $taskVersionOutput = & $taskCommand.Source @taskPrefix -c 'import sys; sys.exit(1) if sys.version_info < (3,10) else print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $taskVersionOutput -is [string] -and (Test-Path -LiteralPath $taskVersionOutput -PathType Leaf)) {
                # Use the actual interpreter so the saved PID is not py.exe's launcher PID.
                $taskPython = $taskVersionOutput.Trim()
                $taskPythonPrefix = @()
                break
            }
        }
        catch { continue }
    }
    if (-not $taskPython) {
        throw '未找到 Python 3.10 或更新版本。请安装 Python 并勾选 Add Python to PATH 后重试。'
    }

    New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
    $taskArguments = @($taskPythonPrefix) + @(('"' + $taskServer + '"'), '--port', [string]$taskPort, '--data-dir', ('"' + $taskData + '"'))
    $taskStartedProcess = Start-Process -FilePath $taskPython -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskLogs 'server.stdout.log') -RedirectStandardError (Join-Path $taskLogs 'server.stderr.log') -PassThru

    for ($taskAttempt = 0; $taskAttempt -lt 40; $taskAttempt++) {
        $taskStartedProcess.Refresh()
        if ($taskStartedProcess.HasExited) { break }
        if (Test-BodyJournal) {
            $taskReady = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $taskReady) {
        throw ('本机服务未成功启动。请查看日志：' + (Join-Path $taskLogs 'server.stderr.log'))
    }
    $taskStartedProcess.Refresh()
    if ($taskStartedProcess.HasExited) {
        $taskReady = $false
        throw '服务启动后意外退出，请查看 data\logs 中的日志。'
    }
    $taskMetadata = @{
        pid = $taskStartedProcess.Id
        server_path = $taskServer
        data_dir = $taskData
        port = $taskPort
        started_utc = $taskStartedProcess.StartTime.ToUniversalTime().ToString('o')
        launcher = 'body-journal-start-v1'
    }
    $taskMetadata | ConvertTo-Json | Set-Content -LiteralPath $taskProcessFile -Encoding UTF8
    Write-Host '形序已在本机启动。关闭浏览器不会停止服务，数据会保存在当前程序文件夹的 data 目录。'
    if (-not $NoBrowser) { Start-Process -FilePath $taskUrl }
    exit 0
}
catch {
    if ($null -ne $taskStartedProcess -and -not $taskReady) {
        try {
            $taskStartedProcess.Refresh()
            if (-not $taskStartedProcess.HasExited) { $taskStartedProcess.Kill() }
        }
        catch { }
    }
    Write-Host ('启动未完成：' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
