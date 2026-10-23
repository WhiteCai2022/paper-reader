import { useEffect, useRef, useState } from 'react';
import { Eye, PenLine, Save, X } from 'lucide-react';
import type { Note, NoteInput, NoteKind } from './types';
import { kindLabels } from './types';
import { messageOf } from './api';
import { Markdown } from './Markdown';
import { useDialogFocus } from './Dialogs';

export function NoteEditor({ note, page, pageCount, onSave, onClose }: {
  note: Note | null; page: number; pageCount: number;
  onSave: (input: NoteInput) => Promise<void>; onClose: () => void;
}) {
  const initial = useRef<NoteInput>({ title: note?.title || '', content: note?.content || '',
    page_start: note?.page_start || page, page_end: note?.page_end || page,
    kind: note?.kind || 'note', sort_order: note?.sort_order || 0, completed: note?.completed || false });
  const [form, setForm] = useState<NoteInput>(initial.current);
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [leaving, setLeaving] = useState(false);
  const dialogRef = useRef<HTMLElement>(null);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial.current);
  const close = () => { if (saving) return; if (dirty) setLeaving(true); else onClose(); };
  useDialogFocus(dialogRef, () => { if (leaving) setLeaving(false); else close(); }, saving);
  useEffect(() => {
    if (!dirty) return;
    const preventLeaving = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', preventLeaving);
    return () => window.removeEventListener('beforeunload', preventLeaving);
  }, [dirty]);
  useEffect(() => { if (leaving) dialogRef.current?.querySelector<HTMLButtonElement>('.nested-confirm button')?.focus(); }, [leaving]);
  const update = <K extends keyof NoteInput>(key: K, value: NoteInput[K]) => setForm((current) => ({ ...current, [key]: value }));
  async function save(event: React.FormEvent) {
    event.preventDefault(); setError('');
    if (!form.title.trim()) { setError('请输入章节标题'); return; }
    if (form.page_start < 1 || form.page_end < form.page_start || form.page_end > pageCount) { setError(`页码范围应在 1–${pageCount} 页内，结束页不能小于起始页`); return; }
    setSaving(true);
    try { await onSave({ ...form, title: form.title.trim() }); }
    catch (failure) { setError(messageOf(failure)); setSaving(false); }
  }
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
    <section ref={dialogRef} className="modal editor-modal" role="dialog" aria-modal="true" aria-labelledby="editor-title">
      <header className="modal-heading"><h2 id="editor-title">{note ? '编辑解析' : '新增解析'}</h2><button type="button" className="icon-button" title="关闭编辑" aria-label="关闭编辑" onClick={close} disabled={saving}><X size={19} /></button></header>
      <form onSubmit={save}>
        <div className="editor-fields"><label className="full-field">章节标题<input autoFocus value={form.title} onChange={(event) => update('title', event.target.value)} maxLength={300} /></label>
          <label>类型<select value={form.kind} onChange={(event) => update('kind', event.target.value as NoteKind)}>{Object.entries(kindLabels).filter(([key]) => key !== 'exercise' || note?.kind === 'exercise').map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
          <label>起始页<input type="number" min={1} max={pageCount} value={form.page_start} onChange={(event) => update('page_start', Number(event.target.value))} /></label>
          <label>结束页<input type="number" min={form.page_start} max={pageCount} value={form.page_end} onChange={(event) => update('page_end', Number(event.target.value))} /></label>
        </div>
        <div className="editor-mode"><div className="segmented"><button type="button" className={mode === 'edit' ? 'active' : ''} onClick={() => setMode('edit')}><PenLine size={14} />编辑</button><button type="button" className={mode === 'preview' ? 'active' : ''} onClick={() => setMode('preview')}><Eye size={14} />预览</button></div><span className="muted">Markdown / LaTeX</span></div>
        {mode === 'edit' ? <textarea className="markdown-editor" aria-label="解析内容" spellCheck={false} value={form.content} onChange={(event) => update('content', event.target.value)} /> : <div className="editor-preview">{form.content ? <Markdown content={form.content} /> : <div className="empty-inline">尚无内容</div>}</div>}
        {error && <div className="form-error" role="alert">{error}</div>}
        <footer className="modal-footer"><span className="muted">{form.content.length.toLocaleString()} 字符{dirty ? ' · 未保存' : ''}</span><div><button type="button" className="button" onClick={close} disabled={saving}>取消</button><button className="button primary" type="submit" disabled={saving}><Save size={15} />{saving ? '保存中…' : '保存'}</button></div></footer>
      </form>
      {leaving && <div className="nested-confirm" role="alertdialog" aria-label="放弃未保存修改"><div><h3>放弃未保存的修改？</h3><p>本次编辑的内容还没有保存。</p><div className="button-row"><button className="button" onClick={() => setLeaving(false)}>继续编辑</button><button className="button danger" onClick={onClose}>放弃修改</button></div></div></div>}
    </section>
  </div>;
}
