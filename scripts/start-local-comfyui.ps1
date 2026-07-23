param(
    [string]$InstallRoot = (Join-Path $PSScriptRoot '..\runtime\comfyui')
)

$ErrorActionPreference = 'Stop'
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$PortableRoot = Join-Path $InstallRoot 'ComfyUI_windows_portable'
$ComfyRoot = Join-Path $PortableRoot 'ComfyUI'
$PythonPath = Join-Path $PortableRoot 'python_embeded\python.exe'
$LogRoot = Join-Path $InstallRoot 'logs'

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw 'ComfyUI is not installed. Run scripts\setup-local-comfyui.ps1 first.'
}

New-Item -ItemType Directory -Force -Path $LogRoot | Out-Null
$process = Start-Process -FilePath $PythonPath `
    -ArgumentList @(
        'main.py',
        '--windows-standalone-build',
        '--listen', '127.0.0.1',
        '--port', '8188',
        '--lowvram',
        '--disable-api-nodes',
        '--preview-method', 'none'
    ) `
    -WorkingDirectory $ComfyRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $LogRoot 'comfyui.log') `
    -RedirectStandardError (Join-Path $LogRoot 'comfyui-error.log') `
    -PassThru

Set-Content -LiteralPath (Join-Path $InstallRoot 'comfyui.pid') -Value $process.Id
Write-Output "ComfyUI started: PID $($process.Id), http://127.0.0.1:8188"
