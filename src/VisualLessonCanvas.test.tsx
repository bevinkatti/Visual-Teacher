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
})
