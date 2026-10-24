$ErrorActionPreference = 'Stop'
$taskRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskServer = Join-Path $taskRoot 'server.py'
$taskData = Join-Path $taskRoot 'data'
$taskProcessFile = Join-Path $taskData 'server-process.json'
$taskStage = '读取启动记录'

try {
    if (-not (Test-Path -LiteralPath $taskProcessFile -PathType Leaf)) {
        Write-Host '没有找到由启动入口保存的进程记录，因此未结束任何进程。'
        Write-Host '如果服务是从终端手动启动的，请回到该终端按 Ctrl+C；停止后可使用“启动形序.cmd”重新启动。'
        exit 0
    }
    $taskMetadata = Get-Content -LiteralPath $taskProcessFile -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($taskMetadata.launcher -ne 'body-journal-start-v1' -or $taskMetadata.port -ne 8765 -or -not [string]::Equals([string]$taskMetadata.server_path, $taskServer, [System.StringComparison]::OrdinalIgnoreCase) -or -not [string]::Equals([string]$taskMetadata.data_dir, $taskData, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw '进程记录与当前程序目录不匹配，未结束任何进程。'
    }
    $taskPid = 0
    if (-not [int]::TryParse([string]$taskMetadata.pid, [ref]$taskPid) -or $taskPid -le 0) {
        throw '进程记录中的编号无效，未结束任何进程。'
    }
    $taskStage = '核验服务身份'
    $taskProcessInfo = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $taskPid) -ErrorAction Stop
    if ($null -eq $taskProcessInfo) {
        Remove-Item -LiteralPath $taskProcessFile
        Write-Host '形序服务已经停止。历史记录与图片均保留。'
        exit 0
    }
    $taskLine = [string]$taskProcessInfo.CommandLine
    $taskServerPattern = '(?i)(?:^|\s)"?' + [regex]::Escape($taskServer) + '"?(?:\s|$)'
    $taskDataPattern = '(?i)--data-dir\s+"?' + [regex]::Escape($taskData) + '"?(?:\s|$)'
    if ($taskProcessInfo.Name -notmatch '^python(?:w|\d+(?:\.\d+)?)?\.exe$' -or $taskLine -notmatch $taskServerPattern -or $taskLine -notmatch '(?:^|\s)--port\s+8765(?:\s|$)' -or $taskLine -notmatch $taskDataPattern) {
        throw '该进程并非此目录启动的形序服务，未结束任何进程。请检查 data\server-process.json。'
    }
    $taskStartedUtc = [DateTime]::Parse([string]$taskMetadata.started_utc, [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
    if ($null -eq $taskProcessInfo.CreationDate) {
        throw '无法核验该进程的启动时间，未结束任何进程。'
    }
    $taskCreationUtc = ([DateTime]$taskProcessInfo.CreationDate).ToUniversalTime()
    if ([Math]::Abs(($taskCreationUtc - $taskStartedUtc).TotalSeconds) -gt 2) {
        throw '该进程的启动时间与记录不匹配，未结束任何进程。'
    }
    $taskStage = '结束已核验服务'
    $taskTermination = Invoke-CimMethod -InputObject $taskProcessInfo -MethodName Terminate -ErrorAction Stop
    if ($null -eq $taskTermination -or $null -eq $taskTermination.ReturnValue -or $taskTermination.ReturnValue -ne 0) {
        $taskReturnCode = if ($null -eq $taskTermination) { '未知' } else { [string]$taskTermination.ReturnValue }
        throw ('系统未能结束服务，返回码：' + $taskReturnCode + '。进程记录已保留，请稍后再试。')
    }
    $taskStage = '确认服务退出'
    $taskExited = $false
    for ($taskAttempt = 0; $taskAttempt -lt 20; $taskAttempt++) {
        $taskRemaining = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $taskPid) -ErrorAction Stop
        if ($null -eq $taskRemaining -or ($null -ne $taskRemaining.CreationDate -and ([DateTime]$taskRemaining.CreationDate).ToUniversalTime() -ne $taskCreationUtc)) {
            # A reused PID belongs to a new process; never send it another termination request.
            $taskExited = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $taskExited) {
        throw '服务尚未停止，请稍后再试。'
    }
    $taskStage = '清理已退出服务的启动记录'
    Remove-Item -LiteralPath $taskProcessFile
    Write-Host '形序服务已停止。历史记录与原图均保留，下次双击“启动形序.cmd”可继续使用。'
    exit 0
}
catch {
    Write-Host ('停止未完成（' + $taskStage + '）：' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
