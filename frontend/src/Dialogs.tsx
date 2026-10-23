import { useEffect, useRef, useState } from 'react';
import type { ReactNode, RefObject } from 'react';
import { FileUp, LoaderCircle, Save, Search, Trash2, Upload, X } from 'lucide-react';
import type { Category, MetadataPreview, Paper } from './types';
import { api, messageOf } from './api';
import { CategoryPicker } from './CategoryPicker';

export function useDialogFocus(ref: RefObject<HTMLElement | null>, onClose: () => void, busy = false) {
  const state = useRef({ onClose, busy }); state.current = { onClose, busy };
  const previousFocus = useRef(document.activeElement as HTMLElement | null);
  useEffect(() => {
    const selector = 'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]';
    const dialog = ref.current;
    if (dialog && !dialog.contains(document.activeElement)) dialog.querySelector<HTMLElement>('input,textarea,button')?.focus();
    const listener = (event: KeyboardEvent) => {
      const all = document.querySelectorAll<HTMLElement>('[role="dialog"], [role="alertdialog"]');
      const top = all[all.length - 1];
      if (!top || (top !== ref.current && !ref.current?.contains(top))) return;
      if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); if (!state.current.busy) state.current.onClose(); }
      if (event.key !== 'Tab') return;
      const elements = [...top.querySelectorAll<HTMLElement>(selector)].filter((item) => item.getClientRects().length > 0);
      const first = elements[0]; const last = elements[elements.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || !top.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !top.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', listener, true);
    return () => { document.removeEventListener('keydown', listener, true); if (previousFocus.current?.isConnected) previousFocus.current.focus(); };
  }, [ref]);
}

export function Modal({ title, onClose, children, busy = false, className = '' }: {
  title: string; onClose: () => void; children: ReactNode; busy?: boolean; className?: string;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  useDialogFocus(dialogRef, onClose, busy);
  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section ref={dialogRef} role="dialog" aria-modal="true" aria-label={title} className={`modal ${className}`}>
      <header className="modal-heading"><h2>{title}</h2><button className="icon-button" title="关闭窗口" aria-label="关闭窗口" onClick={onClose} disabled={busy}><X size={19} /></button></header>{children}
    </section>
  </div>;
}

export function UploadDialog({ onClose, onUpload, categories, initialCategoryIds, onCreateCategory }: { onClose: () => void; onUpload: (form: FormData) => Promise<void>; categories: Category[]; initialCategoryIds: string[]; onCreateCategory: (name: string) => Promise<Category> }) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [shortTitle, setShortTitle] = useState('');
  const [authors, setAuthors] = useState('');
  const [venue, setVenue] = useState('');
  const [year, setYear] = useState('');
  const [doi, setDoi] = useState('');
  const [detecting, setDetecting] = useState(false);
  const [lookupBusy, setLookupBusy] = useState(false);
  const [metadataStatus, setMetadataStatus] = useState('');
  const [metadataWarnings, setMetadataWarnings] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [categoryIds, setCategoryIds] = useState(initialCategoryIds);
  const [categoryBusy, setCategoryBusy] = useState(false);
  const edited = useRef(new Set<string>());
  const requestSequence = useRef(0);
  const lookupController = useRef<AbortController | null>(null);

  function applyMetadata(value: MetadataPreview) {
    if (!edited.current.has('title')) setTitle(value.title);
    if (!edited.current.has('authors')) setAuthors(value.authors);
    if (!edited.current.has('venue')) setVenue(value.venue);
    if (!edited.current.has('year')) setYear(value.year?.toString() || '');
    if (!edited.current.has('doi')) setDoi(value.doi);
    setMetadataWarnings(value.warnings);
  }

  useEffect(() => {
    if (!file) return;
    const controller = new AbortController();
    const current = ++requestSequence.current;
    setDetecting(true); setMetadataStatus('正在读取 PDF 元数据');
    const form = new FormData(); form.append('file', file);
    api<MetadataPreview>('/api/papers/metadata', { method: 'POST', body: form, signal: controller.signal }).then((value) => {
      if (controller.signal.aborted || current !== requestSequence.current) return;
      applyMetadata(value);
      setMetadataStatus(value.sources.title === 'filename' ? '未识别到标题，已使用文件名' : '已读取 PDF 元数据');
    }).catch((failure) => {
      if (!controller.signal.aborted && current === requestSequence.current) { setMetadataStatus('元数据读取失败'); setMetadataWarnings([messageOf(failure)]); }
    }).finally(() => { if (!controller.signal.aborted && current === requestSequence.current) setDetecting(false); });
    return () => controller.abort();
  }, [file]);
  useEffect(() => () => { lookupController.current?.abort(); }, []);

  function selectFile(next: File | null) {
    ++requestSequence.current; lookupController.current?.abort(); edited.current.clear();
    setFile(next); setTitle(next?.name.replace(/\.pdf$/i, '').replaceAll('_', ' ').slice(0, 500) || '');
    setShortTitle(''); setAuthors(''); setVenue(''); setYear(''); setDoi(''); setLookupBusy(false);
    setMetadataWarnings([]); setMetadataStatus(''); setError('');
  }
  async function completeFromDoi() {
    if (!doi.trim() || detecting || lookupBusy || busy) return;
    const controller = new AbortController(); lookupController.current?.abort(); lookupController.current = controller;
    const current = requestSequence.current;
    setLookupBusy(true); setError('');
    try {
      const value = await api<MetadataPreview>('/api/metadata/doi', { method: 'POST', body: JSON.stringify({ doi: doi.trim() }), signal: controller.signal });
      if (!controller.signal.aborted && current === requestSequence.current) {
        // Missing Crossref fields do not erase information already read locally.
        if (!edited.current.has('title') && value.title) setTitle(value.title);
        if (!edited.current.has('authors') && value.authors) setAuthors(value.authors);
        if (!edited.current.has('venue') && value.venue) setVenue(value.venue);
        if (!edited.current.has('year') && value.year) setYear(String(value.year));
        if (!edited.current.has('doi') && value.doi) setDoi(value.doi);
        setMetadataStatus('已通过 Crossref 补全'); setMetadataWarnings(value.warnings);
      }
    } catch (failure) { if (!controller.signal.aborted && current === requestSequence.current) setError(messageOf(failure)); }
    finally { if (!controller.signal.aborted && current === requestSequence.current) setLookupBusy(false); }
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (busy || categoryBusy || detecting || lookupBusy) return; if (!file) { setError('请选择 PDF 文件'); return; }
    if (!file.name.toLowerCase().endsWith('.pdf')) { setError('请选择 PDF 格式文件'); return; }
    const form = new FormData(); form.append('file', file);
    form.append('metadata', JSON.stringify({ title: title.trim(), short_title: shortTitle.trim(), authors: authors.trim(), venue: venue.trim(), year: year ? Number(year) : null, doi: doi.trim() }));
    for (const id of categoryIds) form.append('category_ids', id);
    setBusy(true); setError('');
    try { await onUpload(form); } catch (failure) { setError(messageOf(failure)); setBusy(false); }
  }
  return <Modal title="导入 PDF" onClose={onClose} busy={busy || categoryBusy} className="upload-modal"><form className="dialog-form" onSubmit={submit}>
    <div className="upload-fields">
    <label className={`file-picker upload-file-picker ${file ? 'has-file' : ''}`}><FileUp size={29} /><strong>{file?.name || '选择 PDF 文件'}</strong><span>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : 'PDF'}</span><input autoFocus type="file" accept="application/pdf,.pdf" disabled={busy || categoryBusy} onChange={(event) => selectFile(event.target.files?.[0] || null)} /></label>
    {file && <div className="metadata-status" role="status" data-metadata-status={detecting ? 'loading' : 'ready'}>{detecting && <LoaderCircle size={14} className="spin" />}<span>{metadataStatus}</span></div>}
    {metadataWarnings.length > 0 && <div className="metadata-warnings">{metadataWarnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
    <label>论文标题<textarea aria-label="论文标题" className="upload-title" value={title} onChange={(event) => { edited.current.add('title'); setTitle(event.target.value); }} disabled={busy} maxLength={500} required /></label>
    <label>简称<input value={shortTitle} onChange={(event) => setShortTitle(event.target.value)} disabled={busy} maxLength={500} /></label>
    <label>作者<textarea aria-label="作者" className="upload-authors" value={authors} onChange={(event) => { edited.current.add('authors'); setAuthors(event.target.value); }} disabled={busy} maxLength={5000} /></label>
    <div className="field-row"><label>期刊 / 会议<input value={venue} onChange={(event) => { edited.current.add('venue'); setVenue(event.target.value); }} disabled={busy} maxLength={1000} /></label><label className="year-field">年份<input type="number" min={1800} max={2200} value={year} onChange={(event) => { edited.current.add('year'); setYear(event.target.value); }} disabled={busy} /></label></div>
    <label>DOI<div className="doi-lookup"><input aria-label="DOI" value={doi} onChange={(event) => { edited.current.add('doi'); lookupController.current?.abort(); setLookupBusy(false); setDoi(event.target.value); }} disabled={busy} maxLength={550} /><button type="button" className="icon-button" title="通过 Crossref 补全出版信息，仅发送 DOI" aria-label="通过 DOI 补全出版信息" disabled={busy || detecting || lookupBusy || !doi.trim()} onClick={() => void completeFromDoi()}>{lookupBusy ? <LoaderCircle size={16} className="spin" /> : <Search size={16} />}</button></div></label>
    <CategoryPicker categories={categories} value={categoryIds} onChange={setCategoryIds} disabled={busy} onCreate={onCreateCategory} onBusyChange={setCategoryBusy} />
    {error && <div className="form-error" role="alert">{error}</div>}
    </div>
    <footer className="modal-footer"><span className="muted">本地识别 · 无模型费用</span><div><button className="button" type="button" onClick={onClose} disabled={busy || categoryBusy}>取消</button><button className="button primary" disabled={busy || categoryBusy || detecting || lookupBusy || !file || !title.trim()}><Upload size={15} />{busy ? '导入中…' : '导入'}</button></div></footer>
  </form></Modal>;
}

export function ImportDialog({ count, onClose, onImport }: { count: number; onClose: () => void; onImport: (form: FormData) => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [mode, setMode] = useState<'append' | 'replace'>('append');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (!file || (mode === 'replace' && !confirmed)) return;
    const form = new FormData(); form.append('file', file); form.append('mode', mode);
    setBusy(true); setError('');
    try { await onImport(form); } catch (failure) { setError(messageOf(failure)); setBusy(false); }
  }
  return <Modal title="导入解析" onClose={onClose} busy={busy}><form className="dialog-form" onSubmit={submit}>
    <label className={`file-picker ${file ? 'has-file' : ''}`}><FileUp size={27} /><strong>{file?.name || '选择解析文件'}</strong><span>JSON / Markdown</span><input autoFocus type="file" accept=".json,.md,.markdown,application/json,text/markdown" disabled={busy} onChange={(event) => { setFile(event.target.files?.[0] || null); setError(''); }} /></label>
    <fieldset className="radio-options"><legend>导入方式</legend><label><input type="radio" checked={mode === 'append'} onChange={() => { setMode('append'); setConfirmed(false); }} />追加到现有解析</label><label><input type="radio" checked={mode === 'replace'} onChange={() => setMode('replace')} />替换全部解析</label></fieldset>
    {mode === 'replace' && <label className="replace-confirm"><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />确认替换当前文献的 {count} 条解析</label>}
    {error && <div className="form-error" role="alert">{error}</div>}
    <footer className="modal-footer"><span /><div><button type="button" className="button" onClick={onClose} disabled={busy}>取消</button><button className={`button ${mode === 'replace' ? 'danger' : 'primary'}`} disabled={busy || !file || (mode === 'replace' && !confirmed)}><Upload size={15} />{busy ? '导入中…' : '导入解析'}</button></div></footer>
  </form></Modal>;
}

export function PaperDialog({ paper, onClose, onSave, onDelete }: {
  paper: Paper; onClose: () => void; onSave: (values: Partial<Paper>) => Promise<void>; onDelete: () => void;
}) {
  const [title, setTitle] = useState(paper.title);
  const [shortTitle, setShortTitle] = useState(paper.short_title);
  const [authors, setAuthors] = useState(paper.authors);
  const [venue, setVenue] = useState(paper.venue);
  const [year, setYear] = useState(paper.year?.toString() || '');
  const [doi, setDoi] = useState(paper.doi || '');
  const [tags, setTags] = useState(paper.tags.join(', '));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (!title.trim()) { setError('请输入论文标题'); return; }
    setBusy(true); setError('');
    try { await onSave({ title: title.trim(), short_title: shortTitle.trim(), authors: authors.trim(), venue: venue.trim(), year: year ? Number(year) : null, doi: doi.trim(), tags: tags.split(/[,，]/).map((tag) => tag.trim()).filter(Boolean) }); }
    catch (failure) { setError(messageOf(failure)); setBusy(false); }
  }
  return <Modal title="文献信息" onClose={onClose} busy={busy}><form className="dialog-form" onSubmit={submit}>
    <label>论文标题<textarea aria-label="论文标题" autoFocus className="title-editor" value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
    <label>简称<input value={shortTitle} onChange={(event) => setShortTitle(event.target.value)} /></label>
    <label>作者<input value={authors} onChange={(event) => setAuthors(event.target.value)} /></label>
    <div className="field-row"><label>期刊 / 会议<input value={venue} onChange={(event) => setVenue(event.target.value)} /></label><label className="year-field">年份<input type="number" min={1900} max={2100} value={year} onChange={(event) => setYear(event.target.value)} /></label></div>
    <label>标签<input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="DAG, 动态分割" /></label>
    <label>DOI<input value={doi} onChange={(event) => setDoi(event.target.value)} maxLength={550} /></label>
    {error && <div className="form-error" role="alert">{error}</div>}
    <footer className="modal-footer"><button className="icon-button danger-text" type="button" title="移除文献记录" aria-label="移除文献记录" onClick={onDelete} disabled={busy}><Trash2 size={18} /></button><div><button type="button" className="button" onClick={onClose} disabled={busy}>取消</button><button className="button primary" disabled={busy}><Save size={15} />{busy ? '保存中…' : '保存'}</button></div></footer>
  </form></Modal>;
}
