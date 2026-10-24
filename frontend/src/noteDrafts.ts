import type { NoteInput } from './types';

export interface NoteDraft { version: 1; savedAt: string; baseline: string; input: NoteInput }
type DraftStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
const kinds = new Set(['guide', 'concept', 'method', 'experiment', 'critique', 'exercise', 'note']);

export function draftKey(paperId: string, noteId: string | null): string {
  return `paper-reader:note-draft:v1:${encodeURIComponent(paperId)}:${noteId ? encodeURIComponent(noteId) : 'new'}`;
}

export function noteFingerprint(input: NoteInput): string {
  return JSON.stringify({ title: input.title, content: input.content, page_start: input.page_start, page_end: input.page_end,
    kind: input.kind, sort_order: input.sort_order, completed: input.completed,
    evidence: input.evidence || [], verification_status: input.verification_status || 'unverified' });
}

export function readNoteDraft(storage: DraftStorage, key: string): NoteDraft | null {
  try {
    const draft: unknown = JSON.parse(storage.getItem(key) || 'null');
    if (!draft || typeof draft !== 'object') return null;
    const value = draft as NoteDraft;
    const input = value.input;
    if (value.version !== 1 || typeof value.savedAt !== 'string' || !Number.isFinite(Date.parse(value.savedAt))
      || typeof value.baseline !== 'string' || !input || typeof input.title !== 'string' || typeof input.content !== 'string'
      || !kinds.has(input.kind) || !Number.isInteger(input.page_start) || !Number.isInteger(input.page_end)
      || !Number.isFinite(input.sort_order) || typeof input.completed !== 'boolean'
      || !['unverified', 'verified', 'needs_review'].includes(input.verification_status)
      || !Array.isArray(input.evidence) || input.evidence.length > 32
      || input.evidence.some(item => !item || !Number.isInteger(item.page) || typeof item.quote !== 'string' || typeof item.label !== 'string')) return null;
    return value;
  } catch { return null; }
}

export function writeNoteDraft(storage: DraftStorage, key: string, baseline: string, input: NoteInput): boolean {
  try {
    storage.setItem(key, JSON.stringify({ version: 1, savedAt: new Date().toISOString(), baseline, input } satisfies NoteDraft));
    return true;
  } catch { return false; }
}

export function removeNoteDraft(storage: DraftStorage, key: string): boolean {
  try { storage.removeItem(key); return true; } catch { return false; }
}
