import type { ReactNode } from 'react';
import { ChevronRight } from 'lucide-react';
import type { NoteKind } from './types';
import { kindLabels } from './types';

export function NoteSection({ kind, count, expanded, onExpandedChange, children }: {
  kind: NoteKind; count: number; expanded: boolean; onExpandedChange: (value: boolean) => void; children: ReactNode;
}) {
  if (kind === 'critique') return <details className="note-kind-section note-critique-section" aria-label="补充评析" open={expanded}
    onToggle={event => { if (event.target === event.currentTarget) onExpandedChange(event.currentTarget.open); }}>
    <summary className="note-group-heading"><ChevronRight size={15} />补充评析<span>{count}</span></summary>
    {children}
  </details>;
  return <section className="note-kind-section" aria-label={kindLabels[kind]}><h2 className="note-group-heading">{kindLabels[kind]}<span>{count}</span></h2>{children}</section>;
}
