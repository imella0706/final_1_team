# BrandMate CosyVoice Service

This optional local service runs `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` behind a
small HTTP API. BrandMate uses it first and can fall back to OpenAI TTS when the
local service is unavailable.

## Requirements

- NVIDIA RTX 4060 Laptop GPU with a recent Windows NVIDIA driver
- WSL2 with Ubuntu 22.04
- About 15 GB of free disk space for the repository, environment, and model
- A short, clean WAV reference recording that you own or are authorized to use

Do not use another person's voice without permission. The default service is
bound to port `50000` and processes one request at a time to control VRAM use.

## Install in WSL

Open an Ubuntu WSL terminal and run:

```bash
sudo apt update
sudo apt install -y git git-lfs build-essential sox libsox-dev python3.10 python3.10-dev python3.10-venv
cd /mnt/c/Users/ASUS/Downloads/finalproject12/final_1_team/services/cosyvoice
bash setup.sh
```

The model and Python environment are stored in the WSL filesystem under
`~/.local/share/brandmate-cosyvoice` for better I/O performance. Set
`BRANDMATE_COSYVOICE_HOME` before setup and start to use another location.

Place the authorized reference recording here:

```text
services/cosyvoice/voices/default.wav
```

A mono WAV with clear speech and little background noise works best. Additional
named voices can be added as `voices/<name>.wav`.

## Run

From the same WSL terminal:

```bash
cd /mnt/c/Users/ASUS/Downloads/finalproject12/final_1_team/services/cosyvoice
bash start.sh
```

Check readiness from Windows PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:50000/health
```

Then restart `start-brandmate.cmd`. The API settings in `apps/api/.env` select
CosyVoice first. If it is not ready, BrandMate automatically tries the existing
OpenAI TTS models when `BRANDMATE_COSYVOICE_FALLBACK_TO_OPENAI=true`.

## API

```text
GET  /health
POST /v1/tts
```

Example request:

```powershell
$body = @{
  input = "새로운 하루를 더 맛있게 시작하세요."
  voice = "default"
  instructions = "밝고 자연스러운 한국어 광고 성우 톤"
  speed = 1.0
} | ConvertTo-Json

Invoke-WebRequest http://127.0.0.1:50000/v1/tts `
  -Method Post -ContentType "application/json" -Body $body -OutFile sample.wav
```

The first generation loads the model and is slower than later requests.

BrandMate defaults to `COSYVOICE_INFERENCE_MODE=cross_lingual`. This sends only
the narration script after CosyVoice's system marker, preventing acting
instructions from leaking into generated speech. The reference recording and
speed control still affect the result. The experimental `instruct` mode can be
enabled with an environment variable, but may speak parts of the instruction.

## Troubleshooting

If installation previously stopped while building `openai-whisper` with
`ModuleNotFoundError: No module named 'pkg_resources'`, pull the updated setup
script and run it again:

```bash
cd /mnt/c/Users/ASUS/Downloads/finalproject12/final_1_team/services/cosyvoice
bash setup.sh
```

The script keeps `setuptools` below version 81 and builds the CosyVoice-pinned
Whisper release without an isolated build environment. The existing repository
and virtual environment are reused.

If `pyworld` fails with `x86_64-linux-gnu-g++: No such file or directory`, install
the native build tools and run setup again:

```bash
sudo apt update
sudo apt install -y build-essential python3.10-dev
bash setup.sh
```

After installation, verify the final environment rather than intermediate pip
resolver warnings:

```bash
VENV="$HOME/.local/share/brandmate-cosyvoice/venv"
"$VENV/bin/pip" check
"$VENV/bin/python" -c 'import torch; print(torch.cuda.is_available())'
```

If model loading fails with `CUDA_HOME does not exist, unable to compile CUDA
op(s)`, remove the optional DeepSpeed training package and restart the service:

```bash
VENV="$HOME/.local/share/brandmate-cosyvoice/venv"
"$VENV/bin/pip" uninstall -y deepspeed
"$VENV/bin/python" -c 'from transformers import Qwen2ForCausalLM; print("Transformers import OK")'
bash start.sh
```
