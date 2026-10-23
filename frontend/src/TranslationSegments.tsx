import { useEffect, useMemo, useState } from 'react';
import { LocateFixed, PinOff } from 'lucide-react';
import { Markdown } from './Markdown';
import type { SourceHighlight } from './pdfAlignment';

export interface TranslationSegment { id: string; source_text: string; content: string }

export function TranslationSegments({ paperId, page, segments, wholePage, onHighlight, onLocate, onPage }: {
  paperId: string; page: number; segments: TranslationSegment[]; wholePage: boolean;
  onHighlight: (value: SourceHighlight | null) => void; onLocate: () => void; onPage: (value: number) => void;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);
  const active = hovered || focused || pinned;
  const sourceText = segments.find(item => item.id === active)?.source_text;
  const highlight = useMemo(() => {
    return active && sourceText ? { paperId, page, id: active, sourceText, wholePage } : null;
  }, [sourceText, active, paperId, page, wholePage]);
  useEffect(() => { onHighlight(highlight); }, [highlight, onHighlight]);
  useEffect(() => () => onHighlight(null), [onHighlight]);
  function locate(id: string) { setPinned(id); setHovered(null); setFocused(null); onLocate(); }
  return <div className="translation-segments" data-alignment={wholePage ? 'page' : 'blocks'}>
    {segments.map((segment, index) => <section key={segment.id} tabIndex={0}
      data-segment-id={segment.id} aria-label={wholePage ? '整页译文' : `第 ${index + 1} 段译文`}
      className={`translation-segment ${active === segment.id ? 'active' : ''}`}
      onMouseEnter={() => setHovered(segment.id)} onMouseLeave={() => setHovered(null)}
      onFocus={() => setFocused(segment.id)} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(null); }}
      onKeyDown={event => { if (event.target === event.currentTarget && ['Enter', ' '].includes(event.key)) { event.preventDefault(); event.stopPropagation(); locate(segment.id); } if (event.key === 'Escape') { event.stopPropagation(); setPinned(null); setFocused(null); setHovered(null); } }}>
      <div className="translation-segment-meta"><span>{wholePage ? '整页' : String(index + 1).padStart(2, '0')}</span>
        <div><button className="icon-button" aria-label={wholePage ? '定位本页原文' : `定位第 ${index + 1} 段原文`} title="定位并固定原文高亮" aria-pressed={pinned === segment.id} onClick={() => locate(segment.id)}><LocateFixed size={14} /></button>
        {pinned === segment.id && <button className="icon-button" aria-label="取消固定高亮" title="取消固定高亮" onClick={event => { event.currentTarget.blur(); setPinned(null); setHovered(null); setFocused(null); }}><PinOff size={14} /></button>}</div>
      </div>
      <Markdown content={segment.content} onPage={onPage} />
    </section>)}
  </div>;
}
