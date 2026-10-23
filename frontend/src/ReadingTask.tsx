import { useEffect, useRef, useState } from 'react';
import { Check, ClipboardCopy, Download, LoaderCircle, RotateCw } from 'lucide-react';
import { api, messageOf } from './api';
import { Modal } from './Dialogs';
import type { Paper } from './types';
import { ApiReading } from './ApiReading';

interface ReadingTask {
  paper_id: string;
  standard_version: string;
  mode: 'assistant-assisted';
  status: 'prepared';
  calls_external_api: false;
  request: string;
}

export function ReadingTaskDialog({ paper, onClose, onImported }: { paper: Paper; onClose: () => void; onImported: () => Promise<void> }) {
  const [mode, setMode] = useState<'assistant' | 'api'>('assistant');
  const [apiBusy, setApiBusy] = useState(false);
  const [focus, setFocus] = useState('');
  const [task, setTask] = useState<ReadingTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const output = useRef<HTMLTextAreaElement>(null);
  const sequence = useRef(0);
  const endpoint = `/api/papers/${encodeURIComponent(paper.id)}/reading-task`;

  useEffect(() => {
    const controller = new AbortController();
    const current = ++sequence.current;
    setTask(null); setBusy(true); setError(''); setCopied(false);
    const timer = setTimeout(() => {
      api<ReadingTask>(`${endpoint}?${new URLSearchParams({ focus })}`, { signal: controller.signal }).then((value) => {
        if (current === sequence.current && !controller.signal.aborted) setTask(value);
      }).catch((failure) => {
        if (current === sequence.current && !controller.signal.aborted) setError(messageOf(failure));
      }).finally(() => {
        if (current === sequence.current && !controller.signal.aborted) setBusy(false);
      });
    }, 200);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [endpoint, focus, attempt]);

  async function copy() {
    if (!task) return;
    try { await navigator.clipboard.writeText(task.request); setCopied(true); setError(''); }
    catch { output.current?.focus(); output.current?.select(); setError('剪贴板不可用，可下载任务文件'); }
  }

  return <Modal title="单篇精读任务" onClose={onClose} busy={apiBusy} className="reading-task-modal">
    <div className="reading-task-switch"><div className="segmented"><button aria-pressed={mode === 'assistant'} className={mode === 'assistant' ? 'active' : ''} disabled={apiBusy} onClick={() => setMode('assistant')}>助手任务</button><button aria-pressed={mode === 'api'} className={mode === 'api' ? 'active' : ''} disabled={apiBusy} onClick={() => setMode('api')}>API 精读</button></div></div>
    {mode === 'api' ? <ApiReading paper={paper} focus={focus} onFocus={setFocus} onImported={onImported} onBusy={setApiBusy} /> : <div className="dialog-form">
      <div className="reading-task-paper"><strong>{paper.short_title || paper.title}</strong><span>{paper.page_count} 页 · {paper.notes_count} 条已有解析</span></div>
      <div className="reading-task-status">助手精读 · 尚未生成解析 · 无 API 调用</div>
      <label>阅读重点（可选）<textarea className="reading-focus" value={focus} maxLength={2000} placeholder="例如：重点拆解排队模型、公式推导和实验设置" onChange={(event) => { setFocus(event.target.value); setTask(null); setCopied(false); }} /></label>
      <label>发给助手的精读任务<textarea ref={output} className="reading-task-output" aria-label="精读任务内容" readOnly value={task?.request || ''} spellCheck={false} /></label>
      {busy && <div className="reading-task-status" role="status"><LoaderCircle size={14} className="spin" />准备任务中</div>}
      {error && <div className="form-error" role="alert">{error}</div>}
      <footer className="modal-footer"><span className="muted">标准 {task?.standard_version || '2026-10-22'} · 不含自测</span><div>
        {!task && !busy && <button className="button" onClick={() => setAttempt((value) => value + 1)}><RotateCw size={15} />重试</button>}
        <a className={`button ${!task ? 'disabled' : ''}`} aria-disabled={!task} href={`${endpoint}?${new URLSearchParams({ focus, format: 'markdown' })}`} download onClick={(event) => { if (!task) event.preventDefault(); }}><Download size={15} />下载任务</a>
        <button className="button primary" disabled={!task || busy} onClick={() => void copy()}>{copied ? <Check size={15} /> : <ClipboardCopy size={15} />}{copied ? '已复制' : '复制任务'}</button>
      </div></footer>
    </div>}
  </Modal>;
}
