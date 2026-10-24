import type { Note, NoteKind, VerificationStatus } from './types';

export const noteKindOrder: NoteKind[] = ['guide', 'concept', 'method', 'experiment', 'critique', 'note', 'exercise'];

export function organizedNotes(notes: Note[]): Note[] {
  return [...notes].sort((left, right) => noteKindOrder.indexOf(left.kind) - noteKindOrder.indexOf(right.kind)
    || left.sort_order - right.sort_order || left.page_start - right.page_start || left.title.localeCompare(right.title, 'zh-CN'));
}

export function filterNotes(notes: Note[], page: number | null, kind: NoteKind | 'all', verification: VerificationStatus | 'all'): Note[] {
  return notes.filter(note => (page === null || (note.page_start <= page && note.page_end >= page))
    && (kind === 'all' || note.kind === kind)
    && (verification === 'all' || (note.verification_status || 'unverified') === verification));
}
