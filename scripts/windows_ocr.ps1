param(
    [string]$ImagePath,
    [switch]$Check,
    [ValidateSet('all', 'left', 'right')][string]$Column = 'all'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
    $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
    $null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapTransform, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime]

    $languages = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages)
    $engine = $null
    # Simplified Chinese also recognizes the Latin labels on imported scale reports.
    $preferred = @($languages | Sort-Object @{Expression = {
        if ($_.LanguageTag -like 'zh*') { 0 } elseif ($_.LanguageTag -like 'en*') { 1 } else { 2 }
    }})
    if ($preferred.Count -gt 0) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($preferred[0])
    }
    if ($Check) {
        @{available = ($null -ne $engine); languages = @($languages | ForEach-Object {$_.LanguageTag}); engine = 'Windows OCR'} | ConvertTo-Json -Compress
        exit 0
    }
    if ($null -eq $engine) { throw 'Windows OCR has no installed recognition language.' }
    if ([string]::IsNullOrWhiteSpace($ImagePath)) { throw 'An image path is required.' }
    $resolved = (Resolve-Path -LiteralPath $ImagePath).Path

    $script:asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and
        $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    } | Select-Object -First 1
    function Await-WinRT($Operation, [Type]$ResultType) {
        $task = $script:asTask.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
        $task.Wait()
        return $task.Result
    }

    $file = Await-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($resolved)) ([Windows.Storage.StorageFile])
    $stream = Await-WinRT ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    try {
        $decoder = Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $width = [double]$decoder.PixelWidth
        $height = [double]$decoder.PixelHeight
        $limit = [double][Windows.Media.Ocr.OcrEngine]::MaxImageDimension
        $scale = [Math]::Min(1.0, $limit / [Math]::Max($width, $height))
        $transform = New-Object Windows.Graphics.Imaging.BitmapTransform
        $transform.ScaledWidth = [uint32][Math]::Max(1, [Math]::Floor($width * $scale))
        $transform.ScaledHeight = [uint32][Math]::Max(1, [Math]::Floor($height * $scale))
        $cropX = 0
        if ($Column -ne 'all') {
            $bounds = New-Object Windows.Graphics.Imaging.BitmapBounds
            $half = [uint32][Math]::Floor($transform.ScaledWidth / 2)
            $bounds.X = 0
            $bounds.Y = 0
            $bounds.Width = $half
            $bounds.Height = $transform.ScaledHeight
            if ($Column -eq 'right') {
                $bounds.X = $half
                $bounds.Width = $transform.ScaledWidth - $half
                $cropX = $half / $scale
            }
            $transform.Bounds = $bounds
        }
        $bitmap = Await-WinRT ($decoder.GetSoftwareBitmapAsync(
            [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
            [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied,
            $transform,
            [Windows.Graphics.Imaging.ExifOrientationMode]::IgnoreExifOrientation,
            [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage
        )) ([Windows.Graphics.Imaging.SoftwareBitmap])
        try {
            $result = Await-WinRT ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            $lines = @($result.Lines | ForEach-Object {
                $line = $_
                $words = @($line.Words | ForEach-Object {
                    $r = $_.BoundingRect
                    @{text = $_.Text; x = ($r.X / $scale) + $cropX; y = $r.Y / $scale; width = $r.Width / $scale; height = $r.Height / $scale}
                })
                @{text = $line.Text; words = $words}
            })
            @{text = $result.Text; lines = $lines; width = $width; height = $height; language = $engine.RecognizerLanguage.LanguageTag; engine = 'Windows OCR'} | ConvertTo-Json -Depth 9 -Compress
        } finally { if ($null -ne $bitmap) { $bitmap.Dispose() } }
    } finally { if ($null -ne $stream) { $stream.Dispose() } }
} catch {
    @{error = $_.Exception.Message; available = $false; engine = 'Windows OCR'} | ConvertTo-Json -Compress
    exit 1
}
