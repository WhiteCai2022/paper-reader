import { useEffect, useRef, useState } from 'react';
import { Crosshair, LoaderCircle, MessageSquare, PenLine, Save, Trash2 } from 'lucide-react';
import type { PdfAnnotation, TextAnchor } from './types';
import { Modal } from './Dialogs';
import { messageOf } from './api';

export function AnnotationPanel({ annotations, page, activeId, onLocate, onEdit, onDelete }: {
  annotations: PdfAnnotation[]; page: number; activeId: string | null;
  onLocate: (item: PdfAnnotation) => void; onEdit: (item: PdfAnnotation) => void; onDelete: (item: PdfAnnotation) => void;
}) {
  const [currentPage, setCurrentPage] = useState(false);
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!activeId) return;
    setCurrentPage(false);
    requestAnimationFrame(() => list.current?.querySelector<HTMLElement>(`[data-annotation-id="${CSS.escape(activeId)}"]`)?.scrollIntoView({ block: 'nearest' }));
  }, [activeId]);
  const visible = annotations.filter(item => !currentPage || item.page === page).slice().sort((a, b) => a.page - b.page || a.rects[0].y - b.rects[0].y);
  return <>
    <div className="note-filter"><div className="segmented small"><button className={!currentPage ? 'active' : ''} onClick={() => setCurrentPage(false)}>全部批注</button><button className={currentPage ? 'active' : ''} onClick={() => setCurrentPage(true)}>当前页</button></div><span>{visible.length} 条</span></div>
    <div className="annotations-scroll" ref={list}>
      {!visible.length && <div className="note-empty"><MessageSquare size={28} /><strong>暂无批注</strong></div>}
      {visible.map(item => <article key={item.id} data-annotation-id={item.id} className={`annotation-item ${activeId === item.id ? 'active' : ''}`}>
        <header><button className="page-link" onClick={() => onLocate(item)} title="定位批注原文"><Crosshair size={14} />第 {item.page} 页</button><div className="toolbar-actions"><button className="icon-button" title="编辑批注" aria-label="编辑批注" onClick={() => onEdit(item)}><PenLine size={15} /></button><button className="icon-button danger-hover" title="删除批注" aria-label="删除批注" onClick={() => onDelete(item)}><Trash2 size={15} /></button></div></header>
        <button className="annotation-quote" title="定位批注原文" onClick={() => onLocate(item)}>{item.quote}</button>
        <p className="annotation-content">{item.content}</p>
      </article>)}
    </div>
  </>;
}

export function AnnotationEditor({ anchor, annotation, onClose, onSave }: {
  anchor: TextAnchor; annotation: PdfAnnotation | null; onClose: () => void; onSave: (content: string) => Promise<void>;
}) {
  const [content, setContent] = useState(annotation?.content || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [discard, setDiscard] = useState(false);
  function close() { if (content !== (annotation?.content || '')) setDiscard(true); else onClose(); }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!content.trim() || busy) return;
    setBusy(true); setError('');
    try { await onSave(content.trim()); } catch (failure) { setError(messageOf(failure)); } finally { setBusy(false); }
  }
  return <Modal title={annotation ? '编辑批注' : '添加批注'} onClose={close} busy={busy} className="annotation-editor">
    <form className="dialog-form" onSubmit={event => void save(event)}>
      <div className="annotation-source"><span>第 {anchor.page} 页</span><blockquote>{anchor.quote}</blockquote></div>
      <label>批注<textarea aria-label="批注内容" autoFocus rows={7} maxLength={20_000} required value={content} onChange={event => { setContent(event.target.value); setDiscard(false); }} disabled={busy} /></label>
      {error && <div className="form-error" role="alert">{error}</div>}
      {discard && <div className="annotation-discard" role="alert"><span>放弃未保存的批注？</span><button type="button" className="button" onClick={() => setDiscard(false)}>继续编辑</button><button type="button" className="button danger" onClick={onClose}>放弃</button></div>}
      <footer className="modal-footer"><span /><div><button type="button" className="button" onClick={close} disabled={busy}>取消</button><button type="submit" className="button primary" disabled={busy || !content.trim()}>{busy ? <LoaderCircle size={15} className="spin" /> : <Save size={15} />}保存</button></div></footer>
    </form>
  </Modal>;
}
