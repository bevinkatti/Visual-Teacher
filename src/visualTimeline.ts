import type { CodeExecutionData, VisualState, VisualTimelineFrame } from './VisualLessonCanvas'

export function buildCodeExecutionTimeline(data: CodeExecutionData): VisualTimelineFrame[] {
  const count = data.values.length
  const readyEnd = 0.1
  const completeStart = 0.9
  const stepWidth = (completeStart - readyEnd) / count
  const frames: VisualTimelineFrame[] = [{
    start_progress: 0,
    end_progress: readyEnd,
    phase: 'ready',
    active_line: 1,
    iteration: 0,
    value: null,
    output: [],
    status: 'Ready to begin',
  }]
  data.values.forEach((value, index) => {
    const start = readyEnd + index * stepWidth
    const middle = start + stepWidth * 0.38
    const end = start + stepWidth
    frames.push({
      start_progress: start,
      end_progress: middle,
      phase: 'next_value',
      active_line: 1,
      iteration: index + 1,
      value,
      output: data.values.slice(0, index),
      status: `Read item ${index + 1} of ${count}`,
    }, {
      start_progress: middle,
      end_progress: end,
      phase: 'run_body',
      active_line: 2,
      iteration: index + 1,
      value,
      output: data.values.slice(0, index + 1),
      status: `Print ${value}`,
    })
  })
  frames.push({
    start_progress: completeStart,
    end_progress: 1,
    phase: 'complete',
    active_line: 1,
    iteration: count,
    value: null,
    output: data.values,
    status: 'No values remain · loop stops',
  })
  return frames
}

export function visualStateAtProgress(frames: VisualTimelineFrame[], progress: number): VisualState | null {
  if (frames.length === 0) return null
  const bounded = Math.max(0, Math.min(1, progress))
  return frames.find((frame) => bounded < frame.end_progress) ?? frames[frames.length - 1]
}
