import { useCallback, useEffect, useRef, useState } from 'react';
import { BookOpen, Check, Download, LoaderCircle, Play, RefreshCw, Settings2, Square } from 'lucide-react';
import { api, messageOf } from './api';
import { OptionsFields, configLabel } from './AiOptions';
import type { AiOptions } from './AiOptions';
import { ApiBalance, ApiSettingsDialog } from './ApiSettings';
import type { TranslationSettings } from './ApiSettings';
import { Markdown } from './Markdown';
import type { NoteInput, Paper } from './types';

interface Stage { kind: string; label: string; first: number; last: number; max_tokens: number }
interface Attempt {
  stage: number; label: string; finish_reason: string | null; max_tokens: number;
  input_tokens: number; output_tokens: number; reasoning_tokens: number | null;
}
interface ReadingJob {
  id: string; status: string; paper_id: string | null; focus: string; model: string; reasoning_effort: string;
  completed_stages: number; total_stages: number; cost_cny: number; error: string; imported_at: string | null;
  created_at: string; notes_count: number; notes: NoteInput[]; stages: Stage[]; last_attempt: Attempt | null; has_rejected_output: boolean;
}
interface ReadingList { jobs: ReadingJob[]; settings: TranslationSettings }
interface ReadingQuote {
  quote_id: string; model: string; reasoning_effort: string; focus: string; page_count: number;
  estimated_cny: number; upper_bound_cny: number; settings: TranslationSettings; stages: Stage[]; warning: string;
}
const active = (job?: ReadingJob | null) => !!job && ['queued', 'running', 'cancelling'].includes(job.status);
const money = (value: number) => value.toFixed(4);
const statusLabels: Record<string, string> = { queued: '等待生成', running: '后台生成中', cancelling: '正在停止后续阶段', cancelled: '已停止', completed: '草稿生成完成', failed: '生成未完成', interrupted: '服务重启，任务已中断' };
const when = (value: string) => new Date(value.replace(' ', 'T') + 'Z').toLocaleString('zh-CN');

export function ApiReading({ paper, focus, onFocus, onImported, onBusy }: {
  paper: Paper; focus: string; onFocus: (value: string) => void; onImported: () => Promise<void>; onBusy: (value: boolean) => void;
}) {
  const [options, setOptions] = useState<AiOptions>({ model: 'deepseek-flash', reasoning_effort: 'none' });
  const [budget, setBudget] = useState(2);
  const [list, setList] = useState<ReadingList | null>(null);
  const [selected, setSelected] = useState('');
  const selectedRef = useRef(selected); selectedRef.current = selected;
  const [job, setJob] = useState<ReadingJob | null>(null);
  const [quote, setQuote] = useState<ReadingQuote | null>(null);
  const [estimating, setEstimating] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [quoteError, setQuoteError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [confirmStart, setConfirmStart] = useState(false);
  const [confirmImport, setConfirmImport] = useState(false);
  const confirmRef = useRef<HTMLDivElement>(null);
  const endpoint = `/api/papers/${encodeURIComponent(paper.id)}/reading`;
  const callbacks = useRef({ onBusy }); callbacks.current = { onBusy };
  useEffect(() => { callbacks.current.onBusy(busy); return () => callbacks.current.onBusy(false); }, [busy]);
  useEffect(() => { if (confirmStart || confirmImport) confirmRef.current?.scrollIntoView({ block: 'nearest' }); }, [confirmStart, confirmImport]);
  const load = useCallback(async () => {
    const value = await api<ReadingList>(`${endpoint}/jobs`);
    setList(value);
    setSelected(current => value.jobs.some(item => item.id === current) ? current : value.jobs[0]?.id || '');
    if (selectedRef.current) {
      const current = await api<ReadingJob>(`/api/reading/jobs/${selectedRef.current}`);
      if (current.id === selectedRef.current) setJob(current);
    }
  }, [endpoint]);
  useEffect(() => { let disposed = false; void load().catch(failure => { if (!disposed) setError(messageOf(failure)); }); return () => { disposed = true; }; }, [load]);
  useEffect(() => {
    if (!selected) { setJob(null); return; }
    const controller = new AbortController(); setJob(null);
    api<ReadingJob>(`/api/reading/jobs/${selected}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setJob(value); }).catch(failure => { if (!controller.signal.aborted) setError(messageOf(failure)); });
    return () => controller.abort();
  }, [selected]);
  const running = !!list?.jobs.some(active) || active(job);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => { void load().catch(failure => setError(messageOf(failure))); }, 2000);
    return () => clearInterval(timer);
  }, [running, load]);
  useEffect(() => {
    const changed = () => { setAttempt(value => value + 1); void load().catch(failure => setError(messageOf(failure))); };
    window.addEventListener('paper-reader:api-settings-changed', changed);
    return () => window.removeEventListener('paper-reader:api-settings-changed', changed);
  }, [load]);
  useEffect(() => {
    const controller = new AbortController(); setQuote(null); setQuoteError(''); setEstimating(true); setConfirmStart(false);
    if (running) { setEstimating(false); return; }
    const timer = setTimeout(() => {
      api<ReadingQuote>(`${endpoint}/estimate`, { method: 'POST', body: JSON.stringify({ ...options, focus }), signal: controller.signal })
        .then(value => { if (!controller.signal.aborted) { setQuote(value); setEstimating(false); } })
        .catch(failure => { if (!controller.signal.aborted) { setQuoteError(messageOf(failure)); setEstimating(false); } });
    }, 400);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [endpoint, options.model, options.reasoning_effort, focus, running, attempt]);
  const matches = !!quote && quote.model === options.model && quote.reasoning_effort === options.reasoning_effort && quote.focus === focus.trim();
  const exceeds = !Number.isFinite(budget) || budget < 0 || budget > 1000 ? '请输入 0–1000 元的有效预算。'
    : matches && quote.upper_bound_cny > budget ? '精读费用上限超过单次预算，请调整模型、推理强度或预算。'
    : matches && quote.upper_bound_cny > quote.settings.remaining_cny ? '本程序累计剩余额度不足，请在 API 设置中调整费用控制。'
    : matches && !quote.settings.configured ? '请先绑定 DeepSeek API Key。' : '';
  async function start() {
    if (!quote || !matches || exceeds || running) return;
    setBusy(true); setError('');
    try {
      const value = await api<ReadingJob>(`${endpoint}/jobs`, { method: 'POST', body: JSON.stringify({ quote_id: quote.quote_id, max_cost_cny: budget }) });
      setSelected(value.id); setJob(value); setConfirmStart(false); setQuote(null); setAttempt(current => current + 1); await load();
    } catch (failure) { setError(messageOf(failure)); }
    finally { setBusy(false); }
  }
  async function cancel() {
    if (!job) return; setBusy(true); setError('');
    try { setJob(await api<ReadingJob>(`/api/reading/jobs/${job.id}/cancel`, { method: 'POST' })); await load(); }
    catch (failure) { setError(messageOf(failure)); } finally { setBusy(false); }
  }
  async function append() {
    if (!job) return; setBusy(true); setError('');
    try {
      const value = await api<{ job: ReadingJob }>(`/api/reading/jobs/${job.id}/import`, { method: 'POST' });
      setJob(value.job); setConfirmImport(false); await onImported(); await load();
    } catch (failure) { setError(messageOf(failure)); } finally { setBusy(false); }
  }
  return <div className="api-reading dialog-form">
    <div className="api-reading-scroll">
      <div className="reading-task-paper"><strong>{paper.short_title || paper.title}</strong><span>{paper.page_count} 页 · {paper.notes_count} 条已有解析</span></div>
      <div className="reading-task-status">API 精读草稿 · 尚未人工核验 · 不含自测</div>
      <OptionsFields options={options} onChange={setOptions} disabled={busy || running} />
      <label>阅读重点（可选）<textarea className="reading-focus" maxLength={2000} value={focus} onChange={event => onFocus(event.target.value)} disabled={busy || running} /></label>
      <label>单次预算（元）<input type="number" aria-label="精读单次预算" min={0} max={1000} step="0.1" value={budget} disabled={busy || running} onChange={event => setBudget(Number(event.target.value))} /></label>
      {estimating && <div className="reading-task-status"><LoaderCircle className="spin" size={15} />正在提取全文并估算费用</div>}
      {matches && !running && <><ol className="reading-plan">{quote.stages.map((stage, index) => <li key={index}>{stage.label}<small>输出上限 {stage.max_tokens.toLocaleString('zh-CN')} token{quote.reasoning_effort !== 'none' ? '（含推理）' : ''}</small></li>)}</ol><div className="translation-cost-list"><span>API 请求次数<strong>{quote.stages.length} 次 · 单篇 {quote.page_count} 页</strong></span><span>预计费用<strong>¥{money(quote.estimated_cny)}</strong></span><span>保守费用上限<strong>¥{money(quote.upper_bound_cny)}</strong></span></div></>}
      {(list || quote) && <div className="reading-api-balance"><ApiBalance settings={(list?.settings || quote!.settings)} onBind={() => setSettingsOpen(true)} refreshToken={job ? `${job.id}:${active(job) ? 'active' : job.status}` : ''} /><button className="icon-button" title="API 设置" aria-label="精读 API 设置" onClick={() => setSettingsOpen(true)}><Settings2 size={16} /></button></div>}
      {list && list.jobs.length > 0 && <label>生成记录<select aria-label="精读生成记录" disabled={busy} value={selected} onChange={event => { setSelected(event.target.value); setConfirmImport(false); }}>
        {list.jobs.map(item => <option key={item.id} value={item.id}>{when(item.created_at)} · {statusLabels[item.status] || item.status} · {configLabel(item.model, item.reasoning_effort)}</option>)}
      </select></label>}
      {job && <div className="reading-job"><div className="reading-job-heading"><strong>{active(job) ? <LoaderCircle className="spin" size={15} /> : job.status === 'completed' ? <Check size={15} /> : <BookOpen size={15} />}{statusLabels[job.status] || job.status}</strong><span>{job.completed_stages} / {job.total_stages} 阶段</span>{active(job) && <button className="icon-button" title="停止后续阶段，进行中的请求仍可能计费" aria-label="停止精读后续阶段" disabled={busy || job.status === 'cancelling'} onClick={() => void cancel()}><Square size={14} /></button>}</div>
        <progress value={job.completed_stages} max={job.total_stages} />
        {active(job) && <div className="muted">{job.stages[job.completed_stages]?.label || '正在保存草稿'}</div>}
        <div className="reading-job-meta"><span>{job.notes_count} 条草稿 · 已记账 ¥{money(job.cost_cny)}</span><span>{job.imported_at ? '已追加到解析' : '尚未导入解析'}</span></div>
        {job.status === 'failed' && job.last_attempt && <div className="reading-attempt"><strong>最近请求 · 第 {job.last_attempt.stage} 阶段 · {job.last_attempt.label}</strong><span>输出 {job.last_attempt.output_tokens.toLocaleString('zh-CN')} / 上限 {job.last_attempt.max_tokens.toLocaleString('zh-CN')} token{job.reasoning_effort !== 'none' ? '（含推理）' : ''}{job.last_attempt.reasoning_tokens !== null ? ` · 推理 ${job.last_attempt.reasoning_tokens.toLocaleString('zh-CN')} token` : ''}</span></div>}
        {job.error && <div className="form-error" role="alert">{job.error}</div>}
        {job.has_rejected_output && <a className="reading-rejected-download" href={`/api/reading/jobs/${job.id}/rejected-output`} download><Download size={13} />下载未通过结果</a>}
        {job.status === 'failed' && job.notes_count === 0 && <div className="muted">本次尚未生成有效草稿，已有解析未改动。</div>}
      </div>}
      {job?.notes?.length ? <div className="reading-draft-preview">{job.notes.map((note, index) => <details key={`${job.id}:${index}`} open={index === 0}><summary><span>{note.title}</span><small>第 {note.page_start}{note.page_end !== note.page_start ? `–${note.page_end}` : ''} 页</small></summary><Markdown content={note.content} /></details>)}</div> : null}
      {(error || quoteError) && <div className="form-error" role="alert">{error || quoteError}</div>}
      {exceeds && !running && <div className="form-warning" role="status">{exceeds}</div>}
      {confirmStart && matches && <div className="reading-confirm" ref={confirmRef} role="alert"><strong>确认调用 DeepSeek？</strong><p>将发送本篇论文提取文本与阅读重点，共 {quote.stages.length} 次请求，保守费用上限 ¥{money(quote.upper_bound_cny)}。生成新草稿，不覆盖已有解析；中断不自动重试，已完成请求仍计费。</p><div><button className="button" disabled={busy} onClick={() => setConfirmStart(false)}>取消</button><button className="button primary" disabled={busy || !!exceeds} onClick={() => void start()}><Play size={14} />{busy ? '提交中…' : '确认调用 API'}</button></div></div>}
      {confirmImport && job && <div className="reading-confirm" ref={confirmRef} role="alert"><strong>追加 {job.notes_count} 条 API 草稿？</strong><p>保留已有 {paper.notes_count} 条解析，新内容标注为尚未人工核验，不会覆盖或标记为已完成。</p><div><button className="button" disabled={busy} onClick={() => setConfirmImport(false)}>取消</button><button className="button primary" disabled={busy} onClick={() => void append()}><Check size={14} />确认追加</button></div></div>}
    </div>
    <footer className="modal-footer reading-api-footer"><div>{job && job.notes_count > 0 && <><a className="icon-button" title="导出精读 JSON" aria-label="导出精读 JSON" href={`/api/reading/jobs/${job.id}/export?format=json`} download><Download size={16} /></a><a className="button" href={`/api/reading/jobs/${job.id}/export?format=markdown`} download>Markdown</a></>}{job?.status === 'completed' && !job.imported_at && <button className="button" disabled={busy} onClick={() => { setConfirmImport(true); setConfirmStart(false); }}><Check size={14} />追加到解析</button>}</div>
      <div><button className="icon-button" title="重新估算" aria-label="重新估算精读费用" disabled={busy || estimating || running} onClick={() => setAttempt(value => value + 1)}><RefreshCw size={15} /></button><button className="button primary" disabled={busy || estimating || running || !matches || !!exceeds} onClick={() => { setConfirmStart(true); setConfirmImport(false); }}><Play size={15} />生成草稿</button></div>
    </footer>
    {settingsOpen && <ApiSettingsDialog initialSettings={list?.settings || quote?.settings} onClose={() => setSettingsOpen(false)} onSaved={async () => { await load(); setAttempt(value => value + 1); }} />}
  </div>;
}
