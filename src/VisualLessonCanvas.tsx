import type { ReactNode } from 'react'
import { buildCodeExecutionTimeline, visualStateAtProgress } from './visualTimeline'

export type VisualType = 'title_card' | 'flow' | 'code' | 'concept' | 'concept_diagram' | 'process_flow' | 'code_execution' | 'fraction_model' | 'cause_effect' | 'number_line' | 'equation_steps' | 'cycle'

export type CodeExecutionData = {
  variable_name: string
  iterable_name: string
  values: string[]
}

export type FractionModelData = { numerator: number; denominator: number }
export type CauseEffectData = { inputs: string[]; mechanism: string; outputs: string[] }
export type NumberLineData = { start_value: number; jumps: number[]; operation_labels: string[]; result: number }
export type EquationStepsData = { equations: string[]; operations: string[] }
export type CycleData = { center_label: string; stages: string[] }

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
  fraction_data?: FractionModelData | null
  cause_effect_data?: CauseEffectData | null
  number_line_data?: NumberLineData | null
  equation_steps_data?: EquationStepsData | null
  cycle_data?: CycleData | null
}

export type VisualState = VisualTimelineFrame

const preferredFlowKeys = ['input', 'process', 'step_2', 'step_3', 'output']

function segment(progress: number, start: number, end: number) {
  return Math.max(0, Math.min(1, (progress - start) / Math.max(0.000001, end - start)))
}

function easeOutCubic(value: number) {
  const bounded = Math.max(0, Math.min(1, value))
  return 1 - (1 - bounded) ** 3
}

function getVisualState(scene: VisualScene, progress: number, timeline?: VisualTimelineFrame[]) {
  if (scene.visual_type !== 'code_execution' || !scene.execution_data) return null
  const frames = timeline?.length ? timeline : buildCodeExecutionTimeline(scene.execution_data)
  return visualStateAtProgress(frames, progress)
}

function TitleCard({ scene, progress }: { scene: VisualScene; progress: number }) {
  const topic = scene.visual_data.topic ?? scene.title
  const subtitle = scene.visual_data.subtitle ?? scene.caption
  const boundedProgress = Math.min(1, Math.max(0, progress))

  return (
    <div className="title-card" role="img" aria-label={`Lesson topic: ${topic}`}>
      <span className="title-card-kicker">TODAY'S TOPIC</span>
      <h4>{topic}</h4>
      <p>{subtitle}</p>
      <div className="title-card-track" aria-hidden="true">
        <span style={{ width: `${Math.round(boundedProgress * 100)}%` }} />
      </div>
    </div>
  )
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
  // The packet position mirrors the exported video: one global head moving
  // across the steps, filling each connector in turn.
  const head = Math.min(entries.length - 1, Math.max(0, (progress - 0.08) / 0.86) * (entries.length - 1))
  const boundedHead = Math.max(0, Math.min(entries.length - 1, head))

  return (
    <ol className="process-flow" aria-label="Progressive lesson steps">
      {entries.map(([key, value], index) => (
        <li
          className={`process-step ${index <= active ? 'revealed' : ''} ${index === active ? 'active' : ''}`}
          key={key}
        >
          <span className="process-step-number">{String(index + 1).padStart(2, '0')}</span>
          <span className="process-step-label">{key.replace(/_/g, ' ')}</span>
          <strong>{value}</strong>
          {index < entries.length - 1 && (
            <span className="flow-connector" aria-hidden="true">
              <span
                className={`flow-packet ${boundedHead > index && boundedHead < index + 1 ? 'moving' : ''}`}
                style={{ left: `${Math.round(Math.max(0, Math.min(1, boundedHead - index)) * 100)}%` }}
              />
            </span>
          )}
        </li>
      ))}
    </ol>
  )
}

function FractionModel({ scene, progress }: { scene: VisualScene; progress: number }) {
  const data = scene.fraction_data
  if (!data) return <ConceptDiagram scene={scene} progress={progress} />
  const reveal = segment(progress, 0.08, 0.2)
  const perPart = 0.44 / data.numerator

  return (
    <div className="fraction-model" role="img" aria-label={`${data.numerator} of ${data.denominator} equal parts selected`}>
      <div className="fraction-area" style={{ opacity: reveal, gridTemplateColumns: `repeat(${data.denominator}, minmax(0, 1fr))` }}>
        {Array.from({ length: data.denominator }, (_, index) => {
          const fill = index < data.numerator ? segment(progress, 0.25 + index * perPart, 0.25 + (index + 1) * perPart) : 0
          return <span className="fraction-cell" key={index}>
            <span className="fraction-cell-fill" style={{ width: `${Math.round(fill * 100)}%` }} />
          </span>
        })}
      </div>
      <strong className="fraction-notation" style={{ opacity: segment(progress, 0.73, 0.84) }}>
        {data.numerator} / {data.denominator}
      </strong>
    </div>
  )
}

function NumberLine({ scene, progress }: { scene: VisualScene; progress: number }) {
  const data = scene.number_line_data
  if (!data) return <ConceptDiagram scene={scene} progress={progress} />
  const positions = [data.start_value]
  for (const jump of data.jumps) positions.push(positions[positions.length - 1] + jump)
  let low = Math.max(-20, Math.min(...positions) - 1)
  let high = Math.min(20, Math.max(...positions) + 1)
  if (high - low < 4) {
    const center = Math.round((low + high) / 2)
    low = Math.max(-20, Math.min(low, center - 2))
    high = Math.min(20, Math.max(high, center + 2))
  }
  const xFor = (value: number) => 88 + (value - low) * 824 / Math.max(1, high - low)
  const axisY = 290
  let markerValue = data.start_value
  const jumps = data.jumps.map((_, index) => {
    const start = positions[index]
    const end = positions[index + 1]
    const begin = 0.18 + index * 0.16
    const t = easeOutCubic(segment(progress, begin, begin + 0.15))
    if (t > 0) markerValue = start + (end - start) * t
    const direction = end >= start ? 1 : -1
    const controlY = axisY - direction * (44 + Math.min(36, Math.abs(end - start) * 5.9))
    const x1 = xFor(start)
    const x2 = xFor(end)
    const markerY = (1 - t) ** 2 * axisY + 2 * (1 - t) * t * controlY + t ** 2 * axisY
    return { start, end, begin, t, controlY, x1, x2, markerY, markerX: x1 + (x2 - x1) * t, label: data.operation_labels[index] }
  })
  let activeJump = jumps.find((jump) => jump.t < 1 && progress >= jump.begin) ?? null
  if (progress < 0.18) markerValue = data.start_value
  if (!activeJump && jumps.every((jump) => jump.t >= 1)) markerValue = data.result
  const markerX = xFor(markerValue)
  const resultReveal = segment(progress, 0.84, 0.94)
  const labelStep = Math.max(1, Math.ceil((high - low) / 24))

  return (
    <div className="number-line-visual" role="img" aria-label={`Number line: start at ${data.start_value}, apply ${data.operation_labels.join(', ')}, and reach ${data.result}`}>
      <svg viewBox="0 0 1000 550" aria-hidden="true" preserveAspectRatio="none">
        <line x1="88" y1={axisY} x2="912" y2={axisY} stroke="#8a9bb2" strokeWidth="3" opacity={segment(progress, 0.06, 0.18)} />
        {Array.from({ length: high - low + 1 }, (_, index) => low + index).map((value) => {
          const x = xFor(value)
          const labeled = value % labelStep === 0 || positions.includes(value)
          return <g key={value} opacity={segment(progress, 0.06, 0.18)}>
            <line x1={x} y1={axisY - 15} x2={x} y2={axisY + 15} stroke="#8a9bb2" strokeWidth="2" />
            {labeled && <text x={x} y={axisY + 65} textAnchor="middle" className="number-line-tick">{value}</text>}
          </g>
        })}
        {jumps.map((jump, index) => {
          if (progress < jump.begin) return null
          const midpoint = (jump.x1 + jump.x2) / 2
          const labelOpacity = segment(progress, jump.begin + 0.04, jump.begin + 0.18)
          return <g key={`${jump.start}-${jump.end}-${index}`}>
            <path d={`M ${jump.x1} ${axisY} Q ${midpoint} ${jump.controlY} ${jump.x2} ${axisY}`} pathLength="1" stroke={index % 2 ? '#647da8' : '#3157a4'} strokeWidth="4" fill="none" strokeDasharray="1" strokeDashoffset={1 - jump.t} />
            {jump.t >= 0.98 && <path d="M 0 0 L -11 -5 L -11 5 Z" transform={`translate(${jump.x2} ${axisY}) rotate(${Math.atan2(axisY - jump.controlY, jump.x2 - (jump.x1 + jump.x2) / 2) * 180 / Math.PI})`} fill="#3157a4" />}
            <text x={midpoint} y={jump.controlY - 17} textAnchor="middle" className="number-line-operation" opacity={labelOpacity}>{jump.label}</text>
          </g>
        })}
        {activeJump && <circle cx={activeJump.markerX} cy={activeJump.markerY} r="7" fill="#3157a4" stroke="#fff" strokeWidth="2" />}
        {!activeJump && <circle cx={markerX} cy={axisY} r="7" fill="#3157a4" stroke="#fff" strokeWidth="2" opacity={segment(progress, 0.14, 0.28)} />}
        <g opacity={resultReveal}>
          <rect x="355" y="421" width="290" height="95" rx="9" fill="#edf2f9" stroke="#a7b8d0" strokeWidth="2" />
          <text x="500" y="482" textAnchor="middle" className="number-line-result">Result: {data.result}</text>
        </g>
      </svg>
    </div>
  )
}

function EquationSteps({ scene, progress }: { scene: VisualScene; progress: number }) {
  const data = scene.equation_steps_data
  if (!data) return <ConceptDiagram scene={scene} progress={progress} />
  return (
    <div className="equation-steps-visual" role="img" aria-label={`Equation transformation: ${data.equations.join('; ')}`}>
      <svg viewBox="0 0 1000 550" aria-hidden="true" preserveAspectRatio="none">
        {data.equations.map((equation, index) => {
          const begin = 0.08 + index * 0.16
          const reveal = easeOutCubic(segment(progress, begin, begin + 0.14))
          const y = 24 + index * 96
          const equationFontSize = Math.max(13, Math.min(32, 430 / Math.max(1, equation.length * 0.58)))
          const operationReveal = segment(progress, begin + 0.09, begin + 0.20)
          return <g key={`${index}-${equation}`} opacity={reveal}>
            {index < data.equations.length - 1 && <g opacity={segment(progress, begin + 0.1, begin + 0.22)}>
              <path d={`M 140 ${y + 72} V ${y + 90} L 135 ${y + 84} M 140 ${y + 90} L 145 ${y + 84}`} fill="none" stroke="#7185a6" strokeWidth="3" />
            </g>}
            <rect x="160" y={y} width="440" height="72" rx="8" fill={index === 0 ? '#edf2f9' : '#f2f5f8'} stroke={index === 0 ? '#a7b8d0' : '#c7d2df'} strokeWidth="2" />
            <text x="380" y={y + 45} textAnchor="middle" className="equation-step-expression" style={{ fontSize: `${equationFontSize}px` }}>{equation}</text>
            {index < data.operations.length && <g opacity={operationReveal}>
              <rect x="635" y={y} width="305" height="72" rx="8" fill="#f5f6f7" stroke="#cbd4df" strokeWidth="1" />
              <text x="787" y={y + 39 - (wrappedLabel(data.operations[index], 22).length - 1) * 12} textAnchor="middle" className="equation-step-operation">
                {wrappedLabel(data.operations[index], 22).map((line, lineIndex) => <tspan key={lineIndex} x="787" dy={lineIndex === 0 ? 0 : 24}>{line}</tspan>)}
              </text>
            </g>}
          </g>
        })}
      </svg>
    </div>
  )
}

function Cycle({ scene, progress }: { scene: VisualScene; progress: number }) {
  const data = scene.cycle_data
  if (!data) return <ConceptDiagram scene={scene} progress={progress} />
  const centerX = 500
  const centerY = 250
  const radiusX = 380
  const radiusY = 128
  const nodeWidth = 198
  const nodeHeight = 60
  const centers = data.stages.map((_, index) => {
    const angle = -Math.PI / 2 + Math.PI * 2 * index / data.stages.length
    return { x: centerX + radiusX * Math.cos(angle), y: centerY + radiusY * Math.sin(angle) }
  })
  return (
    <div className="cycle-visual" role="img" aria-label={`${data.center_label} cycle: ${data.stages.join(', ')}`}>
      <svg viewBox="0 0 1000 500" aria-hidden="true" preserveAspectRatio="none">
        {centers.map((source, index) => {
          const begin = 0.18 + index * (0.58 / centers.length)
          const reveal = easeOutCubic(segment(progress, begin, begin + 0.12))
          if (reveal <= 0) return null
          const target = centers[(index + 1) % centers.length]
          const angle = Math.atan2(target.y - source.y, target.x - source.x)
          const x1 = source.x + (nodeWidth / 2 - 10) * Math.cos(angle)
          const y1 = source.y + (nodeHeight / 2 - 7) * Math.sin(angle)
          const x2 = target.x - (nodeWidth / 2 - 12) * Math.cos(angle)
          const y2 = target.y - (nodeHeight / 2 - 9) * Math.sin(angle)
          const headX = x1 + (x2 - x1) * reveal
          const headY = y1 + (y2 - y1) * reveal
          return <g key={`edge-${index}`}>
            <line x1={x1} y1={y1} x2={headX} y2={headY} stroke="#647da8" strokeWidth="3" />
            {reveal >= 0.95 && <path d={`M ${x2 - 9 * Math.cos(angle - .55)} ${y2 - 9 * Math.sin(angle - .55)} L ${x2} ${y2} L ${x2 - 9 * Math.cos(angle + .55)} ${y2 - 9 * Math.sin(angle + .55)} Z`} fill="#3157a4" />}
          </g>
        })}
        {centers.map((center, index) => {
          const begin = 0.08 + index * 0.10
          const reveal = easeOutCubic(segment(progress, begin, begin + 0.15))
          const lines = wrappedLabel(data.stages[index], 15)
          const labelSize = lines.length > 2 ? 22 : 28
          return <g key={`stage-${index}`} opacity={reveal}>
            <rect x={center.x - nodeWidth / 2} y={center.y - nodeHeight / 2} width={nodeWidth} height={nodeHeight} rx="10" fill="#f1f4f8" stroke={index % 2 === 0 ? '#9caec8' : '#b4c0d1'} strokeWidth="2" />
            <text x={center.x} y={center.y + 5 - (lines.length - 1) * labelSize * 0.55} textAnchor="middle" className="cycle-stage-label" style={{ fontSize: `${labelSize}px` }}>
              {lines.map((line, lineIndex) => <tspan key={lineIndex} x={center.x} dy={lineIndex === 0 ? 0 : labelSize * 1.1}>{line}</tspan>)}
            </text>
          </g>
        })}
        <g opacity={segment(progress, 0.14, 0.30)}>
          <rect x="350" y="216" width="300" height="68" rx="12" fill="#fff" stroke="#b7c4d6" strokeWidth="2" />
          <text x="500" y="256" textAnchor="middle" className="cycle-center-label">{data.center_label}</text>
        </g>
      </svg>
    </div>
  )
}

function wrappedLabel(label: string, maximum: number) {
  const lines: string[] = []
  let current = ''
  for (const word of label.split(/\s+/)) {
    if (current && current.length + word.length + 1 > maximum) {
      lines.push(current)
      current = word
    } else {
      current = current ? `${current} ${word}` : word
    }
  }
  if (current) lines.push(current)
  return lines.slice(0, 3)
}

function CauseEffect({ scene, progress }: { scene: VisualScene; progress: number }) {
  const data = scene.cause_effect_data
  if (!data) return <ConceptDiagram scene={scene} progress={progress} />
  const nodeHeight = 58
  const nodeGap = 14
  const inputHeight = data.inputs.length * nodeHeight + (data.inputs.length - 1) * nodeGap
  const outputHeight = data.outputs.length * nodeHeight + (data.outputs.length - 1) * nodeGap
  const inputStart = 250 - inputHeight / 2
  const outputStart = 250 - outputHeight / 2
  const mechanism = { x: 385, y: 185, width: 230, height: 130 }
  const mechanismReveal = segment(progress, 0.27, 0.4)
  const incoming = segment(progress, 0.38, 0.65)
  const outgoing = segment(progress, 0.65, 0.84)

  return (
    <div className="cause-effect" role="img" aria-label={`${data.inputs.join(', ')} through ${data.mechanism} produces ${data.outputs.join(', ')}`}>
      <svg viewBox="0 0 1000 500" aria-hidden="true" preserveAspectRatio="none">
        {data.inputs.map((label, index) => {
          const y = inputStart + index * (nodeHeight + nodeGap)
          const startY = y + nodeHeight / 2
          const x = 310 + (385 - 310) * incoming
          const py = startY + (250 - startY) * incoming
          const reveal = segment(progress, 0.08 + index * 0.075, 0.24 + index * 0.075)
          return <g key={`in-${index}`}>
            <line x1="310" y1={startY} x2={mechanism.x} y2="250" stroke="#254363" strokeWidth="4" opacity={mechanismReveal} />
            {incoming > 0 && <line x1="310" y1={startY} x2={x} y2={py} stroke="#41d0e1" strokeWidth="4" opacity={incoming} />}
            <circle cx={x} cy={py} r="6" fill="#f1f7ff" opacity={incoming > 0 ? 1 : 0} />
            <rect x="54" y={y} width="256" height={nodeHeight} rx="13" fill="#0d2642" stroke="#3e80ff" strokeWidth="2" opacity={reveal} />
            <text x="182" y={startY} className="cause-effect-label" opacity={reveal}>
              {wrappedLabel(label, 17).map((line, lineIndex) => <tspan key={lineIndex} x="182" dy={lineIndex === 0 ? `${-(wrappedLabel(label, 17).length - 1) * 24}` : '24'}>{line}</tspan>)}
            </text>
          </g>
        })}
        {data.outputs.map((label, index) => {
          const y = outputStart + index * (nodeHeight + nodeGap)
          const endY = y + nodeHeight / 2
          const x = 615 + (695 - 615) * outgoing
          const py = 250 + (endY - 250) * outgoing
          const reveal = segment(progress, 0.66 + index * 0.08, 0.81 + index * 0.08)
          return <g key={`out-${index}`}>
            <line x1={mechanism.x + mechanism.width} y1="250" x2="695" y2={endY} stroke="#254363" strokeWidth="4" opacity={mechanismReveal} />
            {outgoing > 0 && <line x1={mechanism.x + mechanism.width} y1="250" x2={x} y2={py} stroke="#f3be63" strokeWidth="4" opacity={outgoing} />}
            <circle cx={x} cy={py} r="6" fill="#f1f7ff" opacity={outgoing > 0 ? 1 : 0} />
            <rect x="695" y={y} width="256" height={nodeHeight} rx="13" fill="#30291b" stroke={index % 2 ? '#56dbac' : '#f3be63'} strokeWidth="2" opacity={reveal} />
            <text x="823" y={endY} className="cause-effect-label" opacity={reveal}>
              {wrappedLabel(label, 17).map((line, lineIndex) => <tspan key={lineIndex} x="823" dy={lineIndex === 0 ? `${-(wrappedLabel(label, 17).length - 1) * 24}` : '24'}>{line}</tspan>)}
            </text>
          </g>
        })}
        <rect x={mechanism.x} y={mechanism.y} width={mechanism.width} height={mechanism.height} rx="16" fill="#0d3044" stroke="#41d0e1" strokeWidth="3" opacity={mechanismReveal} />
        <text x="500" y="250" className="cause-effect-label cause-effect-mechanism" opacity={mechanismReveal}>
          {wrappedLabel(data.mechanism, 17).map((line, lineIndex) => <tspan key={lineIndex} x="500" dy={lineIndex === 0 ? `${-(wrappedLabel(data.mechanism, 17).length - 1) * 28}` : '28'}>{line}</tspan>)}
        </text>
      </svg>
    </div>
  )
}

function LegacyCode({ scene, progress = 0 }: { scene: VisualScene; progress?: number }) {
  const code = scene.visual_data.code ?? Object.entries(scene.visual_data).map(([key, value]) => `${key}: ${value}`).join('\n')
  const lines = code.split('\n').slice(0, 6)
  // Progressive line-by-line walkthrough mirrors the exported MP4 renderer.
  const bounded = Math.min(1, Math.max(0, progress))
  const revealedCount = Math.max(1, Math.ceil(((bounded - 0.05) / 0.35) * lines.length))
  const activeLine = Math.min(lines.length - 1, Math.floor(((bounded - 0.05) / 0.35) * lines.length))
  return (
    <div className="legacy-code" aria-label="Code walkthrough, displayed without running">
      <div className="visual-kicker">CODE · DISPLAY ONLY</div>
      <pre>
        {lines.map((line, index) => (
          <span
            className={`code-line ${index < revealedCount ? 'revealed' : ''} ${index === activeLine && bounded > 0.3 ? 'is-active' : ''}`}
            key={`${index}-${line}`}
          >
            <span className="code-line-number">{String(index + 1).padStart(2, '0')}</span>
            {index < revealedCount ? line : ''}
          </span>
        ))}
      </pre>
    </div>
  )
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
  if (!data) return <LegacyCode scene={scene} progress={progress} />
  const state = getVisualState(scene, progress, timeline)
  if (!state) return <LegacyCode scene={scene} progress={progress} />
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
  title_card: ({ scene, progress }) => <TitleCard scene={scene} progress={progress} />,
  concept: ({ scene, progress }) => <ConceptDiagram scene={scene} progress={progress} />,
  concept_diagram: ({ scene, progress }) => <ConceptDiagram scene={scene} progress={progress} />,
  flow: ({ scene, progress }) => <ProcessFlow scene={scene} progress={progress} />,
  process_flow: ({ scene, progress }) => <ProcessFlow scene={scene} progress={progress} />,
  code: ({ scene, progress }) => <LegacyCode scene={scene} progress={progress} />,
  code_execution: ({ scene, progress, timeline }) => <CodeExecution scene={scene} progress={progress} timeline={timeline} />,
  fraction_model: ({ scene, progress }) => <FractionModel scene={scene} progress={progress} />,
  cause_effect: ({ scene, progress }) => <CauseEffect scene={scene} progress={progress} />,
  number_line: ({ scene, progress }) => <NumberLine scene={scene} progress={progress} />,
  equation_steps: ({ scene, progress }) => <EquationSteps scene={scene} progress={progress} />,
  cycle: ({ scene, progress }) => <Cycle scene={scene} progress={progress} />,
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
  const key = scene.visual_type === 'code_execution' && !scene.execution_data ? 'code'
    : scene.visual_type === 'fraction_model' && !scene.fraction_data ? 'concept_diagram'
      : scene.visual_type === 'cause_effect' && !scene.cause_effect_data ? 'concept_diagram'
        : scene.visual_type === 'number_line' && !scene.number_line_data ? 'concept_diagram'
          : scene.visual_type === 'equation_steps' && !scene.equation_steps_data ? 'concept_diagram'
            : scene.visual_type === 'cycle' && !scene.cycle_data ? 'concept_diagram'
              : scene.visual_type
  const RendererComponent = visualRenderers[key] ?? visualRenderers.concept_diagram
  return <div className="visual-frame">{RendererComponent({ scene, progress, timeline })}</div>
}
