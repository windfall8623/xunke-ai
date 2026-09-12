import { describe, expect, it } from 'vitest'
import { buildGoldSpan, parseSamples } from './dataset'
import type { SourceExcerpt } from '../../types/evaluation'

describe('controlled annotation input', () => {
  it('reads JSONL into distinct samples and rejects duplicate sample IDs', () => {
    expect(
      parseSamples(
        '{"sample_id":"s1","case_type":"retrieval"}\n{"sample_id":"s2","case_type":"quiz"}',
      ),
    ).toHaveLength(2)
    expect(() => parseSamples('[{"sample_id":"s1"},{"sample_id":"s1"}]')).toThrow('sample_id')
  })
  it('rejects a non-array JSON value instead of treating it as sample data', () => {
    expect(() => parseSamples('{"unexpected":true}')).toThrow('sample_id')
  })
  it('keeps server Unicode code point offsets for text containing a surrogate pair', () => {
    const source: SourceExcerpt = {
      doc_id: 'd1',
      version_id: 'v1',
      parse_artifact_id: 'p1',
      canonical_text_hash: 'canon',
      source_sha256: 'source',
      block_id: 'b1',
      excerpt: '😀中',
      locator: {
        block_id: 'b1',
        section_id: 'section1',
        kind: 'paragraph',
        start_char: 1,
        end_char: 3,
        quote_hash: 'quote',
      },
      blocks: [],
      sections: [],
    }
    expect(buildGoldSpan(source)).toEqual({
      doc_id: 'd1',
      source_version_id: 'v1',
      parse_artifact_id: 'p1',
      canonical_text_hash: 'canon',
      block_id: 'b1',
      start_char: 1,
      end_char: 3,
      quote_hash: 'quote',
    })
  })
  it('refuses to invent a hash or location absent from the authorized excerpt', () => {
    expect(() =>
      buildGoldSpan({
        doc_id: 'd1',
        version_id: 'v1',
        parse_artifact_id: 'p1',
        canonical_text_hash: 'canon',
        block_id: 'b1',
        excerpt: '原文',
        locator: {},
      } as unknown as SourceExcerpt),
    ).toThrow('定位')
  })
})
