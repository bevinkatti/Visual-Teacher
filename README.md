# Blu Visual Teacher

Blu Visual Teacher is a local-first lesson video engine. It converts a structured lesson into narrated scenes, captions, and an MP4 using local Python components and FFmpeg.

## Gate 1 through Gate 4 status

The fixed Python-loop sample pipeline uses the existing Pydantic lesson schema, local Kokoro-ONNX narration, a reusable Pillow scene renderer, and FFmpeg. Each scene duration is measured from the synthesized WAV and extended by its configured short pause. The export is verified with FFprobe before the command reports success.

Gate 2 adds a dedicated Ollama planner using the already installed `qwen2.5:3b` model. It returns a Pydantic-validated scene plan; the server supplies trusted request metadata and marks the lesson `source: "ollama"`. Ollama failures return the deterministic sample with `source: "sample"`, `fallback: true`, and a machine-readable `fallback_reason`. Planning stays separate from Kokoro narration, audio-derived scene timing, visual rendering, and MP4 export.

The planner sends requests only to a loopback Ollama URL. The installed model's Ollama metadata reports English; planning has not been quality-validated in Hindi or Kannada. Qwen creates lesson text only; it does not generate narration audio.

Gate 3 connects the existing React/Vite form to `POST /api/lessons`, displays the returned scene data and honest Ollama/sample status, and submits render jobs to the backend. Rendering runs in a bounded background worker. The browser polls status and receives playback, MP4 download, and SRT links only after the real files exist and export validation succeeds. Files are stored under the fixed server-controlled `output/videos/lessons` directory; clients cannot choose output paths. The UI uses system fonts and a Vite `/api` development proxy. Hindi/Kannada narration is not available: the current Kokoro export voice and fallback narration are English.

Gate 4 adds reusable concept diagram, process flow, legacy code display, and structured Python-loop execution visuals. Code visuals are declarative and bounded: the renderer never evaluates model-provided code. A fixed Python loop lesson demonstrates list iteration, changing variable values, accumulated output, and loop termination. The same normalized timeline drives MP4 frames and the interactive lesson preview. A completed render manifest is served from `/api/media/{job_id}/manifest`; the preview follows scene/audio timing while the user plays the real MP4. The interface has a dark navy/blue visual system, responsive breakpoints, reduced-motion handling, and no remote font dependency.

## Setup

Use Python 3.12, Node.js, and FFmpeg/FFprobe with an H.264 encoder (libx264). Install Python dependencies from the project root:

~~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
~~~~

Gate 2 requires Ollama with the `qwen2.5:3b` model already installed. This workspace was verified with Ollama 0.40.11 and model digest `357c53fb659c` (about 1.9 GB). No other model is needed by the planner. Confirm an active local Ollama service and the model before starting FastAPI:

~~~~powershell
ollama --version
ollama list
Invoke-RestMethod http://localhost:11434/api/version
~~~~

Configure the planner (all settings are optional). Ollama URLs must resolve to loopback (`localhost` or a loopback IP); remote endpoints are rejected. The timeout is per generation request.

~~~~powershell
$env:BLU_OLLAMA_URL = 'http://localhost:11434'
$env:BLU_OLLAMA_MODEL = 'qwen2.5:3b'
$env:BLU_OLLAMA_TIMEOUT_SECONDS = '120'
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
~~~~

`POST /api/lessons` keeps the existing top-level `Lesson` response and adds `fallback` and `fallback_reason`. A successful plan reports `source: "ollama"` and `fallback: false`; a deterministic sample fallback reports `source: "sample"`, `fallback: true`, and one of `unavailable`, `timeout`, `http_error`, or `invalid_output`. The fallback preserves the requested language field, but its existing fixed sample narration is English. Request validation still returns FastAPI's 422 response. `/api/health` reports planner configuration and fallback availability; it does not probe Ollama on every health request.

Download the two Kokoro-ONNX files into a new models\kokoro-onnx directory. Do not overwrite existing files.

~~~~powershell
New-Item -ItemType Directory -Force models\kokoro-onnx
if (Test-Path models\kokoro-onnx\kokoro-v1.0.int8.onnx) { throw 'Model already exists; keep it.' }
if (Test-Path models\kokoro-onnx\voices-v1.0.bin) { throw 'Voice pack already exists; keep it.' }
Invoke-WebRequest 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.int8.onnx' -OutFile models\kokoro-onnx\kokoro-v1.0.int8.onnx
Invoke-WebRequest 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin' -OutFile models\kokoro-onnx\voices-v1.0.bin
~~~~

Generate the sample MP4, SRT captions, and JSON timing manifest:

~~~~powershell
.\.venv\Scripts\python.exe -m backend.render_sample
~~~~

The command writes output\videos\python-loop-sample.mp4, .srt, and .json. It refuses to replace any existing output. Start the backend and frontend in separate PowerShell windows:

~~~~powershell
# Window 1: backend API (Ollama should already be running locally)
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload

# Window 2: React/Vite UI; /api requests proxy to 127.0.0.1:8000
npm.cmd run dev
~~~~

Create a lesson in the UI to receive a top-level `Lesson` response. If Ollama planning fails, the API returns the deterministic sample with `source: "sample"`, `fallback: true`, and a reason; the UI labels this explicitly. Select **Render narrated MP4** to queue local narration/export. `POST /api/lessons/{lesson_id}/render` returns a job, and the UI polls `GET /api/renders/{job_id}`. Only a completed job exposes `GET /api/media/{job_id}/video`, `/download`, `/captions`, and `/manifest`. Render jobs live in memory and are lost if the backend process restarts; start again after a restart. `output/videos/lessons` is the fixed media destination.

Run the backend tests with:

~~~~powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
~~~~

Unit tests mock Ollama and need no running model. To opt in to a real local check, or a three-topic latency benchmark, use:

~~~~powershell
.\.venv\Scripts\python.exe -m backend.check_ollama
.\.venv\Scripts\python.exe -m backend.check_ollama --benchmark
~~~~

The benchmark measures wall-clock time through local inference and Pydantic validation. It never unloads the Ollama model. Results depend on whether the model is already resident.

The Gate 3 browser integration tests mock API responses. To run the full local-model-to-render-to-HTTP-media check (uses the installed Ollama model and synthesizes a real narrated MP4), set the opt-in flag. It may take several minutes on CPU and creates a new file under `output/videos/lessons`:

~~~~powershell
$env:BLU_RUN_LOCAL_MEDIA_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest backend\tests\test_gate3_local_integration.py -q -s
Remove-Item Env:BLU_RUN_LOCAL_MEDIA_INTEGRATION
~~~~

Frontend checks:

~~~~powershell
npm.cmd test
npm.cmd run lint
npm.cmd run build
~~~~

The frontend unit suite covers API validation and retry states, honest sample fallback messaging, render failure/completion, manifest-based playback synchronization, Unicode, video next-scene/replay controls, and visual timeline states. The preserved fixed-sample regression is `output/videos/gate4-premium-regression-retry.mp4`; its paired SRT and JSON timing manifest use the same base name. FFprobe verified H.264/AAC, 1280×720, 24 fps. `output/inspection` contains sampled exported frames used for visual review. The player uses native play/pause controls plus manifest-timed Next scene and Replay scene actions.

## Local models, voices, and licences

| Component | Use | Licence / notes |
|---|---|---|
| Ollama `qwen2.5:3b` | Local lesson text planner | About 1.9 GB in this installation. The 3B variant is under the [Qwen Research License](https://ollama.com/library/qwen2.5); it is not Apache-2.0. This workspace uses the Ollama-managed model and does not redistribute it. |
| Kokoro-ONNX 0.6.1 | CPU inference adapter | MIT; Python 3.10–3.13 supported. |
| kokoro-v1.0.int8.onnx | 82M-parameter Kokoro weights | Apache-2.0; upstream release asset is about 114 MB. |
| voices-v1.0.bin | Voice style vectors | About 28 MB, 54 voices. The upstream voice table lists `hf_alpha`, `hf_beta`, `hm_omega`, and `hm_psi` as Hindi voices and warns that non-English quality may be weak. Hindi export uses `hf_alpha`; no Indian-English voice is listed. Preserve upstream notices and check the pack before redistribution. |
| phonemizer and eSpeak NG support | Local text-to-phoneme conversion | GPL-3-or-later components; include the corresponding notices if distributing the runtime. |
| ONNX Runtime | CPU model execution | MIT. |
| Pillow and SoundFile | Scene and PCM/WAV generation | Pillow HPND; SoundFile BSD-3-Clause. |
| FFmpeg | H.264/AAC muxing | Uses the locally installed FFmpeg build. This build includes GPL-enabled libx264; it is not bundled by this repository. |
| Segoe UI and Consolas, Nirmala UI, Tunga | English/code, Devanagari, Kannada text | Read from the local Windows font installation; font files are not redistributed. |

The model weights and voice pack are kept under the ignored models directory and are not included in the source backup or source code. The requirements file pins the tested Python runtime packages.

The planner uses Ollama's JSON Schema `format` support, verified against the installed Ollama 0.40.11 API. Its response schema is derived from the Pydantic `Scene`/`LessonPlan` contract; request metadata, IDs, source, and fallback fields are set by the backend and validated as a complete `Lesson`. User topics are passed as JSON data and explicitly treated as untrusted subject text. Structured validation enforces allowed fields, 3–6 scenes, text bounds, visual types, and bounded `visual_data`. Lesson correctness still requires human review.

## Tested hardware and current limits

The current machine reports an AMD Ryzen 7 7840HS, 16 logical CPUs, 15.29 GiB RAM, and 112.2 GiB free disk. The sample pipeline uses ONNX Runtime's CPU package; no GPU execution is required. In the fixed Python-loop sample run, Kokoro synthesized 34.76 seconds of speech in 85.48 seconds (2.46x slower than real time); a separate 6.70-second speech benchmark took 19.65 seconds. The full 35.79-second MP4 took 120.97 seconds end to end: 21.82 seconds for scene rendering and 12.91 seconds for FFmpeg encoding. FFprobe confirmed 1280x720 H.264 video at 24 fps and mono 24 kHz AAC audio. This is practical for an offline pre-rendered sample on this machine, not real-time narration. These timings are one run, not a performance guarantee.

With the Ollama model resident, the three English beginner topics produced valid three-scene plans without fallback:

| Topic | Call | Generation time |
|---|---:|---:|
| How do fractions show parts of a whole? | First benchmark call | 5.424 s |
| Why does the Moon appear to change shape? | Subsequent call | 5.366 s |
| How does a Python for loop repeat a command? | Subsequent call | 8.463 s |

All three outputs validated; the first two contained three scenes and the third contained six. These are single-run measurements, not cold-start timings or a speed guarantee. The model was not unloaded to force a cold start because the already-running Ollama service was left intact.

Historical Gate 3 and Gate 4 details above/below reflect their original verification dates. The current Phase 3/4 status and fresh artifact checks are in the following update and `docs/requirements-reconciliation.md`.

## Troubleshooting

- **Fallback with `unavailable`:** check `ollama list` and `http://localhost:11434/api/version`; make sure the existing Ollama service is running. Do not start a second `ollama serve` if it is already active.
- **Fallback with `http_error`:** check that `BLU_OLLAMA_MODEL` exactly matches an installed model tag. The planner does not pull models automatically.
- **Fallback with `timeout`:** increase `BLU_OLLAMA_TIMEOUT_SECONDS`; slow CPU inference may need more time.
- **Fallback with `invalid_output`:** inspect the backend warning and run `python -m backend.check_ollama`. The planner rejects malformed or schema-invalid JSON and keeps the sample source/status explicit.
- **Model output is wrong for a topic:** review the lesson before narration/export. Pydantic validates structure and bounds, not factual correctness.

## Phase 3 / Phase 4 voice verification update

The generated-video player has native play/pause plus **Next scene** and **Replay scene** actions that seek using the measured export manifest. These controls are covered by frontend tests; actual browser/device playback and mobile overflow remain unverified in this environment.

Hindi narration uses the existing local Kokoro `hf_alpha` voice with `language="hi"`. The backend requires Devanagari lesson titles, narration, and captions before it queues Hindi export; the Hindi deterministic sample fallback is written in Devanagari. The local Windows Nirmala font is selected for Devanagari captions and scene labels and is not redistributed. English keeps its existing local Kokoro route, but an Indian accent is not independently verified. Kannada export returns HTTP 422 until a licensed local Kannada voice is selected and installed. The frontend names this limitation.

Kokoro’s upstream [voice inventory](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md) lists `hf_alpha`, `hf_beta`, `hm_omega`, and `hm_psi` as Hindi voices and notes limited non-English training data. It does not list an Indian-English voice. The [Kokoro model](https://huggingface.co/hexgrad/Kokoro-82M) is Apache-2.0; the [`kokoro-onnx` adapter](https://github.com/thewh1teagle/kokoro-onnx) is MIT; verify the voice pack notices separately before redistribution. A Kannada [`facebook/mms-tts-kan`](https://huggingface.co/facebook/mms-tts-kan) candidate is CC-BY-NC 4.0; its [ONNX community int8 conversion](https://huggingface.co/onnx-community/mms-tts-kan-ONNX/tree/main/onnx) is 37.7 MB, but the conversion card has no separate license statement. Because the upstream restriction is non-commercial, it was not added to this product. No additional models or packages were downloaded.

The render-job path now passes the selected Kokoro voice and language explicitly. Narration timing is measured from WAV audio before scene boundaries are built. Timing instrumentation uses `time.monotonic()` for TTS initialization and synthesis, rendering, encoding, FFprobe verification, and export total. The old 1513-second narration figure remains anomalous; do not use it as a performance result. See the phase verification record in `docs/requirements-reconciliation.md` for measured outputs and remaining limits.

Verified fixed samples from this phase: `output/videos/phase4-english-final.mp4` (33.677292 s) and `output/videos/phase4-hindi-final.mp4` (38.818667 s). The Hindi sample is a deterministic sample fallback, not a Qwen-generated translation. In the Hindi MP4, FFprobe reports 38.818667 s AAC and 38.791667 s video (less than one 24 fps frame difference); the full AAC duration matches the measured narration-plus-pause timeline. A captured frame at `output/inspection/phase4-hindi-caption.png` visually confirms Devanagari caption glyphs. Local TTS/export performance for one run: English synthesis 51.796 s and export stage total 71.234 s (TTS initialization 1.391 s); Hindi synthesis 62.719 s and export stage total 84.985 s (initialization 1.468 s). The export total begins after narrator initialization. These single-run CPU measurements are not a guarantee. Human listening review for intelligibility and accent remains outstanding.

One real local Hindi planning request exceeded the configured 120 s Ollama timeout and returned the explicit Hindi sample fallback. Hindi planner reliability is not established by the fixed-sample TTS export.
