# Official hackathon requirements and audit reconciliation

Source: [official Blu Visual Teacher problem statement](official-problem-statement.pdf), six pages, dated October 28, 2026. Extracted from the supplied PDF with pypdf. The source is a product/competition requirements document; the user's request determines the work performed in this workspace.

## Core product requirements

| Area | Official requirement | Baseline audit |
|---|---|---|
| Offline operation | No external AI APIs or cloud voices. Run models locally on CPU-only laptops with 8–16 GB RAM. After packages and models are downloaded, run the complete pipeline with Wi-Fi off. | FastAPI and React exist, but there is no local model pipeline; the UI fetches Google Fonts remotely. |
| Student device | Lesson playback should be smooth in a browser on a modest phone. | No player exists to assess. |
| Input | Send topic, beginner/intermediate level, language, and 30–90 second target length to the backend. | Form fields exist; the create action does not call the API. |
| Planner | Local LLM returns JSON for 3–6 scenes containing a title, scene type, on-screen content, and narration. Validate against a schema; invalid output falls back to a built-in sample. Never run model-generated code. | Pydantic validation and a sample endpoint exist; no LLM integration. Current sample schema differs in naming from the example, which is explicitly a starting point. |
| Visual engine | Reusable title card, labelled diagram with arrows, and code walkthrough. Use the app's own components to animate/explain relationships. | Static concept, flow, and code examples are present. They are not rendered from generated scene data. |
| Narration and captions | English with an Indian accent plus at least two Indian languages, all locally generated. Captions use the correct script. Audio, captions, and visuals remain synchronized. Preserve code, numbers, and useful English technical terms. | English sample text only; no TTS, translation, script verification, or synchronization. |
| Browser player | Play, pause, next scene, and replay must work. The reference video also shows step headings, a caption bar, and progress bar. | Scene tabs switch a static preview; playback controls do not exist. |
| MP4 | Downloadable 1280×720 MP4, H.264 video, AAC audio, with captions burned in or supplied as SRT. | FFmpeg/FFprobe are available; there is no export pipeline. |
| Timing | Generate narration audio first. Scene duration equals measured audio duration plus a short pause; do not put scene durations in the LLM plan. | No audio or measured timeline exists. |
| Licences | Check model, code, voice, and asset licences separately; list them in README. | No model or voice inventory. |
| Fallback | Wi-Fi-off live demo. If a model call fails, the fallback lesson still plays. | Sample API exists; it is not yet connected to playback/export. |

## Exact demo and submission wording

- The kickoff/reference video is a **29-second sample lesson on Python loops**, with step headings, a caption bar, and a progress bar. It is a reference, not a fixed judge-assigned topic.
- Submit **two generated MP4 lessons** by the end of hour 24: one on a topic judges give on the day and one on a topic of the team's choice. The statement says each must be “in English and in one Indian language.” It does not say which Indian language; this wording may mean two language versions per topic, so confirm with organizers if the deliverable count matters.
- Give a **5-minute live demo**: enter a new topic and a language called out by judges, generate the lesson live, and play it; then allow **3 minutes for questions**. Wi-Fi is off, and a model failure must fall back to a playable sample.
- The repository README must cover setup, models and voices with licences, and the laptop specifications used for testing.
- The event rule says all code must be written during the 24-hour event. Pre-trained model and package downloads may happen before the event; training a foundation model is out of scope. The user confirmed the permitted coding window is open.

## Model guidance in the official statement

- One small local instruction model, around 3B parameters for an 8–16 GB laptop, with Ollama suggested.
- Kokoro (`kokoro-onnx`) is suggested for CPU speech, specifically Indian-accented English and Hindi; the statement names `hm_omega`, `hm_psi`, `hf_alpha`, and `hf_beta`.
- For additional Indian languages, the statement suggests trying open Indic voice models such as Indic Parler-TTS and benchmarking speed on the target laptop.
- IndicTrans2 is suggested as a local translator. Keep code, numbers, and technical terms understandable.
- Noto Sans fonts for each supported script, Node.js, Python, FFmpeg, and Playwright are suggested setup items.

## Scoring priorities

| Criterion | Weight |
|---|---:|
| Works end to end, live and offline | 25% |
| Teaching quality and progression | 20% |
| Visual clarity | 15% |
| Language quality, narration, and sync | 15% |
| Engineering and robustness | 15% |
| Speed and footprint | 10% |

Bonus features count only after all five core stages work. The PDF lists more languages, voice choice/speed, extra visual types, editing before render, caching, and stage-speed reporting as bonus ideas.

## Gate 1 reconciliation

Gate 1 implements the highest-priority first gate from the statement: a fixed Python-loop sample passing through validation, local narration, measured scene timing, visual rendering, and export. It does not claim the full product is complete: multilingual translation, interactive browser playback, local LLM generation, Wi-Fi-off end-to-end workflow, phone performance, and the two final demo-topic lessons remain later acceptance work.

## Gate 2 reconciliation

Gate 2 adds a loopback-only Ollama planner for the installed `qwen2.5:3b` model. Ollama's JSON Schema output is validated against the Pydantic scene plan and then composed into a complete validated `Lesson`. The backend owns request metadata and accurately exposes `source`, `fallback`, and `fallback_reason`; model errors do not masquerade as successful LLM plans. Failures return the existing deterministic sample content while preserving the requested topic, level, language, and target duration in the response metadata.

This meets the local planner and structured fallback portions of the official brief. Only English planning has been measured in this gate. Hindi/Kannada lesson quality, translation, local narration in those languages, and the existing UI's connection to this API are not validated or implemented. Qwen generates lesson text only; Kokoro remains the separate English narration component. The sample fallback preserves the requested language metadata but its fixed sample narration is English. The generated scenes are structurally checked, but factual/teaching quality still needs human review.

## Gate 2 baseline and verification

Before edits, the existing suite passed **11 tests** (with a warning that pytest could not write its existing cache directory). The unchanged sample exporter completed successfully to `output/videos/gate2-prechange-baseline.mp4`: 35.74 seconds, H.264/AAC, 1280×720 at 24 fps. Its measured wall times were 61.46 seconds narration, 18.22 seconds frame rendering, and 6.72 seconds encoding. The original `python-loop-sample.mp4` was not overwritten.

The local API reported Ollama 0.40.11 and `qwen2.5:3b`, digest `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`, size 1,929,912,432 bytes. JSON Schema structured output was accepted by that installed API. After Gate 2, **24 unit tests passed**; `compileall` passed; direct planner and API checks returned valid lessons; an intentionally closed loopback port returned the sample fallback with `fallback: true`; and three resident-model English benchmark calls took 5.424, 5.366, and 8.463 seconds without fallback. They returned three, three, and six scenes, respectively. The post-change sample export is `output/videos/gate2-postchange-regression.mp4`; FFprobe confirmed 35.791667 seconds, H.264/AAC, 1280×720, 24 fps, with 35.754667 seconds of AAC audio. A sampled frame showed the burned-in caption remains visible, and the manifest retains the measured per-scene speech durations and pauses.

## Gate 3 reconciliation

The existing React/Vite design now submits its actual topic, level, language, and duration controls to `POST /api/lessons`. It validates the response shape in the browser and displays API-provided scene titles, narration, captions, visual data, count, and `ollama`/`sample`/fallback status. Browser and backend validation failures are visible with retry actions; duplicate lesson submissions are blocked. The UI continues to mark Hindi/Kannada planning as unverified and English narration as the only available audio language.

Rendering is a separate `POST /api/lessons/{lesson_id}/render` background job. Status is available from `GET /api/renders/{job_id}`. Job IDs and output names are server generated; a fixed `output/videos/lessons` destination is used, with one renderer worker and a bounded active queue. The backend exposes controlled video playback, MP4 download, and SRT download routes only after the actual output files pass the existing FFprobe validation. Failure states carry no media links. The job registry is in memory: restarting the backend drops job state and the browser must submit again. The MP4/SRT/manifest files remain in the fixed output folder.

The Vite development server proxies same-origin `/api` requests to `127.0.0.1:8000`; FastAPI's existing explicit local CORS allowlist remains unchanged. No external runtime APIs are added. The Google Fonts import has been removed in favor of system-font stacks. Frontend tests mock API payloads; a separate opt-in backend integration check performs a real local Ollama request, synthesis, FFmpeg export, FFprobe validation, and media-route fetch.

Gate 3 verifies a functional browser-to-API preview and actual video playback/download, but it does not complete the entire official brief. The built-in browser video controls support play/pause; there are no generated-media next-scene/replay controls or custom progress bar, and scene navigation in the lesson preview is not synchronized to the MP4 timeline. Narration remains English. No offline Wi-Fi acceptance run, phone-performance test, or submission-ready bilingual pair of final demo lessons is claimed.

## Gate 3 verification record

Before Gate 3 edits, backend tests passed **24/24**. Frontend lint passed when targeted at `src`; the baseline package lint script failed because ESLint also traversed the protected pytest cache directory, so its scope was narrowed to the application source. The production build passed when directed to a new output directory; the existing `dist` directory was left untouched. A verified source backup was made at `backups/pre-gate3-20261027` before editing, and each copied file's SHA-256 matched its source.

After integration, the frontend suite passes **10/10**, frontend lint passes, the default backend suite reports **28 passed, 1 opt-in integration test skipped**, and Python compile checks pass. The production TypeScript/Vite build succeeds. The opt-in test `backend/tests/test_gate3_local_integration.py` also passed separately against the actual local model/API/render/media path. The canonical `python-loop-sample.mp4` was not overwritten; the same fixed sample was rendered into a new regression filename and FFprobe-verified.

The real local integration test passed in **110.85 seconds**. `POST /api/lessons` returned `source: "ollama"`, `fallback: false`, and four scenes for “How do plants move water from roots to leaves?” The renderer produced `output/videos/lessons/lesson-8cb02206798c-9a60e2f92b524e69aee3cbd49fde0eb6.mp4`; FFprobe measured **29.958333 seconds** container/video duration and **29.952000 seconds** AAC duration, with **H.264/AAC**, **1280×720**, **24/1 fps**. The manifest records measured scene narration durations of **7.424667, 6.368000, 6.313958, and 8.467250 seconds**, each followed by its configured pause. Video playback returned the MP4 bytes, the download route returned the same bytes as an attachment, and the SRT route returned 352 bytes.

The fixed Python-loop regression export to `output/videos/gate3-sample-regression.mp4` passed in **111.09 seconds**. FFprobe measured **35.833333 seconds** container/video duration and **35.797333 seconds** AAC duration, with H.264/AAC, 1280×720 at 24 fps. Per-scene narration audio measured **10.580667, 12.546667, and 11.662667 seconds**. Its stage timings were **77.30 seconds narration**, **20.82 seconds rendering**, and **12.82 seconds encoding**. These are single-run CPU measurements, not performance guarantees. The original sample MP4/SRT/manifest remain untouched.

## Gate 4 — premium visual teaching engine

Before editing, the current frontend, schemas, renderer, export service, render jobs, API routes, tests, README, and this reconciliation were inspected. No Git metadata exists. A SHA-256 verified pre-edit copy is at `backups/pre-blu-premium-20261027-182201`; each of its 17 files matched the source. One file was missed in that backup: `backend/services/narration_service.py` was edited to instrument Kokoro initialization/synthesis and is not included in the pre-edit snapshot. Its exact original could not be verified from the available prior backups. This is a backup coverage gap. Baseline backend tests were **28 passed, 1 skipped**; frontend tests **10 passed**; lint and production build passed. The fixed sample baseline is `output/videos/gate4-prechange-baseline.mp4`: **35.82 s**, H.264/AAC, 1280×720 at 24 fps. Its measured stages were TTS/narration **77.624 s**, scene rendering **21.084 s**, encoding **11.174 s**, and total **110.068 s**. Existing approved outputs were left intact.

The schema now supports `concept_diagram`, `process_flow`, and bounded `code_execution` visuals while retaining legacy types. Structured execution data permits an identifier, printable iterable label, and 2–6 bounded values only; no Python is evaluated. `backend/services/visual_registry.py` generates deterministic normalized keyframes for the ready state, each iteration, incremental output, and termination. The Pillow frame renderer and React visual registry render typed concept, process, and code views. The sample loop lesson now has three progressive scenes that teach per-item execution and termination. The browser uses the completed render manifest to synchronize the active scene and visual progress with the actual MP4 playback time. `/api/media/{job_id}/manifest` serves the server-selected manifest without accepting filesystem paths from the client.

The first post-change render attempt exposed a manifest timeline scope bug after writing an MP4 and SRT but before writing JSON. Those partial files remain preserved as `output/videos/gate4-premium-regression.mp4` and `.srt`; no manifest was produced. The exporter was corrected to construct each timeline once and share it between frame rendering and manifest serialization. The clean retry is `output/videos/gate4-premium-regression-retry.mp4`, with paired `.srt` and `.json` files. Export measurements: **33.666667 s video/container**, **33.664 s AAC**, **H.264/AAC**, **1280×720**, **24/1 fps**. The manifest records measured speech durations of **7.218667, 15.126625, and 10.272000 s**, plus **0.35 s** pause per scene. The exporter reported `tts_initialization` 1.879 s, `narration` 1513.408 s, `scene_render` 17.095 s, `encode` 10.123 s, and `total` 1540.813 s. The narration/total timers are inconsistent with the roughly 2–3 minute command session, so those two readings are anomalous and are not used for any speed claim. Three frame captures (`output/inspection/gate4-loop-mid-a.png`, `gate4-loop-mid-b.png`, and `gate4-loop-end.png`) visually confirmed active-line/iteration changes, accumulated printed values, and the terminal concept diagram.

Gate 4 verification: backend tests **32 passed, 1 skipped**; frontend tests **12 passed**; ESLint passed without warnings; TypeScript/Vite production build passed; Python compile checks passed. The source has no remote Google Fonts import. A desktop/mobile headless browser screenshot run was attempted with installed Edge/Chrome, but the managed browser launch forwarded to the already-running browser session and produced no screenshots; Codex exposed no attachable browser surfaces. Therefore actual visual browser QA and measured phone overflow remain unverified. The responsive CSS and reduced-motion behavior are implemented, but they are not claimed as device-tested. Remaining official requirements from Gate 3 remain: Hindi/Kannada narration, generated-video next-scene/replay controls, phone performance, Wi-Fi-off acceptance, and two final bilingual deliverables.

## Phase 3 verification and Phase 4 voice/export update — 2026-10-27

This update supersedes only the current-status statements above. The Gate 4 historical records and artifacts remain unchanged.

### Phase 3 acceptance matrix

| Requirement | Status | Evidence |
|---|---|---|
| Three reusable scene types | PASS (source/test evidence) | `concept_diagram`, `process_flow`, and `code_execution` are dispatched by the shared Python renderer and React canvas; existing visual registry and canvas tests cover these paths. |
| Browser play/pause, next, replay | NOT VERIFIED in an actual browser | Native video controls provide play/pause. Manifest-based Next scene and Replay scene actions have been added and unit-tested, but this environment did not expose a usable browser for playback verification. |
| Keyboard focus/interaction | NOT VERIFIED in an actual browser | Source uses native buttons/video controls and visible focus styles. No real browser keyboard audit was possible. |
| Python-loop teaching progression | PASS (source and rendered frame evidence) | The lesson shows current iteration, changing values, cumulative output, and terminal state; existing captured frames and visual registry tests cover these states. |
| Preview/export timeline compatibility | PASS (manifest path) | The React preview reads the same exported manifest timeline used to render frames; Next/Replay seek by manifest boundaries. |
| Desktop/mobile clipping and controls | NOT VERIFIED | Responsive CSS exists, but no screenshot/browser surface or device test was available in this run. |
| Console errors, local media requests, playback | NOT VERIFIED in an actual browser | API/media tests pass, but no browser session was available for console and real playback review. |

### Phase 4 implementation and limits

Render jobs now pass local Kokoro voice/language settings explicitly. English retains the existing Kokoro path. Hindi uses the already installed `hf_alpha` voice with `hi` G2P; a Devanagari sample fallback and a local Windows Nirmala font were used at that phase. The follow-up below replaces that OS font with bundled Noto Sans assets. Hindi rendering is rejected unless title, narration, and captions contain Hindi-script content. Kannada rendering returns HTTP 422 because no Kannada voice is installed. No silent English speech substitution is performed. The current code does not add translation of arbitrary planner output or independently verify Indian-accented English.

The upstream Kokoro inventory identifies `hf_alpha`, `hf_beta`, `hm_omega`, and `hm_psi` as Hindi voices and warns that non-English quality may be weak; it lists no Indian-English voice. Kokoro model weights are Apache-2.0; the `kokoro-onnx` adapter is MIT; the precise voice-pack notices must be preserved/checked before redistribution. A Kannada-only `facebook/mms-tts-kan` candidate is CC-BY-NC 4.0. Its ONNX-community int8 conversion is listed at 37.7 MB, but that conversion card does not separately state a license. It was not downloaded or included because the inherited non-commercial restriction is not an appropriate unreviewed product dependency. The current application therefore meets neither the two Indian-language requirement nor the verified Indian-accent English requirement.

All TTS and export stage clocks now use `time.monotonic()`. Audio remains synthesized before scene boundaries; each scene duration is read from its WAV file and followed by the validated pause. Prior timing instrumentation reported 1513.408 seconds for a run that took roughly 2–3 minutes. That result remains marked anomalous. No post-change language export measurements are recorded here until a new actual Hindi render completes. Existing English artifact `output/videos/gate4-premium-regression-retry.mp4` was re-probed before changes: 33.666667 s container/video, 33.664 s audio, H.264/AAC, 1280×720, 24/1 fps. It was preserved.

### Pre-edit backup and baseline

No `.git` metadata exists. Before edits, 13 intended-to-change files were copied to `backups/pre-phase3-phase4-20261027-202456`; `SHA256SUMS.txt` records a verified SHA-256 match for every copied source file. This includes `backend/services/narration_service.py`, which had been omitted from the older Gate 4 backup. The existing successful MP4/SRT/manifest were not modified.

Baseline before source edits: backend **32 passed, 1 skipped** (`.venv` Python, targeted to `backend/tests`); frontend **12 passed**, ESLint passed, and Vite/TypeScript production build passed after retrying with Windows process access. `python -m compileall -q backend` passed. FFprobe confirmed the preserved English baseline metadata above. A root-wide pytest attempt failed because pytest recursively collected backup copies and protected `output/pytest-tmp`; it was narrowed to the project test directory.

Post-edit checks: backend **37 passed, 1 skipped**; frontend **12 passed**; ESLint passed; Vite/TypeScript production build passed; Python compile checks passed. The standard pytest cache warning remains because the sandbox denies writes to `.pytest_cache`. Frontend tests simulate video time and play calls; they do not count as actual-browser acceptance.

The final Hindi fixed sample is `output/videos/phase4-hindi-final.mp4`, with paired `.srt` and `.json`. It is the deterministic sample fallback, not an Ollama translation. `hf_alpha` with `hi` G2P synthesized scene audio in **62.719 s**; model initialization took **1.468 s**, rendering **15.141 s**, encoding **6.984 s**, FFprobe verification **0.047 s**, and the exporter total after initialization **84.984 s**. Actual measured narration was **7.786667, 18.270000, and 11.712000 s**, plus the configured **0.35 s** scene pauses. FFprobe reports format/AAC **38.818667 s**, H.264 video **38.791667 s**, **1280×720**, **24/1 fps**. The audio/video difference is **0.027 s**, less than one frame; AAC retains the full measured audio timeline. The SRT is 519 bytes and contains Devanagari text. `output/inspection/phase4-hindi-caption.png` was extracted from the real MP4 and visually inspected; the Nirmala Devanagari glyphs render legibly. The assistant could not perform a human listening review, so pronunciation/intelligibility is still NOT VERIFIED.

The fresh English regression is `output/videos/phase4-english-final.mp4`, with paired `.srt` and `.json`. Kokoro initialization measured **1.391 s**, synthesis **51.796 s**, scene rendering **13.360 s**, encoding **5.984 s**, FFprobe verification **0.031 s**, and exporter total after initialization **71.234 s**. Measured audio durations are **7.218667, 15.116625, and 10.292000 s**. FFprobe reports format/AAC **33.677292 s**, H.264 video **33.666667 s**, **1280×720**, **24/1 fps**. The existing `output/videos/gate4-premium-regression-retry.mp4` remains unchanged.

The first Hindi attempt is preserved at `output/videos/phase4-hindi-fixed-sample.mp4`; it exposed a frame/audio boundary issue. The first retry is also preserved at `output/videos/phase4-hindi-fixed-sample-retry.mp4`. Frame count was changed to include one extra frame after the measured timeline so AAC samples are not cut by FFmpeg `-shortest`; the final AAC duration now matches the audio timeline. The final video stream duration may still be shorter by less than one frame because video is frame-quantized. This is not treated as zero-duration timing error; it is reported explicitly.

Offline Wi-Fi acceptance, actual browser/device QA, arbitrary-topic Hindi translation quality, Kannada narration, and Indian-accent English remain incomplete. No extra model/package was downloaded and no external runtime API was added. The single highest-priority next action is to select a redistribution-compatible Kannada TTS model and verify its actual Windows CPU output and license before integration. Human review of the Hindi output is also required before describing it as intelligible classroom narration.

A real local API request for a Hindi Python-loop lesson hit the configured Ollama timeout after **120 s**. The API returned HTTP 200 with `source: "sample"`, `fallback: true`, `fallback_reason: "timeout"`, and three Devanagari scenes; the render-language script check accepted that lesson. This verifies the honest fallback path, not reliable Hindi planning. No further Ollama calls were made in this phase.

## Portability and Kannada fallback follow-up — 2026-10-27

The renderer no longer uses Windows-only font paths. Seven official Noto Sans fonts are bundled under `backend/assets/fonts`: Latin and Mono, variable Devanagari and Kannada, a Devanagari UI variable font, and Kannada UI regular/semibold fonts, totaling **6,054,712 bytes**. Three SIL Open Font License 1.1 notices are bundled. The Indic UI fonts have incomplete Latin glyph coverage, so mixed captions render Latin runs with the bundled Latin font and Indic runs with their matching script font. [Noto Devanagari project](https://github.com/notofonts/devanagari), [Noto Kannada project](https://github.com/notofonts/kannada), [Noto Sans Mono metadata](https://github.com/google/fonts/blob/main/ofl/notosansmono/METADATA.pb).

`build_sample_lesson` now returns Kannada-script sample scenes for the fixed Python-loop topic and a generic Kannada template for other topics. This corrects the earlier English-text fallback. It does **not** create Kannada audio: `RenderJobManager` still returns HTTP 422 for every Kannada export because no licensed local voice is installed. No silence or English audio is substituted. The earlier wording that Kannada had no sample lesson is superseded; Kannada narration remains a critical Stage 4 gap.

The review said Kannada would silently fall through to English narration. In the current implementation that is not the case: Kannada requests receive a `RenderLanguageUnsupported` response before a render job is queued. The fallback lesson is in Kannada script for preview, while export remains explicitly unavailable.

Initial visual review found tofu boxes where a Hindi caption included the Latin token `fruit`. The renderer now splits mixed Devanagari/Kannada captions into script runs and uses the bundled Latin font for ASCII runs. A focused raster regression test checks the mixed-script output against those font runs. A fresh Hindi frame at `output/inspection/phase4-hindi-noto-mixed-caption.png` was visually inspected: Devanagari and the Latin word `fruit` render legibly.

At the time of the initial portability follow-up, the fresh Hindi MP4 could not be verified inside the restricted shell. Later checks outside the sandbox found the installed WinGet FFmpeg/FFprobe 9.0.1 target, so no installation was needed. The final updated Hindi MP4 and title-card addition are recorded in the completion audit below. Historical outputs listed above were left unchanged.

## Full completion audit — 2026-10-27

### Baseline and preservation

The repository is on branch `main` tracking `origin/main`. Before the title-card work, the working tree already had user changes to `README.md`, `backend/services/lesson_service.py`, `backend/services/scene_renderer.py`, `backend/tests/test_lesson_pipeline.py`, `docs/requirements-reconciliation.md`, plus untracked `backend/assets/fonts` assets. These were inspected and preserved. Git diff checks reported no whitespace errors; Git printed LF-to-CRLF warnings for existing modified files. Verified pre-edit source snapshots are `backups/pre-completion-edits-20261027-222301` and `backups/pre-title-card-20261027-223253`; both contain SHA-256 manifests.

At the starting baseline: backend tests **39 passed, 1 skipped**; frontend tests **12 passed**; ESLint and `compileall` passed. Frontend test/build initially hit a sandbox filesystem denial; rerunning with local filesystem access succeeded. A normal `npm.cmd run build` wrote the existing `dist` directory. The final production build was directed to new `output/completion-final-build`; saved `output/gate*-dist` artifacts were left intact. No existing MP4/SRT/manifest was overwritten. FFmpeg/FFprobe 9.0.1 were present under the local WinGet package, with `libx264` and AAC support; executable access required local filesystem permission. The C: drive reported **105.45 GB free of 350.59 GB**. Current CPU/RAM could not be read through WMI in this environment.

### Acceptance gap matrix

| Requirement | Status | Current evidence and remaining work |
|---|---|---|
| Topic, level, language, target duration input | PASS | React form sends its actual controls to `POST /api/lessons`; `LessonRequest` validates topic, level, `en`/`hi`/`kn`, and 30/60/90 seconds. Frontend API tests pass. |
| Local structured lesson planner and fallback | PASS with a reliability gap | Loopback Ollama `qwen2.5:3b` is installed and API-connected. A real API request returned a validated six-scene `source: "ollama"` lesson. A three-topic benchmark returned valid plans for fractions (**14.132 s**) and Moon phases (**10.122 s**); one Python-plan attempt failed schema validation in **10.190 s**. A follow-up direct attempt also had a code-scene shape error; a subsequent API attempt succeeded with six scenes. The deterministic sample fallback remains the recovery path. Model lesson correctness still requires human review. |
| Scene engine: title card, labelled diagram, code walkthrough | PASS | Added typed `title_card` support to Pydantic, planner prompt, Python renderer, sample opener, React canvas and API response validation. Existing concept diagram and structured non-executing code walkthrough remain. Backend/frontend tests cover title-card rendering and dispatch. |
| Hindi narration and script captions | PASS for fixed sample export; quality review incomplete | Uses local Kokoro `hf_alpha` with Hindi G2P. Fresh exported sample visually confirms Devanagari and Latin `fruit` render clearly; no human pronunciation/intelligibility review was available. Arbitrary Ollama Hindi planning/translation quality is not established. |
| Kannada narration and export | BLOCKED | Preview fallback is Kannada-script, but export still fails closed with HTTP 422. No voice is installed or verified; English speech or silence is not substituted. |
| Indian-accented English | NOT VERIFIED | Existing English Kokoro output has not been judged by a listener as Indian-accented. Kokoro's upstream inventory lists American/British English, Hindi and other languages, but no Indian-English voice category. |
| Local translation | NOT IMPLEMENTED | The planner can write in its requested language; there is no explicit translation stage or technical-term-preserving translation cache. Candidate research is summarized below. |
| Audio-derived timing and MP4 | PASS for the fresh fixed Hindi lesson | Narration WAVs were measured before building the timeline; three pauses are each 0.35 s. The fresh export passes FFprobe with H.264/AAC, 1280×720, 24 fps, audio **38.768667 s**, video **38.750000 s**. Difference is 0.018667 s, under one video frame. |
| Browser playback and responsive/device QA | PARTIAL | Frontend API/video behavior is unit-tested; production build and lint pass. No actual browser playback, phone, keyboard, console, or clipping acceptance run was completed. |
| Offline operation | NOT TESTED | Ollama and TTS use local model assets and frontend has no remote font/runtime API. Wi-Fi-disabled acceptance has not been performed. |
| Restart persistence and caching | NOT IMPLEMENTED | Render job state and lesson registry are in memory, so restart loses status. No persistent lesson/audio/translation cache exists. |

### Final verification

The fresh title-card Hindi output is `output/videos/completion-hindi-title-card.mp4`, paired with `.srt` and `.json`. FFprobe reports video `h264`, **1280×720**, **24/1 fps**, duration **38.750000 s**; audio `aac`, mono **24000 Hz**, duration **38.768667 s**; container duration **38.768667 s**. The exporter measured narration as **7.786667, 18.220000, and 11.712000 s**, giving scene intervals **0–8.136667**, **8.136667–26.706667**, and **26.706667–38.768667 s** with the configured **0.35 s** pause each. Export stage measurements: TTS initialization **1.985 s**, narration **84.969 s**, frame rendering **22.485 s**, encoding **10.047 s**, FFprobe validation **0.093 s**, total **117.703 s**. The title-card frame `output/inspection/completion-title-card-frame.png` and second-scene caption frame `output/inspection/completion-hindi-caption-frame.png` were extracted from the real MP4 and visually inspected. Audio was not human-listened.

After all source changes: backend tests **43 passed, 1 skipped**; frontend tests **13 passed**; ESLint passed; `python -m compileall -q backend` passed; TypeScript/Vite production build passed to `output/completion-final-build`. Pytest reports its existing `.pytest_cache` access warning; test results are unaffected.

### Offline speech and translation candidate check

No models or packages were downloaded and no global environment was changed. The project venv does not contain PyTorch, Transformers, or torchaudio. The checked C: drive had **105.45 GB free**, but CPU/RAM could not be read here and no new CPU benchmark was run.

* [MMS Kannada TTS](https://huggingface.co/facebook/mms-tts-kan) has a 145 MB Safetensors checkpoint and explicit Kannada support, but the model card is **CC-BY-NC 4.0** and requires Transformers/PyTorch. It is not approved here as a general product dependency, has not been downloaded, and its Windows CPU latency/voice quality have not been measured.
* [Indic Parler-TTS](https://huggingface.co/ai4bharat/indic-parler-tts) lists Kannada and Indian-English support and Apache-2.0, but its 0.9B F32 model file is **3.75 GB** and gated behind access terms. It requires an additional Parler/Transformers/PyTorch stack; model access, CPU feasibility, peak memory, and pronunciation have not been verified.
* [Indic-Speak](https://huggingface.co/bodhan-ai/indic-speak) reports Kannada/Indian-English and 22 Indian languages, but is a gated **3B BF16** model under Indic Open Model License terms, with Llama 3.2, SNAC and Vocos components; the card requires Transformers 5, PyTorch and SNAC. This is a much larger unverified CPU dependency and was not downloaded.
* [IndicTrans2](https://github.com/AI4Bharat/IndicTrans2) supports English, Hindi, Kannada and 22 scheduled Indian languages; checkpoints are MIT-licensed. Its distilled English-to-Indic 200M and Indic-to-Indic 320M cards are F32 and gated, and their inference examples recommend GPU/Flash Attention for speed. Required Transformers, PyTorch and IndicTransToolkit dependencies are absent. No translation model was downloaded or CPU-benchmarked.

None of these candidates is integrated. Kannada remains unavailable until model access, license suitability, project-local installation, CPU performance and human speech quality are verified. Translation remains absent until an offline, resource-tested model and a safe code/number-preserving integration are selected.

## Stage 4 closed — Kannada narration and local translation verified (2026-10-28)

The previously missing pieces above are now integrated, license-checked, and measured on this laptop (AMD Ryzen 7 7840HS, 8C/16T, 15.3 GB RAM, CPU-only):

* **Translation:** `ai4bharat/indictrans2-en-indic-dist-200M` (MIT, 2.1 GB fp32, stored at `models/indictrans2-en-indic-dist-200M`) via `IndicTransToolkit` 1.1.1 `IndicProcessor`. Measured: 9.3 s load, 2.5–2.8 s per two-sentence batch on CPU. Scene titles, narration, captions, and prose `visual_data` keys are translated; `code`, `execution_data`, and other keys pass through untouched, keeping `for`, `fruit`, `print`, and numbers in English. A target-script ratio gate rejects non-Devanagari/non-Kannada output; failures return the deterministic native-script sample with `fallback_reason: "translation_unavailable"`.
* **Kannada narration:** `ai4bharat/indic-parler-tts` (Apache-2.0, 938M fp32, 3.6 GB, stored at `models/indic-parler-tts`; there is no official "mini" release — `indic-parler-tts-pretrained` is the same size and is the configured fallback) via `parler-tts` (Apache-2.0, pinned commit `d108732cd57788ec`). The voice description is tokenized with the bundled `google/flan-t5-large` tokenizer files (`models/flan-t5-large-tokenizer`), as the model card requires. Measured single-sentence benchmark: 9.8 s load, **RTF ≈ 9×** (61.6 s synthesis → 6.8 s audio, peak 0.636, fully voiced).
* **Decoding note:** the repo's `generation_config.json` sets `do_sample: true` and `max_length: 2610` (≈30.3 s of DAC frames). Forcing greedy decoding (`do_sample=False`) produced exactly 30.3 s of near-silent output that hit max-length; the narrator therefore samples with a per-chunk text-derived torch seed (reproducible) and fails loudly if peak amplitude is below 0.005.
* **Hugging Face gated access:** both AI4Bharat repos required accepting usage terms plus a read token for the one-time download (`HF_HUB_DISABLE_XET=1` was required on this network; the xet transfer stalled while plain HTTPS ran at ~7 MB/s). The token is not read at runtime.
* **End-to-end Kannada render (offline pipeline, `python -m backend.run_kannada_sample`):** `output/videos/lessons/lesson-b70d9232ddab-889fb5cc89d043a5bc3a391571645b07.mp4` — 46.076 s, 1280×720, H.264/AAC, FFprobe-verified. Scene audio 10.76 / 20.32 / 13.94 s (audio-derived timing plus 0.35 s pause). Stage timings: narration 394.6 s (dominated by Parler CPU synthesis), scene render 22.4 s, encode 9.2 s, total 426.9 s. SRT captions are Kannada script with `for`, `fruit`, and `output` preserved in Latin script.
* **Caching:** every Parler chunk is cached under `models/tts-cache/indic-parler/` keyed by language, voice description, and text hash, so re-rendering the same lesson is near-instant and pre-warming the fixed sample before the live demo is possible.

**Still outstanding for this stage:** human listening review of the Kannada and Hindi narration (intelligibility and accent), a browser-on-a-phone playback check, and an offline Wi-Fi-off dress rehearsal of the full API path. Everything else in Stage 4 — three languages with audio, correct scripts, translated narration for arbitrary topics, and sync — is implemented and machine-verified.

