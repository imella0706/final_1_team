param(
    [string]$ComfyInstallRoot = (Join-Path $PSScriptRoot '..\runtime\comfyui'),
    [switch]$SkipImageModels,
    [switch]$SkipLlmModels
)

$ErrorActionPreference = 'Stop'
$ComfyInstallRoot = [System.IO.Path]::GetFullPath($ComfyInstallRoot)
$PortableRoot = Join-Path $ComfyInstallRoot 'ComfyUI_windows_portable'
$ComfyRoot = Join-Path $PortableRoot 'ComfyUI'
$PythonPath = Join-Path $PortableRoot 'python_embeded\python.exe'

function Receive-ModelFile {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string]$ExpectedSha256
    )

    if (Test-Path -LiteralPath $Destination) {
        if ($ExpectedSha256) {
            $existingSha256 = (
                Get-FileHash -LiteralPath $Destination -Algorithm SHA256
            ).Hash
            if ($existingSha256 -ne $ExpectedSha256) {
                throw "Existing model checksum mismatch: $Destination"
            }
        }
        Write-Output "Already present: $Destination"
        return
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) |
        Out-Null
    $aria2 = Get-Command aria2c -ErrorAction SilentlyContinue
    if ($aria2) {
        $downloadDirectory = Split-Path -Parent $Destination
        $downloadName = Split-Path -Leaf $Destination
        & $aria2.Source `
            --continue=true `
            --max-connection-per-server=16 `
            --split=16 `
            --min-split-size=16M `
            --file-allocation=none `
            --dir=$downloadDirectory `
            --out=$downloadName `
            $Url
        if ($LASTEXITCODE -ne 0) {
            & $aria2.Source `
                --continue=true `
                --max-connection-per-server=4 `
                --split=4 `
                --min-split-size=16M `
                --file-allocation=none `
                --dir=$downloadDirectory `
                --out=$downloadName `
                $Url
        }
    }
    else {
        & curl.exe `
            -L `
            --fail `
            --retry 5 `
            --continue-at - `
            --output $Destination `
            $Url
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Destination)) {
        throw "Model download failed: $Destination"
    }
    if ($ExpectedSha256) {
        $actualSha256 = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
        if ($actualSha256 -ne $ExpectedSha256) {
            throw "Model checksum mismatch: $Destination"
        }
    }
}

if (-not $SkipImageModels) {
    if (-not (Test-Path -LiteralPath $ComfyRoot)) {
        throw 'ComfyUI is not installed. Run scripts/setup-local-comfyui.ps1 first.'
    }
    if (-not (Test-Path -LiteralPath $PythonPath)) {
        throw "Portable Python not found: $PythonPath"
    }

    $customNodePath = Join-Path $ComfyRoot 'custom_nodes\ComfyUI-GGUF'
    if (-not (Test-Path -LiteralPath $customNodePath)) {
        & git clone https://github.com/city96/ComfyUI-GGUF.git $customNodePath
        if ($LASTEXITCODE -ne 0) { throw 'ComfyUI-GGUF clone failed.' }
    }
    & $PythonPath -s -m pip install -r (Join-Path $customNodePath 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'ComfyUI-GGUF dependency install failed.' }

    Receive-ModelFile `
        -Url 'https://huggingface.co/stabilityai/sdxl-turbo/resolve/main/sd_xl_turbo_1.0_fp16.safetensors?download=true' `
        -Destination (Join-Path $ComfyRoot 'models\checkpoints\sd_xl_turbo_1.0_fp16.safetensors')
    Receive-ModelFile `
        -Url 'https://huggingface.co/city96/FLUX.1-schnell-gguf/resolve/main/flux1-schnell-Q4_K_S.gguf?download=true' `
        -Destination (Join-Path $ComfyRoot 'models\unet\flux1-schnell-Q4_K_S.gguf')
    Receive-ModelFile `
        -Url 'https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors?download=true' `
        -Destination (Join-Path $ComfyRoot 'models\clip\clip_l.safetensors')
    Receive-ModelFile `
        -Url 'https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors?download=true' `
        -Destination (Join-Path $ComfyRoot 'models\clip\t5xxl_fp8_e4m3fn.safetensors')
    Receive-ModelFile `
        -Url 'https://huggingface.co/DeepBeepMeep/Flux/resolve/main/flux_vae.safetensors?download=true' `
        -Destination (Join-Path $ComfyRoot 'models\vae\ae.safetensors') `
        -ExpectedSha256 'AFC8E28272CD15DB3919BACDB6918CE9C1ED22E96CB12C4D5ED0FBA823529E38'
}

if (-not $SkipLlmModels) {
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        throw 'Ollama is not installed. Install it, then run this script again.'
    }
    & ollama pull qwen2.5:1.5b
    if ($LASTEXITCODE -ne 0) { throw 'qwen2.5:1.5b pull failed.' }
    & ollama pull qwen2.5:7b
    if ($LASTEXITCODE -ne 0) { throw 'qwen2.5:7b pull failed.' }
    & ollama pull mistral:7b
    if ($LASTEXITCODE -ne 0) { throw 'mistral:7b pull failed.' }
    & ollama pull qwen2.5vl:7b
    if ($LASTEXITCODE -ne 0) { throw 'qwen2.5vl:7b pull failed.' }
    & ollama pull qwen3-vl:2b-instruct
    if ($LASTEXITCODE -ne 0) { throw 'qwen3-vl:2b-instruct pull failed.' }
    & ollama pull qwen3-vl:4b-instruct
    if ($LASTEXITCODE -ne 0) { throw 'qwen3-vl:4b-instruct pull failed.' }
    & ollama pull qwen3-vl:8b-instruct
    if ($LASTEXITCODE -ne 0) { throw 'qwen3-vl:8b-instruct pull failed.' }
}

Write-Output 'Local benchmark models are ready.'
