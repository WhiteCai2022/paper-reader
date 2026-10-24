import type { AnnotationRect, TextAnchor } from './types';

interface Bounds { left: number; top: number; width: number; height: number }

export function normalizedSelectionRects(rects: Bounds[], bounds: Bounds): AnnotationRect[] {
  if (bounds.width <= 0 || bounds.height <= 0) return [];
  const result: AnnotationRect[] = [];
  const seen = new Set<string>();
  for (const rect of rects) {
    const x = Math.max(0, rect.left - bounds.left), y = Math.max(0, rect.top - bounds.top);
    const width = Math.min(bounds.width, rect.left + rect.width - bounds.left) - x;
    const height = Math.min(bounds.height, rect.top + rect.height - bounds.top) - y;
    if (width < 1 || height < 1) continue;
    const value = { x: x / bounds.width, y: y / bounds.height, width: width / bounds.width, height: height / bounds.height };
    const key = JSON.stringify(value);
    if (!seen.has(key)) { seen.add(key); result.push(value); }
  }
  return result;
}

export function selectedPdfText(layer: HTMLElement, sheet: HTMLElement, page: number): TextAnchor | null {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount !== 1) return null;
  const range = selection.getRangeAt(0);
  if (!layer.contains(range.startContainer) || !layer.contains(range.endContainer)) return null;
  const quote = selection.toString().trim();
  if (!quote || quote.length > 10_000) return null;
  const walker = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT);
  const boxes: DOMRect[] = [];
  let node: Node | null;
  // Measure text nodes individually: transformed cross-span boxes can cover an entire column.
  while ((node = walker.nextNode())) {
    if (!range.intersectsNode(node)) continue;
    const part = document.createRange();
    part.setStart(node, range.startContainer === node ? range.startOffset : 0);
    part.setEnd(node, range.endContainer === node ? range.endOffset : node.textContent?.length || 0);
    if (!part.collapsed) boxes.push(...Array.from(part.getClientRects()));
  }
  const rects = normalizedSelectionRects(boxes, sheet.getBoundingClientRect());
  return rects.length && rects.length <= 512 ? { page, quote, rects } : null;
}
