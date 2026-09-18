import type { DocumentItem, SelectedDocument, SourceExcerpt } from '../../types/api'

export const previewSelectionKey = (selection: SelectedDocument) =>
  JSON.stringify([selection.doc_id, [...(selection.section_ids || [])].sort(), selection.section_catalog_revision || null])

export function sourceMatchesDocument(source: SourceExcerpt, document: DocumentItem) {
  return source.doc_id === document.doc_id &&
    source.version_id === document.active_version_id &&
    source.parse_artifact_id === document.section_catalog_revision
}

export function selectedPreviewBlocks(source: SourceExcerpt, selection: SelectedDocument) {
  const ids = new Set(selection.section_ids || [])
  const ranges = source.sections.filter((section) => ids.has(section.section_id))
  return source.blocks.filter((block) => !ids.size || ranges.some((section) =>
    section.start_char <= block.start_char && block.end_char <= section.end_char))
}

export function selectedPreviewSections(source: SourceExcerpt, selection: SelectedDocument) {
  const ids = new Set(selection.section_ids || [])
  const ranges = source.sections.filter((section) => ids.has(section.section_id))
  return source.sections.filter((section) => !ids.size || ranges.some((parent) =>
    parent.start_char <= section.start_char && section.end_char <= parent.end_char))
}

export function identifiedPreviewPages(source: SourceExcerpt, selection: SelectedDocument) {
  return [...new Set(selectedPreviewBlocks(source, selection).flatMap((block) =>
    block.page == null ? [] : [block.page]))].sort((a, b) => a - b)
}
