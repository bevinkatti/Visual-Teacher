import { useEffect, useRef, useState, type SyntheticEvent } from 'react'
import {
  VisualLessonCanvas,
  type CauseEffectData,
  type CodeExecutionData,
  type CycleData,
  type EquationStepsData,
  type FractionModelData,
  type NumberLineData,
  type VisualScene,
  type VisualTimelineFrame,
} from './VisualLessonCanvas'
import './App.css'

type LessonSource = 'ollama' | 'sample'
type FallbackReason =
  | 'unavailable'
  | 'timeout'
  | 'http_error'
  | 'invalid_output'
  | 'translation_unavailable'
  | null

type LessonScene = VisualScene & {
  pause_seconds: number
  execution_data?: CodeExecutionData | null
  fraction_data?: FractionModelData | null
  cause_effect_data?: CauseEffectData | null
  number_line_data?: NumberLineData | null
  equation_steps_data?: EquationStepsData | null
  cycle_data?: CycleData | null
}

type Lesson = {
  id: string
  topic: string
  level: 'beginner' | 'intermediate'
  language: 'en' | 'hi' | 'kn'
  target_duration_seconds: 30 | 60 | 90
  scenes: LessonScene[]
  source: LessonSource
  fallback: boolean
  fallback_reason: FallbackReason
}

type RenderJob = {
  job_id: string
  lesson_id: string
  status: 'queued' | 'rendering' | 'completed' | 'failed'
  output_filename: string
  duration_seconds: number | null
  target_duration_seconds: number | null
  duration_within_tolerance: boolean | null
  video_url: string | null
  download_url: string | null
  captions_url: string | null
  manifest_url: string | null
  error: string | null
}

type ManifestScene = {
  title: string
  start_seconds: number
  audio_seconds: number
  pause_seconds: number
  end_seconds: number
  captions: { text: string; start_seconds: number; end_seconds: number }[]
  visual_timeline: VisualTimelineFrame[]
}

type RenderManifest = { lesson_id: string; scenes: ManifestScene[] }
type ApiError = { detail?: unknown }

const fallbackMessages: Record<Exclude<FallbackReason, null>, string> = {
  unavailable: 'Ollama could not be reached.',
  timeout: 'Ollama did not finish before the configured timeout.',
  http_error: 'Ollama returned an HTTP error.',
  invalid_output: 'Ollama returned a lesson that failed validation.',
  translation_unavailable: 'Local translation into the requested language was unavailable; showing the built-in sample lesson.',
}

const initialExample: LessonScene = {
  title: 'Follow a Python loop',
  narration: 'One item gets one turn. The instruction runs again for the next item.',
  caption: 'A for loop gives each list item one turn.',
  visual_type: 'code_execution',
  visual_data: { purpose: 'one iteration per value' },
  execution_data: { variable_name: 'fruit', iterable_name: 'fruits', values: ['apple', 'pear', 'plum'] },
  pause_seconds: 0.35,
}

const languages = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'हिन्दी' },
  { value: 'kn', label: 'ಕನ್ನಡ' },
] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isExecutionData(value: unknown): value is CodeExecutionData {
  return isRecord(value) &&
    typeof value.variable_name === 'string' && /^[A-Za-z_][A-Za-z0-9_]{0,19}$/.test(value.variable_name) &&
    typeof value.iterable_name === 'string' && value.iterable_name.trim().length > 0 && value.iterable_name.length <= 32 &&
    Array.isArray(value.values) && value.values.length >= 2 && value.values.length <= 6 &&
    value.values.every((item) => typeof item === 'string' && item.trim().length > 0 && item.length <= 32 && !Array.from(item).some((character) => character.charCodeAt(0) < 32))
}

function isFractionData(value: unknown): value is FractionModelData {
  return isRecord(value) && Object.keys(value).length === 2 &&
    typeof value.numerator === 'number' && Number.isInteger(value.numerator) && value.numerator >= 1 && value.numerator <= 8 &&
    typeof value.denominator === 'number' && Number.isInteger(value.denominator) && value.denominator >= 2 && value.denominator <= 8 &&
    value.numerator <= value.denominator
}

function isCauseEffectData(value: unknown): value is CauseEffectData {
  const validLabels = (labels: unknown, minimum: number, maximum: number) =>
    Array.isArray(labels) && labels.length >= minimum && labels.length <= maximum &&
    labels.every((label) => typeof label === 'string' && label.trim().length > 0 && label.length <= 48 && !Array.from(label).some((character) => character.charCodeAt(0) < 32))
  return isRecord(value) && Object.keys(value).length === 3 &&
    validLabels(value.inputs, 2, 3) && validLabels(value.outputs, 1, 2) &&
    typeof value.mechanism === 'string' && value.mechanism.trim().length > 0 && value.mechanism.length <= 48 &&
    !Array.from(value.mechanism).some((character) => character.charCodeAt(0) < 32)
}

function isNumberLineData(value: unknown): value is NumberLineData {
  if (!isRecord(value) || Object.keys(value).length !== 4) return false
  if (typeof value.start_value !== 'number' || !Number.isInteger(value.start_value) || value.start_value < -20 || value.start_value > 20) return false
  if (typeof value.result !== 'number' || !Number.isInteger(value.result) || value.result < -20 || value.result > 20) return false
  if (!Array.isArray(value.jumps) || value.jumps.length < 1 || value.jumps.length > 4 || !Array.isArray(value.operation_labels)) return false
  if (value.operation_labels.length !== value.jumps.length || !value.operation_labels.every((label) => typeof label === 'string' && label.trim().length > 0 && label.length <= 32 && !Array.from(label).some((character) => character.charCodeAt(0) < 32))) return false
  let position = value.start_value
  for (const jump of value.jumps) {
    if (typeof jump !== 'number' || !Number.isInteger(jump) || jump === 0 || jump < -20 || jump > 20) return false
    position += jump
    if (position < -20 || position > 20) return false
  }
  return position === value.result
}

function isEquationStepsData(value: unknown): value is EquationStepsData {
  return isRecord(value) && Object.keys(value).length === 2 &&
    Array.isArray(value.equations) && value.equations.length >= 2 && value.equations.length <= 5 &&
    value.equations.every((item) => typeof item === 'string' && item.trim().length > 0 && item.length <= 64 && !Array.from(item).some((character) => character.charCodeAt(0) < 32)) &&
    Array.isArray(value.operations) && value.operations.length === value.equations.length - 1 &&
    value.operations.every((item) => typeof item === 'string' && item.trim().length > 0 && item.length <= 48 && !Array.from(item).some((character) => character.charCodeAt(0) < 32))
}

function isCycleData(value: unknown): value is CycleData {
  return isRecord(value) && Object.keys(value).length === 2 &&
    typeof value.center_label === 'string' && value.center_label.trim().length > 0 && value.center_label.length <= 40 &&
    Array.isArray(value.stages) && value.stages.length >= 3 && value.stages.length <= 6 &&
    value.stages.every((item) => typeof item === 'string' && item.trim().length > 0 && item.length <= 48 && !Array.from(item).some((character) => character.charCodeAt(0) < 32)) &&
    new Set(value.stages.map((item) => item.toLocaleLowerCase())).size === value.stages.length
}

function isScene(value: unknown): value is LessonScene {
  if (!isRecord(value) || !isRecord(value.visual_data)) return false
  const validVisual = ['title_card', 'concept', 'flow', 'code', 'concept_diagram', 'process_flow', 'code_execution', 'fraction_model', 'cause_effect', 'number_line', 'equation_steps', 'cycle'].includes(String(value.visual_type))
  const executionValid = value.execution_data === null || value.execution_data === undefined || isExecutionData(value.execution_data)
  const fractionValid = value.fraction_data === null || value.fraction_data === undefined || isFractionData(value.fraction_data)
  const causeEffectValid = value.cause_effect_data === null || value.cause_effect_data === undefined || isCauseEffectData(value.cause_effect_data)
  const numberLineValid = value.number_line_data === null || value.number_line_data === undefined || isNumberLineData(value.number_line_data)
  const equationStepsValid = value.equation_steps_data === null || value.equation_steps_data === undefined || isEquationStepsData(value.equation_steps_data)
  const cycleValid = value.cycle_data === null || value.cycle_data === undefined || isCycleData(value.cycle_data)
  return typeof value.title === 'string' && value.title.trim().length >= 3 && value.title.length <= 100 &&
    typeof value.narration === 'string' && value.narration.trim().length >= 5 && value.narration.length <= 1200 &&
    typeof value.caption === 'string' && value.caption.trim().length >= 3 && value.caption.length <= 300 &&
    validVisual && executionValid && fractionValid && causeEffectValid && numberLineValid && equationStepsValid && cycleValid &&
    (value.visual_type !== 'code_execution' || isExecutionData(value.execution_data)) &&
    (value.visual_type === 'code_execution' || value.execution_data == null) &&
    (value.visual_type !== 'fraction_model' || isFractionData(value.fraction_data)) &&
    (value.visual_type === 'fraction_model' || value.fraction_data == null) &&
    (value.visual_type !== 'cause_effect' || isCauseEffectData(value.cause_effect_data)) &&
    (value.visual_type === 'cause_effect' || value.cause_effect_data == null) &&
    (value.visual_type !== 'number_line' || isNumberLineData(value.number_line_data)) &&
    (value.visual_type === 'number_line' || value.number_line_data == null) &&
    (value.visual_type !== 'equation_steps' || isEquationStepsData(value.equation_steps_data)) &&
    (value.visual_type === 'equation_steps' || value.equation_steps_data == null) &&
    (value.visual_type !== 'cycle' || isCycleData(value.cycle_data)) &&
    (value.visual_type === 'cycle' || value.cycle_data == null) &&
    Object.keys(value.visual_data).length <= 16 &&
    Object.entries(value.visual_data).every(([key, item]) => key.trim().length > 0 && key.length <= 40 && typeof item === 'string' && item.trim().length > 0 && item.length <= 320) &&
    typeof value.pause_seconds === 'number' && Number.isFinite(value.pause_seconds) && value.pause_seconds >= 0 && value.pause_seconds <= 1.5
}

function isLesson(value: unknown): value is Lesson {
  if (!isRecord(value) || !Array.isArray(value.scenes)) return false
  const plannerStatus =
    (value.source === 'ollama' && value.fallback === false && value.fallback_reason === null) ||
    (value.source === 'sample' && value.fallback === false && value.fallback_reason === null) ||
    (value.source === 'sample' && value.fallback === true && value.fallback_reason !== null)
  return typeof value.id === 'string' && /^[a-f0-9]{12}$/.test(value.id) &&
    typeof value.topic === 'string' &&
    (value.level === 'beginner' || value.level === 'intermediate') &&
    (value.language === 'en' || value.language === 'hi' || value.language === 'kn') &&
    (value.target_duration_seconds === 30 || value.target_duration_seconds === 45 || value.target_duration_seconds === 60 || value.target_duration_seconds === 90) &&
    (value.source === 'ollama' || value.source === 'sample') && typeof value.fallback === 'boolean' &&
    (value.fallback_reason === null || value.fallback_reason === 'unavailable' || value.fallback_reason === 'timeout' || value.fallback_reason === 'http_error' || value.fallback_reason === 'invalid_output') &&
    plannerStatus && value.scenes.length >= 3 && value.scenes.length <= 6 && value.scenes.every(isScene)
}

function isRenderJob(value: unknown): value is RenderJob {
  if (!isRecord(value)) return false
  const valid = typeof value.job_id === 'string' && /^[a-f0-9]{32}$/.test(value.job_id) &&
    typeof value.lesson_id === 'string' && /^[a-f0-9]{12}$/.test(value.lesson_id) &&
    (value.status === 'queued' || value.status === 'rendering' || value.status === 'completed' || value.status === 'failed') &&
    value.output_filename === `lesson-${value.lesson_id}-${value.job_id}.mp4` &&
    (value.duration_seconds === null || (typeof value.duration_seconds === 'number' && Number.isFinite(value.duration_seconds) && value.duration_seconds > 0)) &&
    (value.video_url === null || typeof value.video_url === 'string') &&
    (value.download_url === null || typeof value.download_url === 'string') &&
    (value.captions_url === null || typeof value.captions_url === 'string') &&
    (value.manifest_url === null || typeof value.manifest_url === 'string') &&
    (value.error === null || typeof value.error === 'string')
  if (!valid) return false
  if (value.status === 'completed') return value.video_url === `/api/media/${value.job_id}/video` &&
    value.download_url === `/api/media/${value.job_id}/download` &&
    value.captions_url === `/api/media/${value.job_id}/captions` &&
    value.manifest_url === `/api/media/${value.job_id}/manifest` &&
    typeof value.duration_seconds === 'number' && value.error === null
  if (value.status === 'failed') return typeof value.error === 'string' && value.error.length > 0 && value.duration_seconds === null &&
    value.video_url === null && value.download_url === null && value.captions_url === null && value.manifest_url === null
  return value.duration_seconds === null && value.error === null && value.video_url === null && value.download_url === null && value.captions_url === null && value.manifest_url === null
}

function isRenderManifest(value: unknown, lesson: Lesson): value is RenderManifest {
  if (!isRecord(value) || value.lesson_id !== lesson.id || !Array.isArray(value.scenes) || value.scenes.length !== lesson.scenes.length) return false
  return value.scenes.every((raw, index) => {
    if (!isRecord(raw) || raw.title !== lesson.scenes[index].title || !Array.isArray(raw.visual_timeline) || !Array.isArray(raw.captions) || raw.captions.length === 0) return false
    const finite = ['start_seconds', 'audio_seconds', 'pause_seconds', 'end_seconds'].every((key) => typeof raw[key] === 'number' && Number.isFinite(raw[key]))
    if (!finite || (raw.start_seconds as number) < 0 || (raw.audio_seconds as number) <= 0 || (raw.pause_seconds as number) < 0) return false
    const audioEnd = (raw.start_seconds as number) + (raw.audio_seconds as number)
    let previousCaptionEnd = raw.start_seconds as number
    const captionsAreTimed = raw.captions.every((cue) => {
      if (!isRecord(cue) || typeof cue.text !== 'string' || !cue.text.trim() || cue.text.length > 300 ||
        typeof cue.start_seconds !== 'number' || !Number.isFinite(cue.start_seconds) ||
        typeof cue.end_seconds !== 'number' || !Number.isFinite(cue.end_seconds)) return false
      if (cue.start_seconds < previousCaptionEnd - 0.001 || cue.end_seconds <= cue.start_seconds ||
        cue.end_seconds > audioEnd + 0.01) return false
      previousCaptionEnd = cue.end_seconds
      return true
    })
    return captionsAreTimed && Math.abs((raw.captions[0] as Record<string, number>).start_seconds - (raw.start_seconds as number)) < 0.01 &&
      Math.abs(previousCaptionEnd - audioEnd) < 0.01 && raw.visual_timeline.every((frame) => isRecord(frame) &&
      typeof frame.start_progress === 'number' && typeof frame.end_progress === 'number' &&
      typeof frame.phase === 'string' && typeof frame.active_line === 'number' &&
      typeof frame.iteration === 'number' && (frame.value === null || typeof frame.value === 'string') &&
      Array.isArray(frame.output) && frame.output.every((item) => typeof item === 'string') && typeof frame.status === 'string')
  })
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ApiError
    if (Array.isArray(body.detail)) {
      const messages = body.detail.map((item) => isRecord(item) && typeof item.msg === 'string' ? item.msg : '').filter(Boolean)
      if (messages.length > 0) return messages.join(' ')
    }
    if (typeof body.detail === 'string') return body.detail
  } catch {
    // Fall back to a status-based message when the service body is not JSON.
  }
  return `The local service returned HTTP ${response.status}.`
}

function plannerStatus(lesson: Lesson) {
  if (lesson.fallback) {
    const reason = lesson.fallback_reason ? fallbackMessages[lesson.fallback_reason] : 'The local planner failed.'
    return `Sample fallback shown. ${reason} The built-in sample text is used; narration is English.`
  }
  return lesson.source === 'ollama' ? 'Lesson plan created by the local Ollama model.' : 'Sample lesson loaded.'
}

function App() {
  const [topic, setTopic] = useState('How Python for-loops work')
  const [level, setLevel] = useState<'beginner' | 'intermediate'>('beginner')
  const [language, setLanguage] = useState<'en' | 'hi' | 'kn'>('en')
  const [duration, setDuration] = useState<'30' | '45' | '60' | '90'>('30')
  const [lesson, setLesson] = useState<Lesson | null>(null)
  const [activeSceneIndex, setActiveSceneIndex] = useState(0)
  const [previewProgress, setPreviewProgress] = useState(0)
  const [captionAudioActive, setCaptionAudioActive] = useState(true)
  const [captionText, setCaptionText] = useState('')
  const [createError, setCreateError] = useState('')
  const [notice, setNotice] = useState('')
  const [isCreating, setIsCreating] = useState(false)
  const [renderJob, setRenderJob] = useState<RenderJob | null>(null)
  const [renderManifest, setRenderManifest] = useState<RenderManifest | null>(null)
  const [renderError, setRenderError] = useState('')
  const [isRendering, setIsRendering] = useState(false)
  const createInFlight = useRef(false)
  const renderInFlight = useRef(false)
  const pollController = useRef<AbortController | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)

  const scenes = lesson?.scenes ?? []
  const scene = scenes[activeSceneIndex] ?? initialExample
  const sceneManifest = renderManifest?.scenes[activeSceneIndex]
  const displayBadge = lesson ? lesson.fallback ? 'SAMPLE FALLBACK' : lesson.source === 'ollama' ? 'OLLAMA PLAN' : 'SAMPLE LESSON' : 'EXAMPLE · NOT GENERATED'
  const visualProgress = Math.min(1, Math.max(0, previewProgress))

  useEffect(() => () => pollController.current?.abort(), [])

  async function createLesson() {
    if (createInFlight.current || renderInFlight.current) return
    const cleanTopic = topic.trim()
    if (cleanTopic.length < 3 || cleanTopic.length > 180) {
      setCreateError('Enter a topic between 3 and 180 characters.')
      setNotice('')
      return
    }
    createInFlight.current = true
    setIsCreating(true)
    setCreateError('')
    setNotice('Sending the request to the local lesson planner…')
    try {
      const response = await fetch('/api/lessons', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: cleanTopic, level, language, duration_seconds: Number(duration) }),
      })
      if (!response.ok) throw new Error(await readError(response))
      const result: unknown = await response.json()
      if (!isLesson(result)) throw new Error('The local lesson service returned an invalid lesson response.')
      setLesson(result)
      setActiveSceneIndex(0)
      setPreviewProgress(0)
      setCaptionAudioActive(true)
      setCaptionText('')
      setRenderJob(null)
      setRenderManifest(null)
      setRenderError('')
      setNotice(plannerStatus(result))
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : 'The local lesson request failed. Please retry.')
      setNotice('')
    } finally {
      createInFlight.current = false
      setIsCreating(false)
    }
  }

  async function loadManifest(job: RenderJob, currentLesson: Lesson) {
    if (!job.manifest_url) throw new Error('The completed render did not provide a timing manifest.')
    const response = await fetch(job.manifest_url)
    if (!response.ok) throw new Error(await readError(response))
    const result: unknown = await response.json()
    if (!isRenderManifest(result, currentLesson)) throw new Error('The render timing manifest did not match the lesson scenes.')
    setRenderManifest(result)
  }

  async function waitForRender(jobId: string, signal: AbortSignal): Promise<RenderJob | null> {
    while (!signal.aborted) {
      await new Promise<void>((resolve) => window.setTimeout(resolve, 650))
      if (signal.aborted) return null
      const response = await fetch(`/api/renders/${encodeURIComponent(jobId)}`, { signal })
      if (!response.ok) throw new Error(await readError(response))
      const result: unknown = await response.json()
      if (!isRenderJob(result)) throw new Error('The render service returned an invalid job status.')
      setRenderJob(result)
      if (result.status === 'completed' || result.status === 'failed') return result
    }
    return null
  }

  async function startRender() {
    if (!lesson || renderInFlight.current || renderJob?.status === 'completed') return
    renderInFlight.current = true
    pollController.current?.abort()
    const controller = new AbortController()
    pollController.current = controller
    setIsRendering(true)
    setRenderError('')
    setRenderManifest(null)
    try {
      const response = await fetch(`/api/lessons/${encodeURIComponent(lesson.id)}/render`, { method: 'POST' })
      if (!response.ok) throw new Error(await readError(response))
      const initial: unknown = await response.json()
      if (!isRenderJob(initial)) throw new Error('The render service returned an invalid job status.')
      setRenderJob(initial)
      const finalJob = initial.status === 'queued' || initial.status === 'rendering'
        ? await waitForRender(initial.job_id, controller.signal)
        : initial
      if (finalJob?.status === 'completed') await loadManifest(finalJob, lesson)
      if (finalJob?.status === 'failed') setRenderError(finalJob.error ?? 'The render failed. Please retry.')
    } catch (error) {
      if (!controller.signal.aborted) setRenderError(error instanceof Error ? error.message : 'The local render request failed. Please retry.')
    } finally {
      renderInFlight.current = false
      setIsRendering(false)
    }
  }

  function syncPreviewToVideo(event: SyntheticEvent<HTMLVideoElement>) {
    if (!renderManifest) return
    const currentTime = event.currentTarget.currentTime
    const sceneIndex = renderManifest.scenes.findIndex((entry, index) =>
      currentTime >= entry.start_seconds && (currentTime < entry.end_seconds || index === renderManifest.scenes.length - 1),
    )
    if (sceneIndex < 0) return
    const timing = renderManifest.scenes[sceneIndex]
    setActiveSceneIndex(sceneIndex)
    setPreviewProgress(Math.min(1, (currentTime - timing.start_seconds) / timing.audio_seconds))
    const activeCaption = timing.captions.find(
      (cue) => currentTime >= cue.start_seconds && currentTime < cue.end_seconds,
    )
    setCaptionText(activeCaption?.text ?? '')
    setCaptionAudioActive(Boolean(activeCaption))
  }

  function seekToScene(index: number, shouldPlay: boolean) {
    const timing = renderManifest?.scenes[index]
    const video = videoRef.current
    if (!timing || !video) return
    video.currentTime = timing.start_seconds
    setActiveSceneIndex(index)
    setPreviewProgress(0)
    setCaptionText(timing.captions[0]?.text ?? '')
    setCaptionAudioActive(Boolean(timing.captions[0]))
    if (shouldPlay) {
      void video.play().catch(() => setRenderError('The browser could not start playback. Press Play on the video to continue.'))
    }
  }

  function nextVideoScene() {
    if (activeSceneIndex + 1 < (renderManifest?.scenes.length ?? 0)) {
      seekToScene(activeSceneIndex + 1, true)
    }
  }

  const currentTimeline = sceneManifest?.visual_timeline

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#home" aria-label="Blu Visual Teacher home">
          <span className="brand-mark">b<span>.</span></span>
          <span className="brand-name">blu<span>teacher</span></span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <nav className="sidebar-nav" aria-label="Workspace navigation">
          <button className="nav-item selected" type="button"><span className="nav-icon">◈</span><span>Lesson studio</span><span className="nav-indicator" /></button>
          <button className="nav-item" type="button" onClick={() => setNotice('Your lesson library will appear here as saved lessons are added.')}><span className="nav-icon">▤</span><span>My lessons</span></button>
          <button className="nav-item" type="button" onClick={() => setNotice('Qwen2.5 3B runs through the local Ollama service. See the README for model details.')}><span className="nav-icon">⌘</span><span>Local AI models</span></button>
        </nav>
        <div className="sidebar-bottom">
          <div className="offline-card"><span className="status-dot" /><div><strong>Local-first studio</strong><p>Requests stay on this device</p></div></div>
          <div className="sidebar-foot">BUILT FOR CURIOUS MINDS</div>
        </div>
      </aside>

      <section className="main-area" id="home">
        <header className="topbar">
          <div className="breadcrumb">Workspace <span>/</span> <strong>Lesson studio</strong></div>
          <div className="topbar-right"><span className="local-pill"><span className="status-dot" /> LOCAL MODE</span><div className="avatar">B</div></div>
        </header>

        <div className="page-content">
          <section className="hero">
            <div className="hero-copy">
              <div className="hero-kicker"><span className="hero-kicker-mark">✳</span> LEARN BY SEEING</div>
              <h1>Make the idea <span>click.</span></h1>
              <p>Blu turns a question into a visual lesson you can follow, hear, and keep.</p>
              <div className="hero-local"><span className="status-dot" /> Local planning · Narration and rendering stay on this device</div>
            </div>
            <div className="hero-visual" aria-label="Example visual: a loop visits each fruit and prints it">
              <div className="hero-visual-label"><span>REFERENCE VISUAL</span><span>PYTHON · FOR LOOP</span></div>
              <div className="hero-code-line"><span>01</span><code>for fruit in fruits:</code></div>
              <div className="hero-code-line hero-code-line-active"><span>02</span><code>    print(fruit)</code></div>
              <div className="hero-loop-flow"><span>apple</span><i /><span>pear</span><i /><span>plum</span></div>
              <div className="hero-glow" />
            </div>
          </section>

          <div className="studio-grid">
            <section className="config-panel" aria-labelledby="design-title">
              <div className="panel-heading"><div><span className="step-label">01 / SET THE QUESTION</span><h2 id="design-title">What should we unpack?</h2></div><span className="heading-index">01</span></div>

              <label className="field-label" htmlFor="topic">WHAT DO YOU WANT TO LEARN?</label>
              <textarea id="topic" className="topic-input" value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="e.g. How neural networks learn" rows={3} maxLength={180} aria-invalid={Boolean(createError)} aria-describedby={createError ? 'create-error' : 'topic-hint'} />
              <div className="input-hint" id="topic-hint">Ask a focused question. We will build the lesson around it.</div>

              <div className="field-block"><span className="field-label">LEARNING LEVEL</span><div className="segmented" role="group" aria-label="Learning level">
                <button type="button" className={level === 'beginner' ? 'segment active' : 'segment'} onClick={() => setLevel('beginner')} aria-pressed={level === 'beginner'}>Beginner</button>
                <button type="button" className={level === 'intermediate' ? 'segment active' : 'segment'} onClick={() => setLevel('intermediate')} aria-pressed={level === 'intermediate'}>Intermediate</button>
              </div></div>

              <div className="field-row">
                <div className="field-block"><label className="field-label" htmlFor="duration">LESSON LENGTH</label><div className="select-wrap"><select id="duration" value={duration} onChange={(event) => setDuration(event.target.value as '30' | '45' | '60' | '90')}><option value="30">30 seconds</option><option value="45">45 seconds</option><option value="60">60 seconds</option><option value="90">90 seconds</option></select><span aria-hidden="true">⌄</span></div></div>
                <div className="field-block"><label className="field-label" htmlFor="language">LESSON LANGUAGE</label><div className="select-wrap"><select id="language" value={language} onChange={(event) => setLanguage(event.target.value as 'en' | 'hi' | 'kn')}>{languages.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><span aria-hidden="true">⌄</span></div></div>
              </div>
              <p className="language-note"><span aria-hidden="true">文</span><span><strong>Local voice support:</strong> English and Devanagari Hindi. Kannada is unavailable; Indian-accent English is not yet verified.</span></p>

              <button className="create-button" type="button" onClick={createLesson} disabled={isCreating || isRendering} aria-busy={isCreating}>
                <span>{isCreating ? 'Building your lesson…' : createError ? 'Retry lesson request' : 'Create my lesson'}</span><span className="button-arrow" aria-hidden="true">↗</span>
              </button>
              <p className="privacy-note"><span>◉</span> Lesson planning uses the local Ollama model.</p>
              {isCreating && <div className="notice" role="status">Generating a structured lesson with the local model…</div>}
              {notice && !isCreating && <div className={`notice ${lesson?.fallback ? 'notice-fallback' : ''}`} role="status">{notice}</div>}
              {createError && <div className="notice notice-error" id="create-error" role="alert">{createError}</div>}
              {lesson && <button className="render-button" type="button" onClick={startRender} disabled={isRendering || isCreating || renderJob?.status === 'completed'} aria-busy={isRendering}>
                {isRendering ? 'Rendering narrated lesson…' : renderJob?.status === 'completed' ? 'Video ready' : renderJob?.status === 'failed' ? 'Retry video render' : 'Render narrated MP4'}
                <span aria-hidden="true">↗</span>
              </button>}
              {renderError && <div className="notice notice-error" role="alert">{renderError}</div>}
            </section>

            <section className="preview-panel" aria-labelledby="preview-title">
              <div className="preview-header"><div><span className="step-label">02 / WATCH IT UNFOLD</span><h2 id="preview-title">Lesson canvas</h2></div><span className={`preview-badge ${lesson?.fallback ? 'preview-badge-fallback' : ''}`}><span className="status-dot" />{displayBadge}</span></div>
              {lesson && <p className="lesson-meta"><strong>{lesson.topic}</strong><span>{lesson.scenes.length} scenes · {lesson.level} · {lesson.language.toUpperCase()} · {lesson.target_duration_seconds}s target</span></p>}

              <div className="stage-topline"><span><span className="stage-live-dot" /> BLU CLASSROOM</span><span>SCENE {String(lesson ? activeSceneIndex + 1 : 1).padStart(2, '0')} <i>/</i> {String(lesson ? scenes.length : 1).padStart(2, '0')}</span></div>
              <div className="stage-title"><span>{lesson ? `SCENE ${String(activeSceneIndex + 1).padStart(2, '0')} · ${scene.visual_type.replace(/_/g, ' ').toUpperCase()}` : 'EXAMPLE VISUAL · NOT GENERATED'}</span><h3>{scene.title}</h3></div>
              <VisualLessonCanvas scene={scene} progress={visualProgress} timeline={currentTimeline} />
              <div className="stage-caption" aria-hidden={!captionAudioActive} style={{ visibility: captionAudioActive ? 'visible' : 'hidden' }}><span>CAPTION</span><p>{renderManifest ? captionText : scene.caption}</p></div>
              <div className="visual-scrubber"><label htmlFor="visual-progress">VISUAL STATE <span>{renderManifest ? 'SYNCED TO NARRATION' : 'PREVIEW TIMELINE'}</span></label><input id="visual-progress" type="range" min="0" max="100" value={Math.round(visualProgress * 100)} onChange={(event) => { setPreviewProgress(Number(event.target.value) / 100); setCaptionAudioActive(true) }} aria-label="Preview visual progress" /><div className="scrubber-labels"><span>Ready</span><span>{scene.visual_type === 'code_execution' ? 'Each iteration' : 'Reveal'}</span><span>Complete</span></div></div>

              {lesson ? <div className="scene-controls">
                <div className="scene-list" style={{ gridTemplateColumns: `repeat(${Math.min(lesson.scenes.length, 3)}, minmax(0, 1fr))` }}>
                  {lesson.scenes.map((item, index) => <button key={`${lesson.id}-${index}`} type="button" className={index === activeSceneIndex ? 'scene-tab active' : 'scene-tab'} onClick={() => { setActiveSceneIndex(index); setPreviewProgress(0); setCaptionAudioActive(true) }} aria-label={`Show scene ${index + 1}: ${item.title}`} aria-pressed={index === activeSceneIndex}><span className="scene-number">{String(index + 1).padStart(2, '0')}</span><span className="scene-tab-title">{item.title}</span></button>)}
                </div>
                <section className="scene-copy" aria-label={`Scene ${activeSceneIndex + 1} details`}><div><strong>NARRATION</strong><p>{scene.narration}</p></div><div><strong>VISUAL DATA · {scene.visual_type.replace(/_/g, ' ').toUpperCase()}</strong><dl>
                  {Object.entries(scene.visual_data).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
                  {scene.execution_data && <div><dt>Iterations</dt><dd>{scene.execution_data.values.join(' → ')}</dd></div>}
                  {scene.fraction_data && <><div><dt>Selected parts</dt><dd>{scene.fraction_data.numerator}</dd></div><div><dt>Equal parts</dt><dd>{scene.fraction_data.denominator}</dd></div></>}
                  {scene.cause_effect_data && <><div><dt>Inputs</dt><dd>{scene.cause_effect_data.inputs.join(' · ')}</dd></div><div><dt>Mechanism</dt><dd>{scene.cause_effect_data.mechanism}</dd></div><div><dt>Outputs</dt><dd>{scene.cause_effect_data.outputs.join(' · ')}</dd></div></>}
                  {scene.number_line_data && <><div><dt>Start</dt><dd>{scene.number_line_data.start_value}</dd></div><div><dt>Jumps</dt><dd>{scene.number_line_data.operation_labels.join(' · ')}</dd></div><div><dt>Result</dt><dd>{scene.number_line_data.result}</dd></div></>}
                  {scene.equation_steps_data && <><div><dt>Transformations</dt><dd>{scene.equation_steps_data.operations.join(' · ')}</dd></div><div><dt>Final equation</dt><dd>{scene.equation_steps_data.equations[scene.equation_steps_data.equations.length - 1]}</dd></div></>}
                  {scene.cycle_data && <><div><dt>Cycle</dt><dd>{scene.cycle_data.center_label}</dd></div><div><dt>Stages</dt><dd>{scene.cycle_data.stages.join(' → ')}</dd></div></>}
                </dl></div></section>
              </div> : <p className="example-note">This is a built-in example preview. Create a lesson to replace it with model-generated lesson content.</p>}

              {renderJob && <section className="render-panel" aria-live="polite" aria-label="MP4 render status">
                <div className="render-panel-heading"><div><span className="step-label">03 / LISTEN & PLAY</span><h3>Rendered lesson</h3></div><span className={`render-state render-state-${renderJob.status}`}>{renderJob.status.toUpperCase()}</span></div>
                <p className="render-filename">{renderJob.output_filename}</p>
                {renderJob.status === 'queued' && <p role="status">Render queued. Media will be available after synthesis and export finish.</p>}
                {renderJob.status === 'rendering' && <p role="status">{lesson?.language === 'kn' ? 'Kannada narration uses the local Indic Parler-TTS voice, which is slower on CPU. This can take 10–20 minutes.' : 'Local narration, captions, and video are being generated. This can take a few minutes.'}</p>}
                {renderJob.status === 'failed' && <p className="notice-error" role="alert">{renderJob.error ?? 'The render failed. Retry when ready.'}</p>}
                {renderJob.status === 'completed' && renderJob.video_url && renderJob.download_url && renderJob.captions_url && <>
                  <p className="render-complete">Completed · {renderJob.duration_seconds?.toFixed(2)} seconds{renderJob.target_duration_seconds ? ` (target ${renderJob.target_duration_seconds}s${renderJob.duration_within_tolerance === false ? ' · over target' : ' · on target'})` : ''}{renderManifest ? ' · visual preview synced to the exported timing manifest' : ''}</p>
                  <video ref={videoRef} className="lesson-video" controls playsInline preload="metadata" src={renderJob.video_url} onTimeUpdate={syncPreviewToVideo} aria-label="Generated lesson video" />
                  {renderManifest && <div className="video-scene-controls" aria-label="Video scene controls">
                    <button type="button" onClick={nextVideoScene} disabled={activeSceneIndex >= renderManifest.scenes.length - 1}>Next scene</button>
                    <button type="button" onClick={() => seekToScene(activeSceneIndex, true)}>Replay scene</button>
                  </div>}
                  <div className="media-links"><a href={renderJob.download_url} download={renderJob.output_filename}>Download MP4 <span aria-hidden="true">↓</span></a><a href={renderJob.captions_url} download>Download SRT captions <span aria-hidden="true">↓</span></a></div>
                </>}
              </section>}
            </section>
          </div>

          <footer className="page-footer"><span>BLU VISUAL TEACHER <span className="footer-dot">·</span> LEARN BY SEEING</span><span>LOCAL-FIRST <span className="footer-dot">✳</span> OPEN BY DESIGN</span></footer>
        </div>
      </section>
    </main>
  )
}

export default App
