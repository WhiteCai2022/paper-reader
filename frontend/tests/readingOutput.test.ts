import test from 'node:test';
import assert from 'node:assert/strict';
import { matchesReadingOutput, recommendedReadingOutput, resolveReadingOutput } from '../src/readingOutput.ts';

test('reading defaults leave more room for both JSON and reasoning', () => {
  assert.equal(recommendedReadingOutput('none'), 65536);
  assert.equal(recommendedReadingOutput('low'), 65536);
  assert.equal(recommendedReadingOutput('high'), 131072);
  assert.equal(recommendedReadingOutput('max'), 262144);
  assert.equal(resolveReadingOutput('auto', 131072), 131072);
  assert.equal(resolveReadingOutput('original', 65536), null);
});

test('custom reading caps must be exact bounded integers', () => {
  for (const value of ['4096', '65536', '393216']) assert.equal(resolveReadingOutput(value, 65536), Number(value));
  for (const value of ['', ' ', '4095', '393217', '1.2', '65536.0', '6e4', '-4096', 'NaN', 'Infinity']) {
    assert.ok(Number.isNaN(resolveReadingOutput(value, 65536)), value);
  }
});

test('a stale estimate cannot authorize a changed cap or original-limit selection', () => {
  assert.equal(matchesReadingOutput(65536, 65536), true);
  assert.equal(matchesReadingOutput(null, null), true);
  assert.equal(matchesReadingOutput(65536, 131072), false);
  assert.equal(matchesReadingOutput(undefined, null), false);
  assert.equal(matchesReadingOutput(65536, NaN), false);
  assert.equal(matchesReadingOutput(65536, null), false);
});
