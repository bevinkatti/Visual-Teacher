import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

function makeLesson(overrides: Record<string, unknown> = {}) {
  return {
    id: 'ab12cd34ef56',
    topic: 'How do fractions show parts of a whole?',
    level: 'beginner',
    language: 'en',
    target_duration_seconds: 30,
    source: 'ollama',
    fallback: false,
    fallback_reason: null,
    scenes: [
      {
        title: 'Fractions name equal parts',
        narration: 'A fraction tells how many equal parts we are considering.',
        caption: 'A fraction names equal parts of a whole.',
        visual_type: 'concept',
        visual_data: { whole: 'One complete shape', part: 'One of four equal pieces' },
        pause_seconds: 0.35,
      },
      {
        title: 'Read the numerator and denominator',
        narration: 'The denominator tells how many equal parts make the whole.',
        caption: 'Denominator: total equal parts.',
        visual_type: 'flow',
        visual_data: { denominator: '4 equal parts', numerator: '1 selected part' },
        pause_seconds: 0.35,
      },
      {
        title: 'Write one quarter',
        narration: 'One of four equal parts is written as one quarter.',
        caption: 'One quarter is written 1 over 4.',
        visual_type: 'code',
        visual_data: { code: '1 / 4', output: 'one quarter' },
        pause_seconds: 0.35,
      },
    ],
    ...overrides,
  }
}

function response(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response
}

function completedJob() {
  return {
    job_id: 'a'.repeat(32),
    lesson_id: 'ab12cd34ef56',
    status: 'completed',
    output_filename: 'lesson-ab12cd34ef56-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.mp4',
    duration_seconds: 35.79,
    video_url: '/api/media/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/video',
    download_url: '/api/media/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/download',
    captions_url: '/api/media/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/captions',
    manifest_url: '/api/media/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/manifest',
    error: null,
  }
}

function renderManifest() {
  const lesson = makeLesson()
  return {
    lesson_id: lesson.id,
    scenes: lesson.scenes.map((scene, index) => ({
      title: scene.title,
      start_seconds: index * 12,
      audio_seconds: 10,
      pause_seconds: 2,
      end_seconds: (index + 1) * 12,
      captions: index === 1
        ? [
          { start_seconds: 12, end_seconds: 15, text: 'The denominator tells how many' },
          { start_seconds: 15, end_seconds: 22, text: 'equal parts make the whole.' },
        ]
        : [{ start_seconds: index * 12, end_seconds: index * 12 + 10, text: scene.narration }],
      visual_timeline: [],
    })),
  }
}

describe('lesson studio API integration', () => {
  const fetchMock = vi.fn<typeof fetch>()

  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('sends actual form values and renders the returned lesson scenes dynamically', async () => {
    const user = userEvent.setup()
    const planned = makeLesson()
    fetchMock.mockResolvedValueOnce(response(planned))
    render(<App />)

    await user.clear(screen.getByLabelText(/what do you want to learn/i))
    await user.type(screen.getByLabelText(/what do you want to learn/i), 'How do fractions show parts of a whole?')
    await user.click(screen.getByRole('button', { name: /intermediate/i }))
    await user.selectOptions(screen.getByLabelText(/lesson length/i), '90')
    await user.selectOptions(screen.getByLabelText(/lesson language/i), 'en')
    await user.click(screen.getByRole('button', { name: /create my lesson/i }))

    expect(await screen.findByRole('heading', { name: 'Fractions name equal parts' })).toBeInTheDocument()
    expect(screen.getByText('OLLAMA PLAN')).toBeInTheDocument()
    expect(screen.getByText('A fraction tells how many equal parts we are considering.')).toBeInTheDocument()
    expect(screen.getByText('A fraction names equal parts of a whole.')).toBeInTheDocument()
    expect(screen.getAllByText('One complete shape')).toHaveLength(2)
    expect(screen.getByRole('button', { name: /show scene 2/i })).toBeInTheDocument()

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/lessons')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({
      topic: 'How do fractions show parts of a whole?',
      level: 'intermediate',
      language: 'en',
      duration_seconds: 90,
    })

    await user.click(screen.getByRole('button', { name: /show scene 2/i }))
    expect(screen.getByRole('heading', { name: 'Read the numerator and denominator' })).toBeInTheDocument()
  })

  it('validates an empty topic in the browser without making a request', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.clear(screen.getByLabelText(/what do you want to learn/i))
    await user.click(screen.getByRole('button', { name: /create my lesson/i }))

    expect(screen.getByRole('alert')).toHaveTextContent('between 3 and 180 characters')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows backend validation errors and offers a retry', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValueOnce(response({ detail: [{ msg: 'String should have at least 3 characters' }] }, 422))
    render(<App />)

    await user.click(screen.getByRole('button', { name: /create my lesson/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('String should have at least 3 characters')
    expect(screen.getByRole('button', { name: /retry lesson request/i })).toBeEnabled()
  })

  it('rejects a lesson response whose source and fallback status disagree', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValueOnce(response(makeLesson({ source: 'ollama', fallback: true, fallback_reason: 'unavailable' })))
    render(<App />)

    await user.click(screen.getByRole('button', { name: /create my lesson/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid lesson response/i)
    expect(screen.queryByText('OLLAMA PLAN')).not.toBeInTheDocument()
  })

  it('prevents repeated submissions while the local API request is pending', async () => {
    const user = userEvent.setup()
    let resolveResponse!: (value: Response) => void
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => { resolveResponse = resolve }))
    render(<App />)

    await user.click(screen.getByRole('button', { name: /create my lesson/i }))
    const pendingButton = screen.getByRole('button', { name: /building your lesson/i })
    expect(pendingButton).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent(/generating a structured lesson with the local model/i)
    await user.click(pendingButton)
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await act(async () => resolveResponse(response(makeLesson())))
    expect(await screen.findByText('OLLAMA PLAN')).toBeInTheDocument()
  })

  it('labels an Ollama failure fallback explicitly instead of claiming success', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValueOnce(response(makeLesson({
      source: 'sample',
      fallback: true,
      fallback_reason: 'unavailable',
    })))
    render(<App />)

    await user.click(screen.getByRole('button', { name: /create my lesson/i }))

    expect(await screen.findByText('SAMPLE FALLBACK')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(/Ollama could not be reached/i)
    expect(screen.getByRole('status')).toHaveTextContent(/narration is English/i)
    expect(screen.queryByText('OLLAMA PLAN')).not.toBeInTheDocument()
  })

  it('renders Unicode captions and visual data without corrupting scripts or arrows', async () => {
    const user = userEvent.setup()
    fetchMock.mockResolvedValueOnce(response(makeLesson({
      language: 'hi',
      scenes: [
        {
          title: 'पूर्ण भाग',
          narration: 'एक पूरा आकार चार बराबर भागों में बाँटा गया है।',
          caption: 'एक चौथाई → १/४',
          visual_type: 'concept',
          visual_data: { भाग: 'ಕನ್ನಡ label', आकार: '४ समान भाग' },
          pause_seconds: 0.35,
        },
        ...makeLesson().scenes.slice(1),
      ],
    })))
    render(<App />)

    await user.click(screen.getByRole('button', { name: /create my lesson/i }))

    expect(await screen.findByRole('heading', { name: 'पूर्ण भाग' })).toBeInTheDocument()
    expect(screen.getByText('एक चौथाई → १/४')).toBeInTheDocument()
    expect(screen.getAllByText('ಕನ್ನಡ label')).toHaveLength(2)
  })

  it('shows a video and download links only after the API reports completed media URLs', async () => {
    const user = userEvent.setup()
    const done = completedJob()
    fetchMock
      .mockResolvedValueOnce(response(makeLesson()))
      .mockResolvedValueOnce(response({ ...done, status: 'queued', duration_seconds: null, video_url: null, download_url: null, captions_url: null, manifest_url: null }))
      .mockResolvedValueOnce(response(done))
      .mockResolvedValueOnce(response(renderManifest()))
    render(<App />)

    await user.click(screen.getByRole('button', { name: /create my lesson/i }))
    await screen.findByText('OLLAMA PLAN')
    await user.click(screen.getByRole('button', { name: /render narrated mp4/i }))

    await waitFor(() => expect(document.querySelector('video')).toHaveAttribute('src', done.video_url), { timeout: 2500 })
    expect(screen.getByRole('link', { name: 'Download MP4' })).toHaveAttribute('href', done.download_url)
    expect(screen.getByRole('link', { name: 'Download SRT captions' })).toHaveAttribute('href', done.captions_url)
    expect(screen.getByText(/completed · 35.79 seconds/i)).toBeInTheDocument()
    expect(screen.getByText(/synced to the exported timing manifest/i)).toBeInTheDocument()
    const video = document.querySelector('video')!
    let currentTime = 13
    Object.defineProperty(video, 'currentTime', { configurable: true, get: () => currentTime, set: (value: number) => { currentTime = value } })
    act(() => video.dispatchEvent(new Event('timeupdate', { bubbles: true })))
    expect(screen.getByRole('heading', { name: 'Read the numerator and denominator' })).toBeInTheDocument()
    const sceneCaption = screen.getByText('The denominator tells how many').closest('.stage-caption')
    expect(sceneCaption).toBeVisible()
    currentTime = 16
    act(() => video.dispatchEvent(new Event('timeupdate', { bubbles: true })))
    expect(screen.getByText('equal parts make the whole.')).toBeVisible()
    currentTime = 22
    act(() => video.dispatchEvent(new Event('timeupdate', { bubbles: true })))
    expect(sceneCaption).not.toBeVisible()
    const playMock = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(video, 'play', { configurable: true, value: playMock })
    await user.click(screen.getByRole('button', { name: 'Next scene' }))
    expect(video.currentTime).toBe(24)
    expect(screen.getByRole('heading', { name: 'Write one quarter' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Replay scene' }))
    expect(video.currentTime).toBe(24)
    expect(playMock).toHaveBeenCalledTimes(2)
  })

  it('shows render errors and no video controls when export fails', async () => {
    const user = userEvent.setup()
    const failed = {
      ...completedJob(),
      status: 'failed',
      duration_seconds: null,
      video_url: null,
      download_url: null,
      captions_url: null,
      manifest_url: null,
      error: 'Local narration or MP4 export failed. Check backend logs and retry.',
    }
    fetchMock
      .mockResolvedValueOnce(response(makeLesson()))
      .mockResolvedValueOnce(response({ ...failed, status: 'queued', error: null, manifest_url: null }))
      .mockResolvedValueOnce(response(failed))
    render(<App />)

    await user.click(screen.getByRole('button', { name: /create my lesson/i }))
    await screen.findByText('OLLAMA PLAN')
    await user.click(screen.getByRole('button', { name: /render narrated mp4/i }))

    expect((await screen.findAllByRole('alert'))[0]).toHaveTextContent(/MP4 export failed/i)
    expect(document.querySelector('video')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Download MP4' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry video render/i })).toBeEnabled()
  })

  it('does not expose playback or download controls for a completed job missing media URLs', async () => {
    const user = userEvent.setup()
    fetchMock
      .mockResolvedValueOnce(response(makeLesson()))
      .mockResolvedValueOnce(response({ ...completedJob(), video_url: null }))
    render(<App />)

    await user.click(screen.getByRole('button', { name: /create my lesson/i }))
    await screen.findByText('OLLAMA PLAN')
    await user.click(screen.getByRole('button', { name: /render narrated mp4/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid job status/i)
    expect(document.querySelector('video')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Download MP4' })).not.toBeInTheDocument()
  })
})

