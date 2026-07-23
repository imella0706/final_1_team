param(
    [string]$InstallRoot = (Join-Path $PSScriptRoot '..\runtime\comfyui')
)

$ErrorActionPreference = 'Stop'
$InstallRoot = [System.IO.Path]::GetFullPath($InstallRoot)
$ArchivePath = Join-Path $InstallRoot 'ComfyUI_windows_portable_nvidia.7z'
$PortableRoot = Join-Path $InstallRoot 'ComfyUI_windows_portable'
$ComfyRoot = Join-Path $PortableRoot 'ComfyUI'
$CheckpointPath = Join-Path $ComfyRoot 'models\checkpoints\sd_xl_base_1.0.safetensors'
$PortableUrl = 'https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z'
$CheckpointUrl = 'https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors?download=true'

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

if (-not (Test-Path -LiteralPath $ComfyRoot)) {
    & curl.exe -L --fail --retry 5 --continue-at - --output $ArchivePath $PortableUrl
    if ($LASTEXITCODE -ne 0) { throw 'ComfyUI portable download failed.' }
    & tar.exe -xf $ArchivePath -C $InstallRoot
    if ($LASTEXITCODE -ne 0) { throw 'ComfyUI portable extraction failed.' }
}

if (-not (Test-Path -LiteralPath $CheckpointPath)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $CheckpointPath) | Out-Null
    & curl.exe -L --fail --retry 5 --continue-at - --output $CheckpointPath $CheckpointUrl
    if ($LASTEXITCODE -ne 0) { throw 'SDXL checkpoint download failed.' }
}

$PythonPath = Join-Path $PortableRoot 'python_embeded\python.exe'
if (-not (Test-Path -LiteralPath $PythonPath)) { throw "Portable Python not found: $PythonPath" }
if (-not (Test-Path -LiteralPath $CheckpointPath)) { throw "SDXL checkpoint not found: $CheckpointPath" }

Write-Output "ComfyUI ready: $ComfyRoot"
Write-Output "SDXL checkpoint ready: $CheckpointPath"
