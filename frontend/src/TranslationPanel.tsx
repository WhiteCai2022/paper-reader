import { useEffect, useRef, useState } from 'react';
import { Check, ChevronLeft, ChevronRight, CircleAlert, Download, Languages, LoaderCircle, RotateCw, Settings2, Square } from 'lucide-react';
import { api, messageOf } from './api';
import { Modal } from './Dialogs';
import { TranslationSegments } from './TranslationSegments';
import type { TranslationSegment } from './TranslationSegments';
import type { SourceHighlight } from './pdfAlignment';
import { ApiBalance, ApiSettingsDialog } from './ApiSettings';
import type { TranslationSettings } from './ApiSettings';
import type { Paper } from './types';
import { OptionsFields, models, efforts, configLabel } from './AiOptions';
import type { AiOptions as Options } from './AiOptions';

interface Job {
  id: string; status: string; total_pages: number; completed_pages: number;
  cached_pages: number; cost_cny: number; error: string; model: string; reasoning_effort: string;
}
interface Summary { pages: { page: number }[]; job: Job | null; settings: TranslationSettings }
interface PageTranslation {
  page: number; source_text: string; text_extractable: boolean;
  translation: { content: string; model: string; reasoning_effort: string; cost_cny: number; updated_at: string } | null;
  alignment: 'blocks' | 'page'; segments: TranslationSegment[];
  alignment_version: number;
}
interface Quote {
  quote_id: string; total_pages: number; cached_pages: number; estimated_cny: number;
  upper_bound_cny: number; settings: TranslationSettings; model: string; reasoning_effort: string;
  refresh_cache: boolean;
}
function readOptions(): Options {
  try {
    const value = JSON.parse(localStorage.getItem('paper-reader:translation-options') || '{}');
    return { model: models.some(item => item.id === value.model) ? value.model : 'deepseek-flash', reasoning_effort: efforts.some(item => item.id === value.reasoning_effort) ? value.reasoning_effort : 'none' };
  } catch { return { model: 'deepseek-flash', reasoning_effort: 'none' }; }
}
const active = (job?: Job | null) => !!job && ['queued', 'running', 'cancelling'].includes(job.status);
const money = (value: number) => value === 0 ? '0' : value < 0.0001 ? '<0.0001' : value.toFixed(4);
const statuses: Record<string, string> = { queued: '等待翻译', running: '正在翻译', cancelling: '正在停止后续页', completed: '翻译完成', cancelled: '已停止', failed: '翻译未完成', interrupted: '任务已中断' };

function TranslateDialog({ paper, page, options, refreshCache = false, currentPageOnly = false, onOptionsChange, onClose, onStarted }: { paper: Paper; page: number; options: Options; refreshCache?: boolean; currentPageOnly?: boolean; onOptionsChange: (value: Options) => void; onClose: () => void; onStarted: (job: Job) => void }) {
  const [scope, setScope] = useState('page');
  const [start, setStart] = useState(page);
  const [end, setEnd] = useState(page);
  const [budget, setBudget] = useState(0.5);
  const [replace, setReplace] = useState(refreshCache);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [estimating, setEstimating] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const first = scope === 'all' ? 1 : scope === 'page' ? page : start;
  const last = scope === 'all' ? paper.page_count : scope === 'page' ? page : end;
  useEffect(() => {
    const controller = new AbortController(); setQuote(null); setError(''); setEstimating(true);
    if (!Number.isInteger(first) || !Number.isInteger(last) || first < 1 || last < first || last > paper.page_count || last - first >= 500) {
      setError('请选择有效页码范围，每次最多 500 页。'); setEstimating(false); return;
    }
    const timer = setTimeout(() => {
      const pages = Array.from({ length: last - first + 1 }, (_, index) => first + index);
      api<Quote>(`/api/papers/${encodeURIComponent(paper.id)}/translations/estimate`, { method: 'POST', body: JSON.stringify({ pages, ...options, refresh_cache: replace }), signal: controller.signal })
        .then(value => { if (!controller.signal.aborted) { setQuote(value); setEstimating(false); } })
        .catch(failure => { if (!controller.signal.aborted) { setError(messageOf(failure)); setEstimating(false); } });
    }, 250);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [first, last, paper.id, paper.page_count, options.model, options.reasoning_effort, replace]);
  const matches = !!quote && quote.model === options.model && quote.reasoning_effort === options.reasoning_effort && quote.refresh_cache === replace;
  const exceeds = matches && quote.upper_bound_cny > budget ? '费用上限超过单次预算，可缩小页码范围或调整预算。'
    : matches && quote.upper_bound_cny > quote.settings.remaining_cny ? '已达到本程序累计支出上限，请在 API 设置的费用控制中调整。'
    : matches && quote.upper_bound_cny > 0 && !quote.settings.configured ? '请先关闭此窗口，在 API 设置中绑定 API Key。' : '';
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (!quote || !matches || exceeds) return; setBusy(true); setError('');
    try { const job = await api<Job>(`/api/papers/${encodeURIComponent(paper.id)}/translations`, { method: 'POST', body: JSON.stringify({ quote_id: quote.quote_id, max_cost_cny: budget }) }); onStarted(job); }
    catch (failure) { setError(messageOf(failure)); setBusy(false); }
  }
  return <Modal title={currentPageOnly ? '重新翻译当前页' : '翻译论文'} busy={busy} onClose={onClose}><form className="dialog-form" onSubmit={submit}>
    <OptionsFields options={options} onChange={onOptionsChange} disabled={busy} />
    <label>翻译范围<select value={scope} onChange={event => setScope(event.target.value)} disabled={busy || currentPageOnly}><option value="page">当前页（第 {page} 页）</option>{!currentPageOnly && <><option value="range">指定页码范围</option><option value="all">整篇论文（{paper.page_count} 页）</option></>}</select></label>
    {scope === 'range' && <div className="field-row"><label>起始页<input type="number" min={1} max={paper.page_count} value={start} onChange={event => setStart(Number(event.target.value))} disabled={busy} /></label><label>结束页<input type="number" min={start} max={paper.page_count} value={end} onChange={event => setEnd(Number(event.target.value))} disabled={busy} /></label></div>}
    <label className="translation-replace"><input type="checkbox" checked={replace} disabled={busy || currentPageOnly} onChange={event => setReplace(event.target.checked)} />重新翻译所选页（成功后替换已有译文）</label>
    {replace && <div className="form-warning" role="status">将重新调用 DeepSeek 并计费；失败时保留已有译文。</div>}
    <label>单次预算（元）<input type="number" min={0} max={1000} step="0.1" value={budget} required onChange={event => setBudget(Number(event.target.value))} disabled={busy} /></label>
    {estimating && <div className="translation-estimating"><LoaderCircle size={16} className="spin" />正在估算费用</div>}
    {matches && <div className="translation-cost-list"><span>本次页数<strong>{quote.total_pages} 页 · {quote.cached_pages} 页已有缓存</strong></span><span>预计费用<strong>¥{money(quote.estimated_cny)}</strong></span><span>保守费用上限<strong>¥{money(quote.upper_bound_cny)}</strong></span><ApiBalance settings={quote.settings} /></div>}
    <p className="translation-help">将所选页的文字发送给 DeepSeek。{replace ? '本次忽略缓存并重新计费，失败时保留原译文。' : '同模型、同推理强度的缓存页不重复调用。'}推理用量计入输出费用；按高峰价预留，实际费用以官方账单为准。</p>
    {(error || exceeds) && <div className="form-error" role="alert">{error || exceeds}</div>}
    <footer className="modal-footer"><span className="muted">{configLabel(options.model, options.reasoning_effort)}</span><div><button type="button" className="button" onClick={onClose} disabled={busy}>取消</button><button className="button primary" disabled={busy || estimating || !matches || !!exceeds}><Languages size={15} />{busy ? '提交中…' : currentPageOnly ? '确认重新翻译' : matches && quote.upper_bound_cny === 0 ? '读取缓存' : '确认翻译'}</button></div></footer>
  </form></Modal>;
}

export function TranslationPanel({ paper, onPage, onHighlight, onLocate }: { paper: Paper; onPage: (page: number) => void; onHighlight: (value: SourceHighlight | null) => void; onLocate: () => void }) {
  const page = paper.progress.page;
  const [summary, setSummary] = useState<Summary | null>(null);
  const [value, setValue] = useState<PageTranslation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [dialog, setDialog] = useState<'translate' | 'settings' | 'upgrade' | 'retranslate' | null>(null);
  const [stopping, setStopping] = useState(false);
  const [options, setOptions] = useState<Options>(readOptions);
  const query = new URLSearchParams({ model: options.model, reasoning_effort: options.reasoning_effort }).toString();
  const queryRef = useRef(query); queryRef.current = query;
  useEffect(() => { try { localStorage.setItem('paper-reader:translation-options', JSON.stringify(options)); } catch { /* Selection remains usable without browser storage. */ } }, [options]);
  async function refresh() { const data = await api<Summary>(`/api/papers/${encodeURIComponent(paper.id)}/translations?${query}`); if (queryRef.current === query) setSummary(data); }
  useEffect(() => {
    const changed = () => { void refresh().catch(failure => setError(messageOf(failure))); };
    window.addEventListener('paper-reader:api-settings-changed', changed);
    return () => window.removeEventListener('paper-reader:api-settings-changed', changed);
  }, [paper.id, query]);
  useEffect(() => {
    let disposed = false; setSummary(null);
    api<Summary>(`/api/papers/${encodeURIComponent(paper.id)}/translations?${query}`).then(data => { if (!disposed) setSummary(data); }).catch(failure => { if (!disposed) setError(messageOf(failure)); });
    return () => { disposed = true; };
  }, [paper.id, query]);
  const job = summary?.job;
  useEffect(() => {
    if (!active(job)) return;
    let disposed = false;
    const timer = setInterval(() => {
      api<Summary>(`/api/papers/${encodeURIComponent(paper.id)}/translations?${query}`).then(data => { if (!disposed) { setSummary(data); setError(''); } }).catch(failure => { if (!disposed) setError(messageOf(failure)); });
    }, 1800);
    return () => { disposed = true; clearInterval(timer); };
  }, [paper.id, query, job?.status]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setValue(null);
    api<PageTranslation>(`/api/papers/${encodeURIComponent(paper.id)}/translations/pages/${page}?${query}`, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) { setValue(data); setLoading(false); setError(''); } })
      .catch(failure => { if (!controller.signal.aborted) { setError(messageOf(failure)); setLoading(false); } });
    return () => controller.abort();
  }, [paper.id, page, query, job?.completed_pages]);
  async function cancel() {
    if (!job) return; setStopping(true);
    try { await api(`/api/translation/jobs/${job.id}/cancel`, { method: 'POST' }); await refresh(); }
    catch (failure) { setError(messageOf(failure)); } finally { setStopping(false); }
  }
  return <div className="translation-pane">
    <OptionsFields options={options} onChange={setOptions} />
    <div className="translation-controls"><div className="translation-page-controls"><button className="icon-button" title="上一页译文" aria-label="上一页译文" disabled={page <= 1} onClick={() => onPage(page - 1)}><ChevronLeft size={17} /></button><span>第 {page} / {paper.page_count} 页</span><button className="icon-button" title="下一页译文" aria-label="下一页译文" disabled={page >= paper.page_count} onClick={() => onPage(page + 1)}><ChevronRight size={17} /></button></div>
      <div className="toolbar-actions"><button className="icon-button" aria-label="重新翻译当前页" title="重新翻译当前页，需确认费用；成功后替换译文" disabled={loading || !value?.text_extractable || active(job)} onClick={() => setDialog('retranslate')}><RotateCw size={17} /></button><button className="icon-button" aria-label="翻译设置" title="翻译设置" disabled={!summary} onClick={() => setDialog('settings')}><Settings2 size={17} /></button><a className={`icon-button ${!summary?.pages.length ? 'translation-disabled' : ''}`} aria-label="导出中英对照" title="导出中英对照 Markdown" href={`/api/papers/${encodeURIComponent(paper.id)}/translations/export?${query}`} download><Download size={17} /></a><button className="button primary translation-start" disabled={active(job)} onClick={() => setDialog('translate')}><Languages size={15} />翻译</button></div>
    </div>
    {job && <div className={`translation-job ${job.status === 'failed' || job.status === 'interrupted' ? 'has-error' : ''}`}><div><span>{active(job) ? <LoaderCircle className="spin" size={14} /> : job.status === 'completed' ? <Check size={14} /> : <CircleAlert size={14} />}{statuses[job.status] || job.status}</span><span>{job.completed_pages} / {job.total_pages} 页</span>{active(job) && <button className="icon-button" aria-label="停止后续页翻译" title="停止后续页；进行中的本页仍可能计费" disabled={stopping || job.status === 'cancelling'} onClick={() => void cancel()}><Square size={13} /></button>}</div><progress max={job.total_pages} value={job.completed_pages} />{job.error && <p>{job.error}</p>}</div>}
    {summary && <><div className="translation-meter"><span>{summary.pages.length} / {paper.page_count} 页已翻译</span><span title="本程序按官方高峰价记账，实际扣费以官方账单为准">本程序已记账 ¥{money(summary.settings.spent_cny)}</span></div><div className="translation-account"><ApiBalance settings={summary.settings} onBind={() => setDialog('settings')} refreshToken={job ? `${job.id}:${active(job) ? 'active' : job.status}` : ''} /></div></>}
    <div className="translation-scroll">
      {error && <div className="form-error" role="alert">{error}</div>}
      {loading && <div className="empty-inline"><LoaderCircle className="spin" size={22} />正在读取本页</div>}
      {!loading && value?.translation && <article className="translated-page"><div className="translation-byline">中文译文 · 第 {page} 页 <span>{configLabel(value.translation.model, value.translation.reasoning_effort)}</span></div>
        <div className={`translation-alignment ${value.alignment_version >= 2 ? '' : 'legacy'}`}><span>{value.alignment === 'blocks' ? `段落对照 · ${value.segments.length} 段${value.alignment_version < 2 ? ' · 旧版分段' : ''}` : '整页对照 · 旧译文无段落锚点'}</span>{value.alignment_version < 2 && <button className="button" disabled={active(job)} onClick={() => setDialog('upgrade')} title="重新翻译当前页以更新段落识别，需确认费用"><RotateCw size={13} />更新对照</button>}</div>
        <TranslationSegments key={`${paper.id}:${page}:${query}:${value.translation.updated_at}`} paperId={paper.id} page={page} wholePage={value.alignment !== 'blocks'} segments={value.alignment === 'blocks' ? value.segments : [{ id: 'whole-page', source_text: value.source_text, content: value.translation.content }]} onHighlight={onHighlight} onLocate={onLocate} onPage={onPage} />
        <details className="translation-source"><summary>原文文本</summary><pre>{value.source_text}</pre></details></article>}
      {!loading && value && !value.translation && <div className="note-empty"><Languages size={29} /><strong>{value.text_extractable ? '这一页尚未翻译' : '这一页没有可提取文字'}</strong>{value.text_extractable && <button className="button primary" disabled={active(job)} onClick={() => setDialog('translate')}><Languages size={15} />翻译当前页</button>}{!value.text_extractable && <p className="translation-help">扫描页需要先进行 OCR。</p>}</div>}
    </div>
    {dialog === 'settings' && summary && <ApiSettingsDialog initialSettings={summary.settings} onClose={() => setDialog(null)} onSaved={refresh} />}
    {(dialog === 'translate' || dialog === 'upgrade' || dialog === 'retranslate') && <TranslateDialog paper={paper} page={page} options={options} refreshCache={dialog !== 'translate'} currentPageOnly={dialog === 'retranslate'} onOptionsChange={setOptions} onClose={() => setDialog(null)} onStarted={value => { setSummary(current => current ? { ...current, job: value } : current); setDialog(null); void refresh(); }} />}
  </div>;
}
