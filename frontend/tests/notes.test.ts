import assert from 'node:assert/strict';
import test from 'node:test';
import { filterNotes, organizedNotes } from '../src/noteOrganization.ts';
import { draftKey, noteFingerprint, readNoteDraft, removeNoteDraft, writeNoteDraft } from '../src/noteDrafts.ts';
import { remarkPageCitations, splitPageCitations } from '../src/pageCitations.ts';
import type { Note, NoteInput } from '../src/types.ts';

function input(patch: Partial<NoteInput> = {}): NoteInput {
  return { title: 'A note', content: 'Body', kind: 'note', page_start: 1, page_end: 2, sort_order: 0, completed: false,
    evidence: [], verification_status: 'unverified', ...patch };
}
function note(id: string, patch: Partial<NoteInput> = {}): Note { return { id, ...input(patch) }; }
function storage() {
  const data = new Map<string, string>();
  return { getItem: (key: string) => data.get(key) || null, setItem: (key: string, value: string) => { data.set(key, value); }, removeItem: (key: string) => { data.delete(key); } };
}

test('notes are organized by reading topic rather than generation chunk order', () => {
  const notes = [note('experiment', { kind: 'experiment', sort_order: 0 }), note('summary', { kind: 'guide', sort_order: 10 }), note('method', { kind: 'method', sort_order: 3 }), note('concept', { kind: 'concept', sort_order: 8 }), note('personal')];
  assert.deepEqual(organizedNotes(notes).map(item => item.id), ['summary', 'concept', 'method', 'experiment', 'personal']);
  assert.equal(notes[0].id, 'experiment');
});
test('category, page, and independent verification filters compose', () => {
  const notes = [note('one', { kind: 'method', verification_status: 'verified', completed: false }), note('two', { kind: 'method', verification_status: 'unverified', completed: true }), note('three', { kind: 'experiment', page_start: 3, page_end: 4, verification_status: 'verified' })];
  assert.deepEqual(filterNotes(notes, 2, 'method', 'verified').map(item => item.id), ['one']);
  assert.deepEqual(filterNotes(notes, 3, 'all', 'verified').map(item => item.id), ['three']);
});
test('local draft roundtrip preserves LaTeX, evidence, and the saved baseline', () => {
  const memory = storage(); const key = draftKey('paper/one', 'note:two');
  const original = input(); const draft = input({ content: '$\\theta + \\nu$\nDetails', evidence: [{ page: 2, quote: 'Original evidence from page two', label: 'Eq. 1' }], verification_status: 'needs_review' });
  assert.equal(writeNoteDraft(memory, key, noteFingerprint(original), draft), true);
  const restored = readNoteDraft(memory, key);
  assert.deepEqual(restored?.input, draft);
  assert.equal(restored?.baseline, noteFingerprint(original));
  assert.notEqual(restored?.baseline, noteFingerprint(input({ title: 'Changed externally' })));
  assert.equal(removeNoteDraft(memory, key), true);
  assert.equal(readNoteDraft(memory, key), null);
});
test('drafts are isolated by paper and note and ignore malformed or inaccessible storage', () => {
  assert.notEqual(draftKey('a', null), draftKey('b', null));
  assert.notEqual(draftKey('a', 'one'), draftKey('a', 'two'));
  const memory = storage();
  memory.setItem('bad', '{'); assert.equal(readNoteDraft(memory, 'bad'), null);
  memory.setItem('bad', JSON.stringify({ version: 1, savedAt: new Date().toISOString(), baseline: '', input: { ...input(), evidence: [null] } }));
  assert.equal(readNoteDraft(memory, 'bad'), null);
  const denied = { getItem() { throw Error('denied'); }, setItem() { throw Error('full'); }, removeItem() { throw Error('denied'); } };
  assert.equal(readNoteDraft(denied, 'key'), null);
  assert.equal(writeNoteDraft(denied, 'key', '', input()), false);
});
test('page citations become local links and leave invalid references untouched', () => {
  const nodes = splitPageCitations('Summary [p. 3] and [pp. 4–6], but [p. 0].');
  assert.deepEqual(nodes.filter(item => item.type === 'link').map(item => item.url), ['#page=3', '#page=4']);
  assert.ok(nodes.some(item => item.value?.includes('[p. 0]')));
});
test('page citation remark transform skips code, formulas, and existing links', () => {
  const tree = { type: 'root', children: [{ type: 'paragraph', children: [{ type: 'text', value: 'See [p. 2]' }, { type: 'inlineCode', value: '[p. 3]' }, { type: 'inlineMath', value: '[p. 4]' }, { type: 'link', url: 'https://example.com', children: [{ type: 'text', value: '[p. 5]' }] }] }, { type: 'code', value: '[p. 6]' }] };
  remarkPageCitations()(tree);
  assert.equal(tree.children[0].children?.[1].type, 'link');
  assert.equal(tree.children[0].children?.[2].value, '[p. 3]');
  assert.equal(tree.children[0].children?.[3].value, '[p. 4]');
  assert.equal(tree.children[0].children?.[4].children?.[0].value, '[p. 5]');
  assert.equal(tree.children[1].value, '[p. 6]');
});
