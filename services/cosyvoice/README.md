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
  speed = 1.0
} | ConvertTo-Json

Invoke-WebRequest http://127.0.0.1:50000/v1/tts `
  -Method Post -ContentType "application/json" -Body $body -OutFile sample.wav
```

The first generation loads the model and is slower than later requests.

BrandMate defaults to `COSYVOICE_INFERENCE_MODE=cross_lingual`. This sends only
the narration script after CosyVoice's system marker, preventing acting
instructions from leaking into generated speech. Long narration is split at
sentence boundaries and generated in order to reduce omitted phrases. The
selected emotion reference recording and speed control still affect the result.
The `woman_whisper` preset uses a short, fixed model-native whisper instruction
because cross-lingual speaker embeddings alone do not reliably preserve
whispered articulation. The male whisper recordings are excluded because they
produce an unreliable hoarse delivery. Custom web instructions are not sent in
this mode.

The experimental `instruct` mode can be enabled explicitly, but may speak parts
of the instruction:

```bash
COSYVOICE_INFERENCE_MODE=instruct bash start.sh
```

## Voice benchmark automation

The Windows-side benchmark script resumes from `voice test.csv`, generates the
next planned case, measures WAV duration from its frame count, records request
latency, and saves the audio under `test voices`.

Preview the next test without generating audio:

```powershell
.\apps\api\.venv\Scripts\python.exe .\scripts\run_cosyvoice_test.py --dry-run
```

Generate and record the next test:

```powershell
.\apps\api\.venv\Scripts\python.exe .\scripts\run_cosyvoice_test.py
```

Use `--count 3` for the next three cases or `--all` for every remaining case.
The defaults are:

```text
CSV:       ../voice test.csv
WAV files: ../test voices/
```

Close the CSV in Excel before running the script. The script checks that the
CSV is writable before starting generation and removes a newly generated WAV
if appending its measurement fails.

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
