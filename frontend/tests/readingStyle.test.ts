import test from 'node:test';
import assert from 'node:assert/strict';
import { readingStyleLabel } from '../src/readingStyle.ts';

test('only explicitly frozen tutor plans get the learning label', () => {
  assert.equal(readingStyleLabel({ reading_style: 'learning-tutor-v1', workflow: 'whole-paper-topics-v1', stages: [] }), '学习式全文精读');
  assert.equal(readingStyleLabel({ reading_style: 'original', workflow: 'whole-paper-topics-v1', stages: [] }), '全文主题精读（原规则）');
  assert.equal(readingStyleLabel({ stages: [{ kind: 'index' }, { kind: 'concept' }] }), '全文主题精读（原规则）');
  assert.equal(readingStyleLabel({ workflow: 'legacy-page-batches', stages: [] }), '旧版分段精读');
  assert.equal(readingStyleLabel({ stages: [{ kind: 'detail' }] }), '旧版分段精读');
});
