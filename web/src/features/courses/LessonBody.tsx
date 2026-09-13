import { FileText, MessageCircle } from 'lucide-react'
import type { CourseLessonView } from '../../types/course'
import { LessonText } from './LessonText'

export type LessonBodyProps = {
  blocks: NonNullable<CourseLessonView['blocks']>
  helpDisabled: boolean
  onEvidence: (sourceRef: string) => void
  onExplain: (mode: 'explain' | 'example', blockIndex: number) => void
}
const blockLabels = { explanation: '讲解', example: '示例', reference: '资料说明', recap: '小结' }

export function LessonBody({ blocks, helpDisabled, onEvidence, onExplain }: LessonBodyProps) {
  return (
    <section className="card course-lesson-body" aria-label="本课正文">
      {blocks.map((block, index) => (
        <section className={`course-block course-block-${block.type}`} key={index}>
          <div className="section-line"><h3>{blockLabels[block.type]}</h3>
            {block.synthetic && <span className="badge">示意示例</span>}</div>
          <LessonText text={block.text} />
          {!!block.source_refs?.length && <div className="course-citations">
            {block.source_refs.map((ref, number) => <button type="button" key={ref} className="text-button"
              onClick={() => onEvidence(ref)} aria-label={`查看第 ${index + 1} 段依据 ${number + 1}`}>
              <FileText size={14} />原文依据 {number + 1}
            </button>)}
          </div>}
          <div className="course-block-help">
            <button type="button" className="text-button" disabled={helpDisabled}
              aria-label={`解释这一段（第 ${index + 1} 段）`} onClick={() => onExplain('explain', index)}>
              <MessageCircle size={14} />解释这一段</button>
            <button type="button" className="text-button" disabled={helpDisabled}
              aria-label={`换个例子（第 ${index + 1} 段）`} onClick={() => onExplain('example', index)}>换个例子</button>
          </div>
        </section>
      ))}
    </section>
  )
}
