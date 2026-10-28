import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { VisualLessonCanvas, type VisualScene } from './VisualLessonCanvas'

const loopScene: VisualScene = {
  title: 'Follow a Python loop',
  narration: 'Each list item gets one turn.',
  caption: 'A loop repeats for each item.',
  visual_type: 'code_execution',
  visual_data: {},
  execution_data: { variable_name: 'fruit', iterable_name: 'fruits', values: ['apple', 'pear', 'plum'] },
}

describe('visual lesson renderers', () => {
  it('renders a typed title card with the lesson topic and progress', () => {
    const { container } = render(<VisualLessonCanvas scene={{
      ...loopScene,
      visual_type: 'title_card',
      visual_data: { topic: 'How plants move water', subtitle: 'Follow water from roots to leaves.' },
      execution_data: null,
    }} progress={0.6} />)

    expect(screen.getByRole('img', { name: 'Lesson topic: How plants move water' })).toBeInTheDocument()
    expect(screen.getByText('Follow water from roots to leaves.')).toBeInTheDocument()
    expect(container.querySelector('.title-card-track span')).toHaveStyle({ width: '60%' })
  })

  it('shows the current loop value and accumulated output as progress advances', () => {
    const { rerender } = render(<VisualLessonCanvas scene={loopScene} progress={0.4} />)
    expect(screen.getByText('“pear”')).toBeInTheDocument()
    expect(screen.getByText('apple', { selector: '.execution-output li' })).toBeInTheDocument()
    expect(screen.getByText('Read item 2 of 3')).toBeInTheDocument()

    rerender(<VisualLessonCanvas scene={loopScene} progress={0.96} />)
    expect(screen.getByText('No values remain · loop stops')).toBeInTheDocument()
    expect(screen.getByText('plum', { selector: '.execution-output li' })).toBeInTheDocument()
  })

  it('renders non-code concepts and process data with the modular visual registry', () => {
    render(<VisualLessonCanvas scene={{
      ...loopScene,
      visual_type: 'concept_diagram',
      visual_data: { left: 'Seed', relationship: 'grows into', right: 'Plant' },
      execution_data: null,
    }} progress={0.8} />)
    expect(screen.getByRole('img', { name: 'Seed grows into Plant' })).toBeInTheDocument()
    expect(screen.getByText('Plant')).toBeInTheDocument()
  })

  it('walks legacy code line by line as progress advances', () => {
    const codeScene: VisualScene = {
      ...loopScene,
      visual_type: 'code',
      visual_data: { code: 'for i in range(3):\n    print(i)\nprint("done")' },
      execution_data: null,
    }
    const { rerender, container } = render(<VisualLessonCanvas scene={codeScene} progress={0.1} />)
    expect(container.querySelectorAll('.code-line.revealed')).toHaveLength(1)

    rerender(<VisualLessonCanvas scene={codeScene} progress={0.6} />)
    expect(container.querySelectorAll('.code-line.revealed').length).toBeGreaterThan(1)
    expect(container.querySelector('.code-line.is-active')).not.toBeNull()
  })

  it('moves the process-flow packet along the connectors with progress', () => {
    const flowScene: VisualScene = {
      ...loopScene,
      visual_type: 'process_flow',
      visual_data: { input: 'Observe', process: 'Understand', output: 'Explain' },
      execution_data: null,
    }
    const { rerender, container } = render(<VisualLessonCanvas scene={flowScene} progress={0.2} />)
    const packets = container.querySelectorAll('.flow-packet')
    expect(packets).toHaveLength(2)

    rerender(<VisualLessonCanvas scene={flowScene} progress={0.7} />)
    const moving = container.querySelector('.flow-packet') as HTMLElement
    expect(Number.parseInt(moving.style.left, 10)).toBeGreaterThan(0)
  })

  it('partitions a whole before shading the selected numerator', () => {
    const fractionScene: VisualScene = {
      ...loopScene,
      title: 'Shade three of four equal parts',
      visual_type: 'fraction_model',
      visual_data: {},
      execution_data: null,
      fraction_data: { numerator: 3, denominator: 4 },
    }
    const { container, rerender } = render(<VisualLessonCanvas scene={fractionScene} progress={0.6} />)

    expect(screen.getByRole('img', { name: '3 of 4 equal parts selected' })).toBeInTheDocument()
    expect(container.querySelectorAll('.fraction-cell')).toHaveLength(4)
    const fills = Array.from(container.querySelectorAll('.fraction-cell-fill')) as HTMLElement[]
    expect(Number.parseInt(fills[0].style.width, 10)).toBeGreaterThan(0)
    expect(fills[3].style.width).toBe('0%')
    expect(container.querySelector('.fraction-notation')).toHaveStyle({ opacity: '0' })

    rerender(<VisualLessonCanvas scene={fractionScene} progress={0.9} />)
    expect(screen.getByText('3 / 4')).toHaveStyle({ opacity: '1' })
  })

  it('moves inputs through a named mechanism before revealing outputs', () => {
    const causeEffectScene: VisualScene = {
      ...loopScene,
      title: 'Trace photosynthesis through a leaf',
      visual_type: 'cause_effect',
      visual_data: {},
      execution_data: null,
      cause_effect_data: {
        inputs: ['sunlight', 'water', 'carbon dioxide'],
        mechanism: 'chloroplasts in a leaf',
        outputs: ['glucose', 'oxygen'],
      },
    }
    const { container, rerender } = render(<VisualLessonCanvas scene={causeEffectScene} progress={0.2} />)
    expect(screen.getByRole('img', { name: /sunlight, water, carbon dioxide through chloroplasts in a leaf/ })).toBeInTheDocument()
    expect(container.querySelectorAll('circle')).toHaveLength(5)
    expect(container.querySelector('line')).toHaveAttribute('opacity', '0')

    rerender(<VisualLessonCanvas scene={causeEffectScene} progress={0.55} />)
    expect(container.querySelector('line')).toHaveAttribute('opacity', '1')
    expect(container.querySelectorAll('circle')[0]).toHaveAttribute('opacity', '1')
    expect(container.querySelector('rect[x="695"]')).toHaveAttribute('opacity', '0')

    rerender(<VisualLessonCanvas scene={causeEffectScene} progress={0.86} />)
    expect(container.querySelector('rect[x="695"]')).toHaveAttribute('opacity', '1')
  })
})
