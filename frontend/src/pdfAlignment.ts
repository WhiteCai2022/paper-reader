export interface SourceHighlight {
  paperId: string;
  page: number;
  id: string;
  sourceText: string;
  wholePage?: boolean;
}

export interface TextRange { start: number; end: number }

// Keep source offsets through ligature expansion, wrapped words, and PDF whitespace.
export function normalizedText(text: string) {
  let value = '';
  const starts: number[] = [], ends: number[] = [];
  let offset = 0;
  for (const character of text) {
    const normalized = character.normalize('NFKC').toLowerCase()
      .replace(/[\s\u00ad\-\u2010-\u2015]/gu, '')
      .replace(/[\u2018\u2019]/g, "'").replace(/[\u201c\u201d]/g, '"');
    for (let index = 0; index < normalized.length; index++) {
      starts.push(offset); ends.push(offset + character.length);
    }
    value += normalized;
    offset += character.length;
  }
  return { value, starts, ends };
}

export function matchSourceRanges(text: string, source: string): TextRange[] {
  const indexed = normalizedText(text);
  const exact = (part: string): TextRange | null => {
    const needle = normalizedText(part).value;
    if (needle.length < 6) return null;
    const start = indexed.value.indexOf(needle);
    if (start < 0 || indexed.value.indexOf(needle, start + 1) >= 0) return null;
    return { start: indexed.starts[start], end: indexed.ends[start + needle.length - 1] };
  };
  const entire = exact(source);
  if (entire) return [entire];
  const lines = source.split(/\r?\n/).filter(line => normalizedText(line).value.length >= 12);
  const matched = lines.map(exact).filter((item): item is TextRange => !!item);
  const matchedLength = matched.reduce((sum, item) => sum + normalizedText(text.slice(item.start, item.end)).value.length, 0);
  // Never invent a position from translated Chinese or highlight a weak/ambiguous match.
  if (matchedLength < normalizedText(source).value.length * 0.65) return [];
  return matched.sort((a, b) => a.start - b.start).filter((item, index, list) => !index || item.start >= list[index - 1].end);
}
