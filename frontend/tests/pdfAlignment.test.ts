import assert from 'node:assert/strict';
import test from 'node:test';
import { matchSourceRanges, normalizedText } from '../src/pdfAlignment.ts';

test('normalized offsets survive ligatures, wrapped hyphens, unicode and punctuation', () => {
  const source = 'Efficient “ﬁne” infer-\nence with DNNs.';
  const text = 'Header EFFICIENT "fine" inference with DNNs. footer';
  const [range] = matchSourceRanges(text, source);
  assert.equal(text.slice(range.start, range.end), 'EFFICIENT "fine" inference with DNNs.');
  const ligature = matchSourceRanges('A ﬁnal result.', 'final result.')[0];
  assert.equal('A ﬁnal result.'.slice(ligature.start, ligature.end), 'ﬁnal result.');
});

test('split PDF text items are matched independent of whitespace', () => {
  assert.equal(matchSourceRanges('Weminimizelatencyunderresourceconstraints.', 'We minimize latency under resource constraints.').length, 1);
});

test('line fallback handles reading order differences without widening to unrelated columns', () => {
  const source = 'First unique sentence about neural networks.\nSecond unique sentence about edge resources.';
  const text = 'First unique sentence about neural networks. Other column content. Second unique sentence about edge resources.';
  const matches = matchSourceRanges(text, source);
  assert.equal(matches.length, 2);
  assert.ok(matches.every(range => !text.slice(range.start, range.end).includes('Other column')));
});

test('ambiguous, short, or low coverage source is not highlighted', () => {
  assert.deepEqual(matchSourceRanges('Repeated sentence. Repeated sentence.', 'Repeated sentence.'), []);
  assert.deepEqual(matchSourceRanges('Title', 'Title'), []);
  assert.deepEqual(matchSourceRanges('Only this sentence exists.', 'Only this sentence exists.\nThis much longer source section is completely absent from the PDF page. Another missing sentence too.'), []);
  assert.deepEqual(matchSourceRanges('Original English text.', '完全不匹配的中文译文'), []);
});

test('normalization maps UTF-16 offsets and expansion correctly', () => {
  const result = normalizedText('𝒜 ﬁ');
  assert.equal(result.value, 'afi');
  assert.deepEqual(result.starts, [0, 3, 3]);
  assert.deepEqual(result.ends, [2, 4, 4]);
});
