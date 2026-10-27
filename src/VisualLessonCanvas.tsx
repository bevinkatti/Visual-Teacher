import type { ReactNode } from 'react'
import { buildCodeExecutionTimeline, visualStateAtProgress } from './visualTimeline'

export type VisualType = 'flow' | 'code' | 'concept' | 'concept_diagram' | 'process_flow' | 'code_execution'

export type CodeExecutionData = {
  variable_name: string
  iterable_name: string
  values: string[]
}

export type VisualTimelineFrame = {
  start_progress: number
  end_progress: number
  phase: string
  active_line: number
  iteration: number
  value: string | null
  output: string[]
  status: string
}

export type VisualScene = {
  title: string
  narration: string
  caption: string
  visual_type: VisualType
  visual_data: Record<string, string>
  execution_data?: CodeExecutionData | null
}

export type VisualState = VisualTimelineFrame

const preferredFlowKeys = ['input', 'process', 'step_2', 'step_3', 'output']

function getVisualState(scene: VisualScene, progress: number, timeline?: VisualTimelineFrame[]) {
  if (scene.visual_type !== 'code_execution' || !scene.execution_data) return null
  const frames = timeline?.length ? timeline : buildCodeExecutionTimeline(scene.execution_data)
  return visualStateAtProgress(frames, progress)
}

function ConceptDiagram({ scene, progress }: { scene: VisualScene; progress: number }) {
  const entries = Object.entries(scene.visual_data)
  const left = scene.visual_data.left ?? entries[0]?.[1] ?? 'Starting idea'
  const relation = scene.visual_data.relationship ?? scene.visual_data.process ?? 'connects to'
  const right = scene.visual_data.right ?? scene.visual_data.output ?? entries[1]?.[1] ?? 'Result'
  const activeCount = Math.min(3, Math.max(1, Math.floor(progress * 3) + 1))
  const nodes = [
    { label: 'INPUT', value: left, tone: 'blue' },
    { label: 'RELATIONSHIP', value: relation, tone: 'cyan' },
    { label: 'RESULT', value: right, tone: 'gold' },
  ]

  return (
    <div className="concept-diagram" role="img" aria-label={`${left} ${relation} ${right}`}>
      <svg className="concept-connectors" viewBox="0 0 1000 240" aria-hidden="true" preserveAspectRatio="none">
        <defs><marker id="concept-arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0 0L9 4.5L0 9Z" /></marker></defs>
        <path className={activeCount > 1 ? 'connector-lit' : ''} d="M294 120H392" markerEnd="url(#concept-arrow)" />
        <path className={activeCount > 2 ? 'connector-lit' : ''} d="M608 120H706" markerEnd="url(#concept-arrow)" />
      </svg>
      {nodes.map((node, index) => (
        <div key={node.label} className={`diagram-node diagram-node-${node.tone} ${index < activeCount ? 'revealed' : ''}`}>
          <span>{node.label}</span><strong>{node.value}</strong>
        </div>
      ))}
    </div>
  )
}

function ProcessFlow({ scene, progress }: { scene: VisualScene; progress: number }) {
  const data = scene.visual_data
  let entries = preferredFlowKeys.filter((key) => data[key]).map((key) => [key, data[key]] as const)
  if (entries.length < 2) entries = Object.entries(data).slice(0, 4)
  entries = entries.slice(0, 4)
  if (entries.length === 0) entries = [['observe', 'Observe'], ['result', 'Understand']]
  const active = Math.min(entries.length - 1, Math.floor(progress * entries.length))

  return (
    <ol className="process-flow" aria-label="Progressive lesson steps">
      {entries.map(([key, value], index) => (
        <li className={`process-step ${index <= active ? 'revealed' : ''} ${index === active ? 'active' : ''}`} key={key}>
          <span className="process-step-number">{String(index + 1).padStart(2, '0')}</span>
          <span className="process-step-label">{key.replace(/_/g, ' ')}</span>
          <strong>{value}</strong>
        </li>
      ))}
    </ol>
  )
}

function LegacyCode({ scene }: { scene: VisualScene }) {
  const code = scene.visual_data.code ?? Object.entries(scene.visual_data).map(([key, value]) => `${key}: ${value}`).join('\n')
  return <div className="legacy-code"><div className="visual-kicker">CODE · DISPLAY ONLY</div><pre>{code}</pre></div>
}

function CodeExecution({
  scene,
  progress,
  timeline,
}: {
  scene: VisualScene
  progress: number
  timeline?: VisualTimelineFrame[]
}) {
  const data = scene.execution_data
  if (!data) return <LegacyCode scene={scene} />
  const state = getVisualState(scene, progress, timeline)
  if (!state) return <LegacyCode scene={scene} />
  const lines = [
    `for ${data.variable_name} in ${data.iterable_name}:`,
    `    print(${data.variable_name})`,
  ]

  return (
    <div className="code-execution" aria-label="Python loop execution, displayed without running code">
      <section className="code-window" aria-label="Python code example">
        <div className="code-window-top"><span /><span /><span /><b>PYTHON · DISPLAY ONLY</b></div>
        {lines.map((line, index) => {
          const number = index + 1
          return <div className={`code-line ${state.active_line === number ? 'is-active' : ''}`} key={line}>
            <span>{String(number).padStart(2, '0')}</span><code>{line}</code>
          </div>
        })}
        <div className="code-input-values"><span>{data.iterable_name}</span><strong>[ {data.values.join(' · ')} ]</strong></div>
      </section>
      <section className="execution-state" aria-live="polite" aria-label="Current loop state">
        <div className="execution-metrics">
          <div><span>ITERATION</span><strong>{state.iteration}<small> / {data.values.length}</small></strong></div>
          <div><span>{data.variable_name}</span><strong className="execution-variable">{state.value === null ? '—' : `“${state.value}”`}</strong></div>
        </div>
        <div className="execution-output-label"><span>OUTPUT</span><code>print({data.variable_name})</code></div>
        <ol className="execution-output" aria-label="Output so far">
          {state.output.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}
          {state.output.length === 0 && <li className="output-empty">Nothing printed yet</li>}
        </ol>
        <div className={`execution-status ${state.phase === 'complete' ? 'is-complete' : ''}`}>
          <span className="execution-status-dot" />{state.status}
        </div>
      </section>
    </div>
  )
}

type RendererProps = { scene: VisualScene; progress: number; timeline?: VisualTimelineFrame[] }
type Renderer = (props: RendererProps) => ReactNode

const visualRenderers: Record<string, Renderer> = {
  concept: ({ scene, progress }) => <ConceptDiagram scene={scene} progress={progress} />,
  concept_diagram: ({ scene, progress }) => <ConceptDiagram scene={scene} progress={progress} />,
  flow: ({ scene, progress }) => <ProcessFlow scene={scene} progress={progress} />,
  process_flow: ({ scene, progress }) => <ProcessFlow scene={scene} progress={progress} />,
  code: ({ scene }) => <LegacyCode scene={scene} />,
  code_execution: ({ scene, progress, timeline }) => <CodeExecution scene={scene} progress={progress} timeline={timeline} />,
}

export function VisualLessonCanvas({
  scene,
  progress = 0,
  timeline,
}: {
  scene: VisualScene
  progress?: number
  timeline?: VisualTimelineFrame[]
}) {
  const key = scene.visual_type === 'code_execution' && !scene.execution_data ? 'code' : scene.visual_type
  const RendererComponent = visualRenderers[key] ?? visualRenderers.concept_diagram
  return <div className="visual-frame">{RendererComponent({ scene, progress, timeline })}</div>
}
