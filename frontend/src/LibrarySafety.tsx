import { useEffect, useRef, useState } from 'react';
import { ArchiveRestore, Check, Download, FileArchive, LoaderCircle, RefreshCw, RotateCcw, ShieldCheck, Trash2, Upload } from 'lucide-react';
import { api, messageOf } from './api';
import { Modal } from './Dialogs';

interface TrashItem { type: 'paper' | 'note'; id: string; title: string; paper_id?: string; paper_title?: string; deleted_at: string }
interface RestorePreview {
  preview_id: string; papers_count: number; notes_count: number; pdfs_count: number;
  annotations_count?: number;
  missing_pdfs: number | string[]; warnings: string[];
}
interface EmptyTrashPreview {
  preview_id: string; papers_count: number; notes_count: number; pdfs_count: number;
  external_pdfs_count: number; warnings: string[];
}
interface EmptyTrashResult {
  papers_count: number; notes_count: number; pdfs_deleted: number;
  retained_files_count: number; warnings: string[];
}

export function LibrarySafetyDialog({ onClose, onRestored }: { onClose: () => void; onRestored: () => Promise<void> }) {
  const [tab, setTab] = useState<'backup' | 'trash'>('backup');
  const [items, setItems] = useState<TrashItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<RestorePreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [emptyPreview, setEmptyPreview] = useState<EmptyTrashPreview | null>(null);
  const [emptyConfirmed, setEmptyConfirmed] = useState(false);
  const [emptyWarnings, setEmptyWarnings] = useState<string[]>([]);
  const emptyButton = useRef<HTMLButtonElement>(null);
  const emptyHeading = useRef<HTMLHeadingElement>(null);
  async function loadTrash() {
    setLoading(true);
    try { setItems((await api<{ items: TrashItem[] }>('/api/library/trash')).items); }
    catch (failure) { setError(messageOf(failure)); } finally { setLoading(false); }
  }
  useEffect(() => { if (tab === 'trash') void loadTrash(); }, [tab]);
  useEffect(() => { if (emptyPreview) emptyHeading.current?.focus(); }, [emptyPreview]);
  function cancelEmpty() {
    setEmptyPreview(null); setEmptyConfirmed(false);
    requestAnimationFrame(() => emptyButton.current?.focus());
  }
  function changeTab(next: 'backup' | 'trash') {
    setTab(next); setError(''); setEmptyPreview(null); setEmptyConfirmed(false);
  }
  async function previewEmpty() {
    if (busy || loading || !items.length) return;
    setBusy(true); setError(''); setNotice(''); setEmptyConfirmed(false);
    try {
      setEmptyPreview(await api<EmptyTrashPreview>('/api/library/trash/empty/preview', { method: 'POST' }));
    } catch (failure) { setError(messageOf(failure)); } finally { setBusy(false); }
  }
  async function emptyTrash() {
    if (!emptyPreview || !emptyConfirmed || busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await api<EmptyTrashResult>('/api/library/trash/empty', { method: 'POST', body: JSON.stringify({ preview_id: emptyPreview.preview_id, confirm: true }) });
      setEmptyPreview(null); setEmptyConfirmed(false);
      const warnings = [...result.warnings];
      if (result.retained_files_count > 0) warnings.push(`仍有 ${result.retained_files_count} 个原文件保留在磁盘上；外部或共享文件按规则保留，其他原因见上方提示。对应记录已无法从回收站恢复。`);
      setEmptyWarnings(previous => [...new Set([...previous, ...warnings])]);
      setNotice(`回收站记录已清空：${result.papers_count} 篇文献、${result.notes_count} 条解析；实际删除 ${result.pdfs_deleted} 个托管 PDF。`);
      await loadTrash();
      try { await onRestored(); } catch (failure) { setError(`回收站已清空，但文献库刷新失败：${messageOf(failure)}`); }
    } catch (failure) {
      setEmptyPreview(null); setEmptyConfirmed(false);
      setError(`${messageOf(failure)}。未自动重试；请刷新回收站并重新预览。`);
    } finally { setBusy(false); }
  }
  async function backup() {
    setBusy(true); setError(''); setNotice('');
    try {
      const response = await fetch('/api/library/backup');
      if (!response.ok) {
        const value = await response.json().catch(() => ({})) as { detail?: string };
        throw new Error(value.detail || `备份失败（${response.status}）`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url;
      link.download = `paper-reader-backup-${new Date().toISOString().replace(/[:.]/g, '-')}.zip`;
      link.click(); setTimeout(() => URL.revokeObjectURL(url), 60000);
      setNotice('备份包已下载。不包含 API Key；未追加草稿随包单独存档。');
    } catch (failure) { setError(messageOf(failure)); } finally { setBusy(false); }
  }
  async function inspect() {
    if (!file) return; setBusy(true); setError(''); setNotice(''); setPreview(null); setConfirmed(false);
    try {
      const form = new FormData(); form.append('file', file);
      setPreview(await api<RestorePreview>('/api/library/restore/preview', { method: 'POST', body: form }));
    } catch (failure) { setError(messageOf(failure)); } finally { setBusy(false); }
  }
  async function restoreBackup() {
    if (!preview || !confirmed) return; setBusy(true); setError(''); setNotice('');
    try {
      const result = await api<{ papers_count: number; notes_count: number; annotations_count?: number }>('/api/library/restore', { method: 'POST', body: JSON.stringify({ preview_id: preview.preview_id, confirm: true }) });
      setPreview(null); setConfirmed(false); setFile(null);
      await onRestored(); setNotice(`已合并恢复 ${result.papers_count} 篇文献、${result.notes_count} 条解析、${result.annotations_count || 0} 条批注。现有文献和费用账本未覆盖。`);
    } catch (failure) { setError(messageOf(failure)); } finally { setBusy(false); }
  }
  async function restoreItem(item: TrashItem) {
    setBusy(true); setError(''); setNotice('');
    try {
      await api(`/api/library/trash/${item.type}/${encodeURIComponent(item.id)}/restore`, { method: 'POST' });
      await loadTrash(); await onRestored(); setNotice(`已恢复：${item.title}`);
    } catch (failure) { setError(messageOf(failure)); } finally { setBusy(false); }
  }
  const missing = preview ? Array.isArray(preview.missing_pdfs) ? preview.missing_pdfs.length : preview.missing_pdfs : 0;
  return <Modal title="数据与恢复" className="library-safety-modal" busy={busy} onClose={onClose}>
    <div className="library-safety-tabs segmented"><button aria-pressed={tab === 'backup'} className={tab === 'backup' ? 'active' : ''} disabled={busy} onClick={() => changeTab('backup')}><ShieldCheck size={15} />备份与恢复</button><button aria-pressed={tab === 'trash'} className={tab === 'trash' ? 'active' : ''} disabled={busy} onClick={() => changeTab('trash')}><Trash2 size={15} />回收站</button></div>
    <div className="dialog-form library-safety-scroll">
      {tab === 'backup' ? <>
        <section className="library-safety-section"><h3><FileArchive size={17} />文献库备份</h3><p className="muted">PDF、解析、批注、分类、阅读进度和译文；数据库与历史任务存档，不包含 API Key。</p><button className="button" disabled={busy} onClick={() => void backup()}>{busy ? <LoaderCircle className="spin" size={15} /> : <Download size={15} />}下载完整备份</button></section>
        <section className="library-safety-section"><h3><ArchiveRestore size={17} />安全合并恢复</h3><p className="muted">恢复为新文献，不覆盖当前资料、费用账本或 Key。历史收费任务不会重放，未追加草稿保留在备份包的 drafts 中。</p>
          <label>备份文件<input aria-label="选择文献库备份" type="file" accept=".zip,application/zip" disabled={busy} onChange={event => { setFile(event.target.files?.[0] || null); setPreview(null); setConfirmed(false); setError(''); }} /></label>
          <button className="button" disabled={busy || !file} onClick={() => void inspect()}>{busy ? <LoaderCircle className="spin" size={15} /> : <Upload size={15} />}校验备份包</button>
          {preview && <div className="library-restore-preview"><dl><div><dt>文献</dt><dd>{preview.papers_count}</dd></div><div><dt>解析</dt><dd>{preview.notes_count}</dd></div><div><dt>批注</dt><dd>{preview.annotations_count || 0}</dd></div><div><dt>PDF</dt><dd>{preview.pdfs_count}</dd></div></dl>
            {missing > 0 && <p className="form-warning">有 {missing} 个 PDF 未包含在备份中，恢复后需重新关联原文。</p>}
            {preview.warnings.map((warning, index) => <p className="form-warning" key={index}>{warning}</p>)}
            <label className="library-restore-confirm"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />确认合并为新文献；保留当前资料与费用记录</label>
            <button className="button primary" disabled={busy || !confirmed} onClick={() => void restoreBackup()}><ArchiveRestore size={15} />确认合并恢复</button>
          </div>}
        </section>
      </> : <section className="library-safety-section"><div className="library-trash-heading"><h3><Trash2 size={17} />已移除的文献与解析</h3><div className="library-trash-actions"><button className="icon-button" aria-label="刷新回收站" title="刷新回收站" disabled={busy || loading || !!emptyPreview} onClick={() => void loadTrash()}><RefreshCw size={15} className={loading ? 'spin' : ''} /></button><button ref={emptyButton} className="button danger" disabled={busy || loading || !items.length || !!emptyPreview} onClick={() => void previewEmpty()}><Trash2 size={15} />清空回收站</button></div></div>
        {emptyPreview && <section className="library-trash-confirm" aria-labelledby="library-trash-confirm-heading">
          <h3 ref={emptyHeading} id="library-trash-confirm-heading" tabIndex={-1}>永久清空回收站</h3>
          <dl><div><dt>文献</dt><dd>{emptyPreview.papers_count}</dd></div><div><dt>解析</dt><dd>{emptyPreview.notes_count}</dd></div><div><dt>托管 PDF</dt><dd>{emptyPreview.pdfs_count}</dd></div></dl>
          <p className="danger-text">将永久删除上述文献及关联资料（含批注）、单独删除的解析和历史版本，不能再从回收站还原。请先确认已保存所需备份。</p>
          <p className="muted">未删除的文献、费用账本和 API Key 不变；已有备份不受影响。外部原始 PDF 不会删除{emptyPreview.external_pdfs_count > 0 ? `（${emptyPreview.external_pdfs_count} 个）` : ''}。</p>
          {emptyPreview.warnings.map((warning, index) => <p className="form-warning" key={index}>{warning}</p>)}
          <label className="library-restore-confirm"><input type="checkbox" aria-label="确认永久删除回收站内容" checked={emptyConfirmed} disabled={busy} onChange={event => setEmptyConfirmed(event.target.checked)} />我确认永久删除，且理解无法从回收站还原</label>
          <div className="library-trash-confirm-actions"><button className="button" disabled={busy} onClick={cancelEmpty}>取消清空</button><button className="button danger" disabled={busy || !emptyConfirmed} onClick={() => void emptyTrash()}>{busy ? <LoaderCircle className="spin" size={15} /> : <Trash2 size={15} />}永久清空</button></div>
        </section>}
        {loading && <div className="empty-inline"><LoaderCircle className="spin" size={18} />正在读取</div>}
        {!loading && !items.length && <div className="empty-inline">回收站为空</div>}
        {items.map(item => <div className="library-trash-item" key={`${item.type}:${item.id}`}><div><strong>{item.title}</strong><span>{item.type === 'paper' ? '文献及其关联资料' : `解析${item.paper_title ? ` · ${item.paper_title}` : ''}`}</span></div><button className="icon-button" title={`恢复${item.title}`} aria-label={`恢复${item.title}`} disabled={busy || !!emptyPreview} onClick={() => void restoreItem(item)}><RotateCcw size={17} /></button></div>)}
      </section>}
      {notice && <div className="library-safety-notice" role="status"><Check size={15} />{notice}</div>}
      {emptyWarnings.length > 0 && <div className="library-trash-retained" role="alert">{emptyWarnings.map((warning, index) => <p className="form-warning" key={index}>{warning}</p>)}</div>}
      {error && <div className="form-error" role="alert">{error}</div>}
    </div>
    <footer className="modal-footer"><span className="muted">不调用模型，不产生 API 费用</span><button className="button" disabled={busy} onClick={onClose}>完成</button></footer>
  </Modal>;
}
