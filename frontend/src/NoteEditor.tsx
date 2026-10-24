import { useEffect, useRef, useState } from 'react';
import { CheckCheck, Eye, History, LoaderCircle, PenLine, Plus, RotateCcw, Save, Trash2, X } from 'lucide-react';
import type { Note, NoteEvidence, NoteInput, NoteKind, Paper, VerificationStatus } from './types';
import { kindLabels, verificationLabels } from './types';
import { api, messageOf } from './api';
import { Markdown } from './Markdown';
import { useDialogFocus } from './Dialogs';
import { draftKey, noteFingerprint, readNoteDraft, removeNoteDraft, writeNoteDraft } from './noteDrafts';
import type { NoteDraft } from './noteDrafts';

interface NoteVersion { id: string; created_at: string; reason: string; note: Note }
interface EvidenceCheck { status: string; message: string }
function draftStorage() { try { return window.localStorage; } catch { return null; } }
function timeLabel(value: string) { const date = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value.replace(' ', 'T')}Z`); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN'); }
const versionReasons: Record<string, string> = { create: '创建', edit: '编辑', delete: '删除前', import_replace: '覆盖导入前', restore: '恢复' };

export function NoteEditor({ paperId, note, page, pageCount, onSave, onClose, onRestored }: {
  paperId: string; note: Note | null; page: number; pageCount: number;
  onSave: (input: NoteInput) => Promise<void>; onClose: () => void; onRestored: () => Promise<void>;
}) {
  const initial = useRef<NoteInput>({ title: note?.title || '', content: note?.content || '',
    page_start: note?.page_start || page, page_end: note?.page_end || page,
    kind: note?.kind || 'note', sort_order: note?.sort_order || 0, completed: note?.completed || false,
    evidence: note?.evidence || [], verification_status: note?.verification_status || 'unverified' });
  const baseline = useRef(noteFingerprint(initial.current));
  const saveBaseline = useRef(baseline.current);
  const key = draftKey(paperId, note?.id || null);
  const [form, setForm] = useState<NoteInput>(initial.current);
  const [recovery, setRecovery] = useState<NoteDraft | null>(() => { const storage = draftStorage(); return storage ? readNoteDraft(storage, key) : null; });
  const [draftStatus, setDraftStatus] = useState('');
  const [mode, setMode] = useState<'edit' | 'preview'>('edit');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [leaving, setLeaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [history, setHistory] = useState(false);
  const [versions, setVersions] = useState<NoteVersion[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionError, setVersionError] = useState('');
  const [selectedVersion, setSelectedVersion] = useState<NoteVersion | null>(null);
  const [restoreConfirm, setRestoreConfirm] = useState(false);
  const [evidenceChecks, setEvidenceChecks] = useState<Record<string, EvidenceCheck>>({});
  const [checking, setChecking] = useState('');
  const dialogRef = useRef<HTMLElement>(null);
  const suppressDraft = useRef(false);
  const dirty = noteFingerprint(form) !== baseline.current;
  const latest = useRef({ form, dirty, recovery }); latest.current = { form, dirty, recovery };
  const close = () => { if (saving) return; if (dirty) setLeaving(true); else onClose(); };
  useDialogFocus(dialogRef, () => { if (restoreConfirm) setRestoreConfirm(false); else if (conflict) setConflict(false); else if (leaving) setLeaving(false); else close(); }, saving);

  function persistDraft(): boolean {
    const current = latest.current;
    if (suppressDraft.current || current.recovery || !current.dirty) return true;
    const storage = draftStorage();
    return storage ? writeNoteDraft(storage, key, saveBaseline.current, current.form) : false;
  }
  function clearDraft() { suppressDraft.current = true; const storage = draftStorage(); if (storage) removeNoteDraft(storage, key); }
  useEffect(() => {
    if (recovery || saving) return;
    if (!dirty) { const storage = draftStorage(); if (storage) removeNoteDraft(storage, key); setDraftStatus(''); return; }
    setDraftStatus('草稿保存中');
    const timer = setTimeout(() => setDraftStatus(persistDraft() ? '本机草稿已保存' : '本机草稿保存失败'), 500);
    return () => clearTimeout(timer);
  }, [form, dirty, recovery, saving]);
  useEffect(() => {
    const flush = () => { persistDraft(); };
    window.addEventListener('pagehide', flush);
    return () => { flush(); window.removeEventListener('pagehide', flush); };
  }, [key]);
  useEffect(() => {
    if (!dirty) return;
    const preventLeaving = (event: BeforeUnloadEvent) => { persistDraft(); event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', preventLeaving);
    return () => window.removeEventListener('beforeunload', preventLeaving);
  }, [dirty]);
  useEffect(() => {
    if (leaving || conflict || restoreConfirm) dialogRef.current?.querySelector<HTMLButtonElement>('.nested-confirm button')?.focus();
  }, [leaving, conflict, restoreConfirm]);

  const update = <K extends keyof NoteInput>(field: K, value: NoteInput[K]) => setForm(current => ({ ...current, [field]: value,
    verification_status: field !== 'verification_status' && ['title', 'content', 'evidence', 'page_start', 'page_end', 'kind'].includes(field) && current.verification_status === 'verified' ? 'needs_review' : field === 'verification_status' ? value as VerificationStatus : current.verification_status }));
  function updateEvidence(index: number, patch: Partial<NoteEvidence>) { update('evidence', form.evidence.map((item, position) => position === index ? { ...item, ...patch } : item)); }
  async function checkEvidence(evidence: NoteEvidence) {
    const checkKey = `${evidence.page}:${evidence.quote}`;
    setChecking(checkKey);
    try {
      const result = await api<EvidenceCheck>(`/api/papers/${encodeURIComponent(paperId)}/evidence/check`, { method: 'POST', body: JSON.stringify({ page: evidence.page, quote: evidence.quote }) });
      setEvidenceChecks(current => ({ ...current, [checkKey]: result }));
    } catch (failure) { setEvidenceChecks(current => ({ ...current, [checkKey]: { status: 'unavailable', message: messageOf(failure) } })); }
    finally { setChecking(''); }
  }
  async function performSave(overwrite = false) {
    if (saving || recovery) return;
    setError('');
    if (!form.title.trim()) { setError('请输入章节标题'); return; }
    if (form.page_start < 1 || form.page_end < form.page_start || form.page_end > pageCount) { setError(`页码范围应在 1–${pageCount} 页内，结束页不能小于起始页`); return; }
    if (form.evidence.some(item => item.page < 1 || item.page > pageCount || item.quote.trim().length < 10 || item.quote.length > 2000)) { setError('原文证据页码须在论文范围内，每条摘录须为 10–2000 字符'); return; }
    setSaving(true);
    try {
      if (note) {
        const currentPaper = await api<Paper>(`/api/papers/${encodeURIComponent(paperId)}`);
        const current = currentPaper.notes?.find(item => item.id === note.id);
        if (!current) throw new Error('这条解析已被删除，请先关闭编辑并在回收站恢复。');
        if (!overwrite && noteFingerprint(current) !== saveBaseline.current) { setConflict(true); setSaving(false); return; }
      }
      await onSave({ ...form, title: form.title.trim() });
      clearDraft();
    } catch (failure) { setError(messageOf(failure)); setSaving(false); persistDraft(); }
  }
  async function loadVersions() {
    if (!note) return;
    setHistory(true); setVersionsLoading(true); setVersionError('');
    try {
      const result = await api<{ versions: NoteVersion[] }>(`/api/papers/${encodeURIComponent(paperId)}/notes/${encodeURIComponent(note.id)}/versions`);
      setVersions(result.versions); setSelectedVersion(result.versions[0] || null);
    } catch (failure) { setVersionError(messageOf(failure)); }
    finally { setVersionsLoading(false); }
  }
  async function restoreVersion() {
    if (!note || !selectedVersion || saving) return;
    setSaving(true); setVersionError('');
    try {
      await api<Note>(`/api/papers/${encodeURIComponent(paperId)}/notes/${encodeURIComponent(note.id)}/versions/${encodeURIComponent(selectedVersion.id)}/restore`, { method: 'POST' });
      clearDraft(); await onRestored(); onClose();
    } catch (failure) { setVersionError(messageOf(failure)); setRestoreConfirm(false); setSaving(false); }
  }

  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) close(); }}>
    <section ref={dialogRef} className="modal editor-modal note-editor-v2" role="dialog" aria-modal="true" aria-labelledby="editor-title">
      <header className="modal-heading"><h2 id="editor-title">{note ? '编辑解析' : '新增解析'}</h2><div className="note-editor-header-actions">{note && <button type="button" className={`icon-button ${history ? 'pressed' : ''}`} title="版本历史" aria-label="版本历史" onClick={() => history ? setHistory(false) : void loadVersions()} disabled={saving}><History size={17} /></button>}<button type="button" className="icon-button" title="关闭编辑" aria-label="关闭编辑" onClick={close} disabled={saving}><X size={19} /></button></div></header>
      {history ? <div className="note-version-pane">
        <div className="note-version-heading"><h3>版本历史</h3><button className="button" type="button" disabled={saving} onClick={() => setHistory(false)}><PenLine size={14} />返回编辑</button></div>
        {versionsLoading && <div className="empty-inline"><LoaderCircle size={18} className="spin" />载入版本</div>}
        {versionError && <div className="form-error" role="alert">{versionError}</div>}
        {!versionsLoading && !versions.length && !versionError && <div className="empty-inline">暂无历史版本</div>}
        {versions.length > 0 && <><label className="note-version-select">版本<select aria-label="选择解析版本" value={selectedVersion?.id || ''} onChange={event => setSelectedVersion(versions.find(item => item.id === event.target.value) || null)}>{versions.map(item => <option key={item.id} value={item.id}>{timeLabel(item.created_at)} · {versionReasons[item.reason] || item.reason}</option>)}</select></label>{selectedVersion && <><h3>{selectedVersion.note.title}</h3><div className="note-version-info">{kindLabels[selectedVersion.note.kind]} · 第 {selectedVersion.note.page_start}–{selectedVersion.note.page_end} 页 · {verificationLabels[selectedVersion.note.verification_status || 'unverified']}</div><div className="note-version-preview"><Markdown content={selectedVersion.note.content} /></div><footer className="modal-footer"><span /><button className="button primary" type="button" disabled={saving} onClick={() => setRestoreConfirm(true)}><RotateCcw size={15} />恢复此版本</button></footer></>}</>}
      </div> : <form onSubmit={event => { event.preventDefault(); void performSave(); }}>
        <div className="note-editor-scroll">
          {recovery && <section className="note-draft-recovery" role="status"><strong>发现未提交的本机草稿</strong><span>{timeLabel(recovery.savedAt)}</span>{recovery.baseline !== baseline.current && <p className="error-text">解析已在草稿保存后发生变化。恢复后请核对差异，覆盖保存需要再次确认。</p>}<div className="button-row"><button type="button" className="button primary" onClick={() => { saveBaseline.current = recovery.baseline; setForm(recovery.input); setRecovery(null); setDraftStatus('已恢复本机草稿'); }}><RotateCcw size={14} />恢复草稿</button><button type="button" className="button" onClick={() => { const storage = draftStorage(); if (storage) removeNoteDraft(storage, key); setRecovery(null); }}>丢弃草稿</button></div></section>}
          <fieldset className="note-editor-fieldset" disabled={saving || !!recovery}>
            <div className="editor-fields"><label className="full-field">章节标题<input autoFocus value={form.title} onChange={event => update('title', event.target.value)} maxLength={300} /></label>
              <label>类型<select value={form.kind} onChange={event => update('kind', event.target.value as NoteKind)}>{Object.entries(kindLabels).filter(([value]) => value !== 'exercise' || note?.kind === 'exercise').map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              <label>起始页<input type="number" min={1} max={pageCount} value={form.page_start} onChange={event => update('page_start', Number(event.target.value))} /></label>
              <label>结束页<input type="number" min={form.page_start} max={pageCount} value={form.page_end} onChange={event => update('page_end', Number(event.target.value))} /></label>
            </div>
            <div className="editor-mode"><div className="segmented"><button type="button" className={mode === 'edit' ? 'active' : ''} onClick={() => setMode('edit')}><PenLine size={14} />编辑</button><button type="button" className={mode === 'preview' ? 'active' : ''} onClick={() => setMode('preview')}><Eye size={14} />预览</button></div><span className="muted">Markdown / LaTeX</span></div>
            {mode === 'edit' ? <textarea className="markdown-editor" aria-label="解析内容" spellCheck={false} value={form.content} onChange={event => update('content', event.target.value)} /> : <div className="editor-preview">{form.content ? <Markdown content={form.content} /> : <div className="empty-inline">尚无内容</div>}</div>}
            <div className="note-verification-field"><label>内容核验<select aria-label="内容核验状态" value={form.verification_status} onChange={event => update('verification_status', event.target.value as VerificationStatus)}>{Object.entries(verificationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="note-completed-field"><input type="checkbox" checked={form.completed} onChange={event => update('completed', event.target.checked)} />已读完</label></div>
            <section className="note-evidence-editor" aria-label="原文证据"><div className="note-evidence-heading"><h3>原文证据 <small>{form.evidence.length} / 32</small></h3><button type="button" className="icon-button" title="添加原文证据" aria-label="添加原文证据" disabled={form.evidence.length >= 32} onClick={() => update('evidence', [...form.evidence, { page: form.page_start, quote: '', label: '' }])}><Plus size={17} /></button></div>
              {form.evidence.map((item, index) => { const checkKey = `${item.page}:${item.quote}`; const result = evidenceChecks[checkKey]; return <div className="note-evidence-edit-row" key={index}>
                <div className="note-evidence-edit-fields"><label>页码<input aria-label={`证据 ${index + 1} 页码`} type="number" min={1} max={pageCount} value={item.page} onChange={event => updateEvidence(index, { page: Number(event.target.value) })} /></label><label>证据标注<input aria-label={`证据 ${index + 1} 标注`} maxLength={200} value={item.label} onChange={event => updateEvidence(index, { label: event.target.value })} /></label><button type="button" className="icon-button" title="核对原句是否出现在提取文本中，不代表结论已核验" aria-label={`核对证据 ${index + 1} 原句`} disabled={!!checking || item.quote.trim().length < 10 || item.quote.length > 2000 || item.page < 1 || item.page > pageCount} onClick={() => void checkEvidence(item)}>{checking === checkKey ? <LoaderCircle size={16} className="spin" /> : <CheckCheck size={16} />}</button><button type="button" className="icon-button danger-hover" title="移除原文证据" aria-label={`移除证据 ${index + 1}`} onClick={() => update('evidence', form.evidence.filter((_, position) => position !== index))}><Trash2 size={15} /></button></div>
                <textarea aria-label={`证据 ${index + 1} 原文摘录`} maxLength={2000} rows={3} value={item.quote} onChange={event => updateEvidence(index, { quote: event.target.value })} />
                {result && <div className={`note-evidence-check ${result.status}`} role="status">{result.message}</div>}
              </div>; })}
            </section>
          </fieldset>
          {error && <div className="form-error" role="alert">{error}</div>}
        </div>
        <footer className="modal-footer"><span className="muted">{form.content.length.toLocaleString()} 字符{dirty ? ` · ${draftStatus || '未提交'}` : ''}</span><div><button type="button" className="button" onClick={close} disabled={saving}>取消</button><button className="button primary" type="submit" disabled={saving || !!recovery}><Save size={15} />{saving ? '保存中…' : '保存'}</button></div></footer>
      </form>}
      {leaving && <div className="nested-confirm" role="alertdialog" aria-label="关闭未保存编辑"><div><h3>编辑尚未提交</h3><p>保留草稿后，下次打开这条解析可以继续编辑。</p><div className="button-row"><button className="button" onClick={() => setLeaving(false)}>继续编辑</button><button className="button" onClick={() => { if (persistDraft()) onClose(); else { setError('本机草稿保存失败，请先保存解析或明确丢弃修改。'); setLeaving(false); } }}>保留草稿并关闭</button><button className="button danger" onClick={() => { clearDraft(); onClose(); }}>丢弃修改</button></div></div></div>}
      {conflict && <div className="nested-confirm" role="alertdialog" aria-label="解析版本冲突"><div><h3>解析已在别处被修改</h3><p>当前编辑基于旧版本。覆盖保存会产生新的历史版本，本机草稿不会自动覆盖文献库。</p><div className="button-row"><button className="button" onClick={() => setConflict(false)}>返回编辑</button><button className="button danger" onClick={() => { setConflict(false); void performSave(true); }}>仍然覆盖保存</button></div></div></div>}
      {restoreConfirm && <div className="nested-confirm" role="alertdialog" aria-label="确认恢复解析版本"><div><h3>恢复所选版本？</h3><p>当前已保存内容会保留在版本历史中。{dirty ? '本次尚未提交的编辑和本机草稿将被丢弃。' : ''}</p><div className="button-row"><button className="button" disabled={saving} onClick={() => setRestoreConfirm(false)}>取消</button><button className="button primary" disabled={saving} onClick={() => void restoreVersion()}><RotateCcw size={15} />{saving ? '恢复中…' : '确认恢复'}</button></div></div></div>}
    </section>
  </div>;
}
