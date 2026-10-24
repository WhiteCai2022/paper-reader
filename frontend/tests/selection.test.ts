import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizedSelectionRects } from '../src/pdfSelection.ts';

test('selection geometry is relative to the page, clipped and deduplicated', () => {
  const bounds = { left: 100, top: 50, width: 600, height: 800 };
  const rect = { left: 160, top: 130, width: 240, height: 16 };
  assert.deepEqual(normalizedSelectionRects([rect, rect], bounds), [{ x: .1, y: .1, width: .4, height: .02 }]);
  assert.deepEqual(normalizedSelectionRects([{ left: 90, top: 40, width: 70, height: 26 }], bounds), [{ x: 0, y: 0, width: .1, height: .02 }]);
});

test('zoom does not change stored anchors and non-text or outside boxes are ignored', () => {
  const rects = [{ left: 60, top: 80, width: 240, height: 16 }];
  const bounds = { left: 0, top: 0, width: 600, height: 800 };
  const zoomed = rects.map(rect => Object.fromEntries(Object.entries(rect).map(([key, value]) => [key, value * 2])) as typeof rect);
  assert.deepEqual(normalizedSelectionRects(rects, bounds), normalizedSelectionRects(zoomed, { left: 0, top: 0, width: 1200, height: 1600 }));
  assert.deepEqual(normalizedSelectionRects([{ left: 700, top: 10, width: 30, height: 10 }, { left: 1, top: 1, width: 0, height: 10 }], bounds), []);
  assert.deepEqual(normalizedSelectionRects(rects, { ...bounds, width: 0 }), []);
});
