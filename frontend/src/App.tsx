import { useCallback, useEffect, useRef, useState } from 'react';
import { AlignLeft, ArchiveRestore, ArrowDownToLine, BookOpen, Check, CheckCheck, ChevronDown, ChevronLeft, ChevronRight, Circle, CircleCheck, CloudOff, Download, FileCode2, FileText, FileUp, FlaskConical, FolderInput, GraduationCap, Highlighter, Languages, Library, ListPlus, ListTree, LoaderCircle, Maximize, PanelLeftClose, PanelLeftOpen, PenLine, Plus, Quote, RotateCw, Search, Settings2, SlidersHorizontal, Trash2, Upload, X, ZoomIn, ZoomOut } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { api, messageOf } from './api';
import type { Category, Note, NoteEvidence, NoteInput, NoteKind, Paper, ReadingProgress, VerificationStatus } from './types';
import { kindLabels, verificationLabels } from './types';
import { Markdown } from './Markdown';
import { PdfViewer } from './PdfViewer';
import { NoteEditor } from './NoteEditor';
import { TranslationPanel } from './TranslationPanel';
import { ApiSettingsDialog } from './ApiSettings';
import { ReadingTaskDialog } from './ReadingTask';
import { LibrarySafetyDialog } from './LibrarySafety';
import { filterNotes, noteKindOrder, organizedNotes } from './noteOrganization';
import { CategoryNameDialog, CategoryNav, CategoryPapersDialog, PaperCategoriesDialog } from './Categories';
import { ImportDialog, Modal, PaperDialog, UploadDialog } from './Dialogs';
import type { SourceHighlight } from './pdfAlignment';

type ProgressPatch = Partial<ReadingProgress> & { status?: Paper['status'] };
type ModalState = { type: 'upload' | 'import' | 'paper' | 'api-settings' | 'reading-task' | 'library-safety' } | { type: 'note'; note: Note | null } | { type: 'category-name'; category: Category | null } | { type: 'paper-categories'; paper: Paper } | { type: 'category-papers'; category: Category } | null;
interface ConfirmState { title: string; message: string; action: () => Promise<void> }
const kindIcons: Record<NoteKind, LucideIcon> = { guide: BookOpen, concept: Circle, method: SlidersHorizontal, experiment: FlaskConical, critique: PenLine, exercise: GraduationCap, note: FileText };
const statusNames = { unread: '未读', reading: '阅读中', done: '已读' };
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
function readStorage(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
function writeStorage(key: string, value: string) { try { localStorage.setItem(key, value); } catch { /* Reading remains available with browser storage disabled. */ } }

export default function App() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryId, setCategoryId] = useState(() => readStorage('paper-reader:category') || 'default');
  const [selectedId, setSelectedId] = useState('');
  const [paper, setPaper] = useState<Paper | null>(null);
  const [listLoading, setListLoading] = useState(true);
  const [paperLoading, setPaperLoading] = useState(false);
  const [listError, setListError] = useState('');
  const [paperError, setPaperError] = useState('');
  const [search, setSearch] = useState('');
  const [tag, setTag] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sidebar, setSidebar] = useState(true);
  const [mobileDrawer, setMobileDrawer] = useState(false);
  const [mobileView, setMobileView] = useState<'notes' | 'pdf'>('notes');
  const [noteMode, setNoteMode] = useState<'all' | 'page'>('all');
  const [noteKind, setNoteKind] = useState<NoteKind | 'all'>('all');
  const [verificationFilter, setVerificationFilter] = useState<VerificationStatus | 'all'>('all');
  const [leftView, setLeftView] = useState<'notes' | 'translation'>('notes');
  const [sourceHighlight, setSourceHighlight] = useState<SourceHighlight | null>(null);
  const [showContents, setShowContents] = useState(true);
  const [fitWidth, setFitWidth] = useState(true);
  const [selectable, setSelectable] = useState(true);
  const [split, setSplit] = useState(41);
  const [pageInput, setPageInput] = useState('1');
  const [modal, setModal] = useState<ModalState>(null);
  const [confirm, setConfirm] = useState<ConfirmState | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState('');
  const [exportOpen, setExportOpen] = useState(false);
  const [busyNotes, setBusyNotes] = useState<Set<string>>(new Set());
  const [sync, setSync] = useState<'saved' | 'pending' | 'error'>('saved');
  const [notice, setNotice] = useState('');
  const selectedRef = useRef(selectedId); selectedRef.current = selectedId;
  const paperRef = useRef(paper); paperRef.current = paper;
  const pending = useRef(new Map<string, { patch: ProgressPatch; timer: ReturnType<typeof setTimeout> }>());
  const chains = useRef(new Map<string, Promise<void>>());
  const cachedProgress = useRef(new Map<string, ProgressPatch>());
  const failed = useRef(new Set<string>());
  const deleted = useRef(new Set<string>());
  const notesRef = useRef<HTMLDivElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const loadSequence = useRef(0);

  const flushProgress = useCallback((id: string): Promise<void> => {
    const item = pending.current.get(id);
    if (!item) return chains.current.get(id) || Promise.resolve();
    clearTimeout(item.timer); pending.current.delete(id);
    const next = (chains.current.get(id) || Promise.resolve()).catch(() => undefined).then(async () => {
      if (deleted.current.has(id)) return;
      try {
        await api(`/api/papers/${encodeURIComponent(id)}/progress`, { method: 'PATCH', body: JSON.stringify(item.patch), keepalive: true });
        failed.current.delete(id);
        if (selectedRef.current === id && !pending.current.has(id)) setSync('saved');
      } catch {
        if (!deleted.current.has(id)) { failed.current.add(id); if (selectedRef.current === id) setSync('error'); }
      }
    });
    chains.current.set(id, next);
    void next.finally(() => { if (chains.current.get(id) === next) chains.current.delete(id); });
    return next;
  }, []);

  const queueProgress = useCallback((id: string, patch: ProgressPatch) => {
    cachedProgress.current.set(id, { ...cachedProgress.current.get(id), ...patch });
    const old = pending.current.get(id); if (old) clearTimeout(old.timer);
    const merged = { ...cachedProgress.current.get(id), ...old?.patch, ...patch };
    const timer = setTimeout(() => void flushProgress(id), 650);
    pending.current.set(id, { patch: merged, timer });
    if (selectedRef.current === id) setSync('pending');
  }, [flushProgress]);

  const updateReading = useCallback((id: string, patch: ProgressPatch) => {
    setPaper((current) => current?.id === id ? { ...current, status: patch.status || current.status, progress: { ...current.progress, ...patch } } : current);
    setPapers((current) => current.map((item) => item.id === id ? { ...item, status: patch.status || item.status, progress: { ...item.progress, ...patch } } : item));
    queueProgress(id, patch);
  }, [queueProgress]);

  const loadLibrary = useCallback(async () => {
    setListLoading(true); setListError('');
    try {
      const [data, groups] = await Promise.all([api<Paper[]>('/api/papers'), api<Category[]>('/api/categories')]);
      setPapers(data); setCategories(groups);
      setCategoryId((current) => current === 'all' || current === 'default' || groups.some((item) => item.id === current) ? current : 'default');
      setPaper((current) => current ? { ...current, category_ids: data.find((item) => item.id === current.id)?.category_ids || [] } : current);
      setSelectedId((current) => {
        if (data.some((item) => item.id === current)) return current;
        const previous = readStorage('paper-reader:selected');
        return data.find((item) => item.id === previous)?.id || data.find((item) => `${item.short_title} ${item.title}`.toLowerCase().includes('qdmp'))?.id || data[0]?.id || '';
      });
    } catch (failure) { setListError(messageOf(failure)); } finally { setListLoading(false); }
  }, []);

  useEffect(() => { void loadLibrary(); }, [loadLibrary]);
  useEffect(() => { writeStorage('paper-reader:category', categoryId); }, [categoryId]);
  useEffect(() => { setNoteKind('all'); setVerificationFilter('all'); setSourceHighlight(null); }, [selectedId]);
  useEffect(() => { setSourceHighlight(null); }, [leftView]);
  useEffect(() => {
    if (!selectedId) { setPaper(null); return; }
    const controller = new AbortController(); const sequence = ++loadSequence.current;
    setPaper(null); setPaperLoading(true); setPaperError('');
    setFitWidth(readStorage(`paper-reader:fit:${selectedId}`) !== 'false');
    setSync(failed.current.has(selectedId) ? 'error' : pending.current.has(selectedId) || chains.current.has(selectedId) ? 'pending' : 'saved');
    writeStorage('paper-reader:selected', selectedId);
    api<Paper>(`/api/papers/${encodeURIComponent(selectedId)}`, { signal: controller.signal }).then((data) => {
      if (controller.signal.aborted || sequence !== loadSequence.current) return;
      const cache = cachedProgress.current.get(data.id);
      const progress = { ...data.progress, ...cache };
      progress.page = clamp(progress.page || 1, 1, Math.max(1, data.page_count)); progress.zoom = clamp(progress.zoom || 1, 0.25, 4);
      const next = { ...data, notes: data.notes || [], status: cache?.status || data.status, progress };
      setPaper(next); setPaperLoading(false); setMobileView('notes');
      setPapers((current) => current.map((item) => item.id === data.id ? { ...next, notes: undefined } : item));
      if (next.status === 'unread') updateReading(data.id, { status: 'reading' });
    }).catch((failure) => { if (!controller.signal.aborted) { setPaperError(messageOf(failure)); setPaperLoading(false); } });
    return () => controller.abort();
  }, [selectedId, updateReading]);

  useEffect(() => { if (paper) setPageInput(String(paper.progress.page)); }, [paper?.progress.page, paper?.id]);
  useEffect(() => {
    const flush = () => { for (const id of pending.current.keys()) void flushProgress(id); };
    const visibility = () => { if (document.visibilityState === 'hidden') flush(); };
    window.addEventListener('pagehide', flush); document.addEventListener('visibilitychange', visibility);
    return () => { flush(); window.removeEventListener('pagehide', flush); document.removeEventListener('visibilitychange', visibility); };
  }, [flushProgress]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(''), 6500); return () => clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (!exportOpen) return;
    const close = (event: PointerEvent) => { if (!(event.target as Element).closest('.export-menu')) setExportOpen(false); };
    document.addEventListener('pointerdown', close); return () => document.removeEventListener('pointerdown', close);
  }, [exportOpen]);

  const changePage = useCallback((value: number) => {
    const current = paperRef.current; if (!current || !Number.isFinite(value)) return;
    updateReading(current.id, { page: clamp(Math.round(value), 1, Math.max(1, current.page_count)) });
  }, [updateReading]);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (modal || confirm || document.querySelector('[aria-modal="true"]') || event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target as HTMLElement;
      if (target.closest('input,textarea,select,[contenteditable="true"]')) return;
      const page = paperRef.current?.progress.page || 1;
      if (event.key === 'ArrowRight' || event.key === 'PageDown') { event.preventDefault(); changePage(page + 1); }
      if (event.key === 'ArrowLeft' || event.key === 'PageUp') { event.preventDefault(); changePage(page - 1); }
    };
    window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener);
  }, [changePage, modal, confirm]);

  const selectPaper = (id: string) => { if (id !== selectedId) { if (selectedId) void flushProgress(selectedId); setSelectedId(id); } setMobileDrawer(false); setExportOpen(false); };
  const noteList = organizedNotes(paper?.notes || []);
  const scopeNotes = filterNotes(noteList, noteMode === 'page' ? paper?.progress.page || 1 : null, 'all', verificationFilter);
  const visibleNotes = filterNotes(scopeNotes, null, noteKind, 'all');
  const tags = [...new Set(papers.flatMap((item) => item.tags))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
  const filteredPapers = papers.filter((item) => {
    const matches = `${item.title} ${item.short_title} ${item.authors} ${item.venue} ${item.tags.join(' ')}`.toLowerCase().includes(search.toLowerCase().trim());
    const inCategory = categoryId === 'all' || (categoryId === 'default' ? !item.category_ids?.length : item.category_ids?.includes(categoryId));
    return inCategory && matches && (tag === 'all' || item.tags.includes(tag)) && (statusFilter === 'all' || item.status === statusFilter);
  });
  const currentCategory = categories.find((item) => item.id === categoryId);
  const completed = noteList.filter((note) => note.completed).length;

  function selectCategory(id: string) { setCategoryId(id); setSearch(''); setTag('all'); setStatusFilter('all'); }
  async function createCategory(name: string): Promise<Category> {
    const created = await api<Category>('/api/categories', { method: 'POST', body: JSON.stringify({ name }) });
    setCategories((current) => [...current, created]);
    return created;
  }
  function askDeleteCategory(category: Category) {
    setConfirm({ title: '删除分类？', message: `删除“${category.name}”不会删除任何论文、PDF、解析或译文。没有其他分类的文献会回到默认分类。`, action: async () => {
      await api(`/api/categories/${encodeURIComponent(category.id)}`, { method: 'DELETE' });
      if (categoryId === category.id) setCategoryId('default');
      await loadLibrary(); setNotice('分类已删除，文献已保留');
    } }); setConfirmError('');
  }

  async function reloadCurrent(id: string) {
    const data = await api<Paper>(`/api/papers/${encodeURIComponent(id)}`);
    const local = paperRef.current?.id === id ? paperRef.current : null;
    const progress = { ...data.progress, ...cachedProgress.current.get(id), ...local?.progress };
    if (progress.active_note_id && !data.notes?.some((note) => note.id === progress.active_note_id)) {
      progress.active_note_id = null;
      queueProgress(id, { active_note_id: null });
    }
    const next = { ...data, status: cachedProgress.current.get(id)?.status || data.status, progress };
    if (selectedRef.current === id) setPaper(next);
    setPapers((current) => current.map((item) => item.id === id ? { ...next, notes: undefined } : item));
  }
  function mergeNote(id: string, note: Note) {
    setPaper((current) => current?.id === id ? { ...current, notes: (current.notes || []).map((item) => item.id === note.id ? note : item) } : current);
  }
  async function toggleNote(note: Note) {
    if (!paper) return; const id = paper.id;
    setBusyNotes((current) => new Set(current).add(note.id));
    try { const result = await api<Note>(`/api/papers/${encodeURIComponent(id)}/notes/${encodeURIComponent(note.id)}`, { method: 'PUT', body: JSON.stringify({ completed: !note.completed }) }); mergeNote(id, result || { ...note, completed: !note.completed }); }
    catch (failure) { setNotice(`勾选未保存：${messageOf(failure)}`); }
    finally { setBusyNotes((current) => { const next = new Set(current); next.delete(note.id); return next; }); }
  }
  function activateNote(note: Note, showPdf = false) {
    if (!paper) return;
    setSourceHighlight(null);
    updateReading(paper.id, { active_note_id: note.id, page: note.page_start });
    if (showPdf) setMobileView('pdf');
    requestAnimationFrame(() => document.getElementById(`note-${note.id}`)?.scrollIntoView({ block: 'start', behavior: 'smooth' }));
  }
  function locateEvidence(note: Note, evidence: NoteEvidence, index: number) {
    if (!paper) return;
    updateReading(paper.id, { active_note_id: note.id, page: evidence.page });
    setSourceHighlight({ paperId: paper.id, page: evidence.page, id: `note:${note.id}:${index}`, sourceText: evidence.quote });
    setMobileView('pdf');
  }
  function askDeleteNote(note: Note) {
    if (!paper) return; const id = paper.id;
    setConfirm({ title: '删除这条解析？', message: `“${note.title}”将移入回收站，可在“数据与恢复”中还原。`, action: async () => {
      await api(`/api/papers/${encodeURIComponent(id)}/notes/${encodeURIComponent(note.id)}`, { method: 'DELETE' });
      setPaper((current) => current?.id === id ? { ...current, notes: (current.notes || []).filter((item) => item.id !== note.id), notes_count: Math.max(0, current.notes_count - 1) } : current);
      setPapers((current) => current.map((item) => item.id === id ? { ...item, notes_count: Math.max(0, item.notes_count - 1) } : item));
      if (paperRef.current?.progress.active_note_id === note.id) updateReading(id, { active_note_id: null });
    } }); setConfirmError('');
  }
  function askDeletePaper(target: Paper) {
    const id = target.id;
    const nextId = filteredPapers.find((item) => item.id !== id)?.id || papers.find((item) => item.id !== id)?.id || '';
    setConfirm({ title: '删除文献及解析？', message: `“${target.short_title || target.title}”及其 ${target.notes_count} 条解析将移入回收站。原文件不受影响，受管理的 PDF 副本保留以便恢复。`, action: async () => {
      await flushProgress(id); await api(`/api/papers/${encodeURIComponent(id)}`, { method: 'DELETE' }); deleted.current.add(id);
      const item = pending.current.get(id); if (item) clearTimeout(item.timer); pending.current.delete(id); cachedProgress.current.delete(id); failed.current.delete(id);
      setModal(null); setPapers((current) => current.filter((item) => item.id !== id));
      if (selectedRef.current === id) { setSelectedId(nextId); setPaper(null); setPaperLoading(false); setPaperError(''); setMobileDrawer(false); }
      setNotice('文献及解析已删除');
    } }); setConfirmError('');
  }
  async function doConfirm() {
    if (!confirm || confirmBusy) return; setConfirmBusy(true); setConfirmError('');
    try { await confirm.action(); setConfirm(null); } catch (failure) { setConfirmError(messageOf(failure)); } finally { setConfirmBusy(false); }
  }
  function resizeStart(event: React.PointerEvent<HTMLDivElement>) {
    event.preventDefault(); const target = event.currentTarget; target.setPointerCapture(event.pointerId);
    const move = (next: PointerEvent) => { const rect = workspaceRef.current?.getBoundingClientRect(); if (rect) setSplit(clamp(((next.clientX - rect.left) / rect.width) * 100, 28, 64)); };
    const end = () => { target.removeEventListener('pointermove', move); target.removeEventListener('pointerup', end); target.removeEventListener('pointercancel', end); };
    target.addEventListener('pointermove', move); target.addEventListener('pointerup', end); target.addEventListener('pointercancel', end);
  }
  function zoomTo(value: number) { if (!paper) return; setFitWidth(false); writeStorage(`paper-reader:fit:${paper.id}`, 'false'); updateReading(paper.id, { zoom: clamp(Number(value.toFixed(3)), 0.25, 4) }); }
  const libraryContent = <>
    <div className="library-heading"><h2><Library size={16} />文献库 <span>{papers.length}</span></h2><button className="icon-button mobile-only" title="收起文献库" aria-label="收起文献库" onClick={() => setMobileDrawer(false)}><X size={17} /></button></div>
    <div className="library-search"><Search size={16} /><input aria-label="搜索文献" placeholder="搜索标题、作者、标签" value={search} onChange={(event) => setSearch(event.target.value)} /><button className={`icon-button ${!search ? 'invisible' : ''}`} title="清空搜索" aria-label="清空搜索" onClick={() => setSearch('')}><X size={13} /></button></div>
    <CategoryNav categories={categories} papers={papers} selected={categoryId} onSelect={selectCategory} onCreate={() => setModal({ type: 'category-name', category: null })} onRename={(category) => setModal({ type: 'category-name', category })} onDelete={askDeleteCategory} />
    <div className="library-filters"><select aria-label="主题筛选" value={tag} onChange={(event) => setTag(event.target.value)}><option value="all">全部主题</option>{tags.map((value) => <option key={value} value={value}>{value}</option>)}</select><select aria-label="阅读状态筛选" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">全部状态</option>{Object.entries(statusNames).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></div>
    <div className="category-current"><span>{categoryId === 'all' ? '全部文献' : currentCategory?.name || '默认分类'} <small>{filteredPapers.length}</small></span>{currentCategory && !currentCategory.is_default && <button className="icon-button" title="管理分类文献" aria-label="管理分类文献" onClick={() => setModal({ type: 'category-papers', category: currentCategory })}><ListPlus size={16} /></button>}</div>
    <div className="library-list">
      {listLoading && <div className="empty-inline"><LoaderCircle size={19} className="spin" />载入文献</div>}
      {listError && <div className="empty-inline error-text"><span>{listError}</span><button className="button" onClick={() => void loadLibrary()}><RotateCw size={14} />重试</button></div>}
      {!listLoading && !listError && !filteredPapers.length && <div className="empty-inline"><Search size={22} /><span>{papers.length ? '没有匹配的文献' : '文献库为空'}</span>{currentCategory && !currentCategory.is_default && <button className="button" onClick={() => setModal({ type: 'category-papers', category: currentCategory })}><ListPlus size={15} />添加文献</button>}{!papers.length && <button className="button" onClick={() => setModal({ type: 'upload' })}><Plus size={15} />导入 PDF</button>}</div>}
      {filteredPapers.map((item) => <div className={`paper-item ${item.id === selectedId ? 'selected' : ''}`} key={item.id} data-paper-id={item.id}>
        <button type="button" className="paper-open" onClick={() => selectPaper(item.id)} title={item.title} aria-current={item.id === selectedId ? 'true' : undefined}>
          <span className="paper-item-top"><span className={`status-dot ${item.status}`} /><strong>{item.short_title || item.title}</strong><span className="paper-year">{item.year || ''}</span></span>
          <span className="paper-title">{item.title}</span><span className="paper-meta">{item.venue || '未填写出版信息'}<span>{item.page_count} 页 · {item.notes_count} 条解析</span></span>
          {item.tags.length > 0 && <span className="paper-tags">{item.tags.slice(0, 3).map((value) => <span key={value}>{value}</span>)}</span>}
        </button>
        <button type="button" className="icon-button paper-categorize" title="设置文献分类" aria-label={`设置文献分类：${item.short_title || item.title}`} onClick={() => setModal({ type: 'paper-categories', paper: item })}><FolderInput size={15} /></button>
        <button type="button" className="icon-button paper-delete danger-hover" title="删除文献及全部解析" aria-label={`删除文献：${item.short_title || item.title}`} onClick={() => askDeletePaper(item)}><Trash2 size={15} /></button>
      </div>)}
    </div><div className="library-bottom"><span><span className="local-dot" />本地文献库</span><a href="/api/docs" target="_blank" rel="noreferrer" title="打开 API 文档"><FileCode2 size={14} />API</a></div>
  </>;

  return <div className={`app-shell ${sidebar ? '' : 'sidebar-collapsed'}`}>
    <header className="app-header"><div className="brand"><BookOpen size={23} /><span>论文研读</span></div>
      <button className="icon-button desktop-only" title={sidebar ? '折叠文献库' : '展开文献库'} aria-label={sidebar ? '折叠文献库' : '展开文献库'} onClick={() => setSidebar(!sidebar)}>{sidebar ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}</button>
      <button className="icon-button mobile-only" title="文献库" aria-label="打开文献库" onClick={() => setMobileDrawer(true)}><Library size={19} /></button>
      <div className="header-current">{paper?.short_title || paper?.title || '文献阅读'}</div><div className="header-actions"><button className="icon-button" title="数据与恢复" aria-label="数据与恢复" onClick={() => setModal({ type: 'library-safety' })}><ArchiveRestore size={18} /></button><button className="button" title="API Key 绑定与账户余额" onClick={() => setModal({ type: 'api-settings' })}><Settings2 size={16} /><span>设置</span></button><button className="button upload-button" onClick={() => setModal({ type: 'upload' })}><Plus size={16} /><span>导入 PDF</span></button></div>
    </header>
    <div className="app-body">
      {sidebar && <aside className="library-panel desktop-only">{libraryContent}</aside>}
      {mobileDrawer && <div className="drawer-backdrop" onClick={() => setMobileDrawer(false)}><aside className="library-panel mobile-drawer" onClick={(event) => event.stopPropagation()}>{libraryContent}</aside></div>}
      <main className="reader-main">
        {paperLoading && <div className="surface-state"><LoaderCircle className="spin" size={28} /><span>正在打开文献</span></div>}
        {paperError && <div className="surface-state"><FileText size={30} /><strong>文献暂时无法打开</strong><p>{paperError}</p><button className="button" onClick={() => { const id = selectedId; setSelectedId(''); setTimeout(() => setSelectedId(id), 0); }}><RotateCw size={15} />重试</button></div>}
        {!paperLoading && !paperError && !paper && <div className="surface-state"><BookOpen size={34} /><strong>{listLoading ? '正在载入文献库' : '选择一篇文献'}</strong><button className="button" onClick={() => setModal({ type: 'upload' })}><Upload size={15} />导入 PDF</button></div>}
        {paper && <>
          <div className="paper-heading"><div className="paper-heading-text"><div className="publication"><span>{paper.venue || '本地文献'}</span>{paper.year && <span>{paper.year}</span>}<span>{paper.page_count} 页</span></div><h1 title={paper.title}>{paper.title}</h1><p title={paper.authors}>{paper.authors || '作者信息未填写'}</p></div>
            <div className="paper-heading-actions"><button className="button reading-task-button" title="单篇精读：助手任务或 API 草稿" aria-label="精读任务" onClick={() => setModal({ type: 'reading-task' })}><BookOpen size={15} /><span>精读任务</span></button><button className={`button status-button ${paper.status === 'done' ? 'done' : ''}`} onClick={() => updateReading(paper.id, { status: paper.status === 'done' ? 'reading' : 'done' })} title={paper.status === 'done' ? '标记为阅读中' : '标记为已读'}>{paper.status === 'done' ? <CheckCheck size={15} /> : <CircleCheck size={15} />}<span>{paper.status === 'done' ? '已读' : '标记已读'}</span></button><button className="icon-button" title="编辑文献信息" aria-label="编辑文献信息" onClick={() => setModal({ type: 'paper' })}><SlidersHorizontal size={17} /></button></div>
          </div>
          <div className="mobile-tabs segmented"><button className={mobileView === 'notes' ? 'active' : ''} onClick={() => setMobileView('notes')}>{leftView === 'translation' ? <Languages size={16} /> : <AlignLeft size={16} />}{leftView === 'translation' ? '译文' : '解析'}</button><button className={mobileView === 'pdf' ? 'active' : ''} onClick={() => setMobileView('pdf')}><FileText size={16} />原文</button></div>
          <div className={`reading-workspace mobile-${mobileView}`} ref={workspaceRef} style={{ '--note-width': `${split}%` } as React.CSSProperties}>
            <section className="notes-pane" aria-label={leftView === 'translation' ? '论文译文' : '论文解析'}>
              <div className="pane-toolbar reader-view-toolbar"><div className="segmented small left-view-switch"><button className={leftView === 'notes' ? 'active' : ''} aria-pressed={leftView === 'notes'} onClick={() => setLeftView('notes')}><AlignLeft size={14} />解析</button><button className={leftView === 'translation' ? 'active' : ''} aria-pressed={leftView === 'translation'} onClick={() => setLeftView('translation')}><Languages size={14} />译文</button></div>{leftView === 'notes' && <div className="toolbar-actions"><button className={`icon-button ${showContents ? 'pressed' : ''}`} title={showContents ? '收起章节目录' : '显示章节目录'} aria-label="切换章节目录" aria-pressed={showContents} onClick={() => setShowContents(!showContents)}><ListTree size={17} /></button><button className="icon-button" title="导入解析" aria-label="导入解析" onClick={() => setModal({ type: 'import' })}><FileUp size={17} /></button><div className="export-menu"><button className={`icon-button ${exportOpen ? 'pressed' : ''}`} title="导出解析" aria-label="导出解析" onClick={() => setExportOpen(!exportOpen)}><ArrowDownToLine size={17} /></button>{exportOpen && <div className="dropdown"><a href={`/api/papers/${encodeURIComponent(paper.id)}/export?format=json`} download onClick={() => setExportOpen(false)}><FileCode2 size={15} />JSON</a><a href={`/api/papers/${encodeURIComponent(paper.id)}/export?format=markdown`} download onClick={() => setExportOpen(false)}><FileText size={15} />Markdown</a></div>}</div><button className="icon-button accent" title="新增解析" aria-label="新增解析" onClick={() => setModal({ type: 'note', note: null })}><Plus size={18} /></button></div>}</div>
              {leftView === 'translation' ? <TranslationPanel key={paper.id} paper={paper} onPage={changePage} onHighlight={setSourceHighlight} onLocate={() => setMobileView('pdf')} /> : <><div className="note-filter"><div className="segmented small"><button className={noteMode === 'all' ? 'active' : ''} onClick={() => setNoteMode('all')}>全部解析</button><button className={noteMode === 'page' ? 'active' : ''} onClick={() => setNoteMode('page')}>当前页</button></div><span>{completed} / {noteList.length} 已读完</span></div>
              <div className="note-category-filters"><label>类别<select aria-label="解析类别筛选" value={noteKind} onChange={event => setNoteKind(event.target.value as NoteKind | 'all')}><option value="all">全部类别 ({scopeNotes.length})</option>{noteKindOrder.filter(kind => noteList.some(note => note.kind === kind)).map(kind => <option key={kind} value={kind}>{kindLabels[kind]} ({scopeNotes.filter(note => note.kind === kind).length})</option>)}</select></label><label>核验<select aria-label="解析核验筛选" value={verificationFilter} onChange={event => setVerificationFilter(event.target.value as VerificationStatus | 'all')}><option value="all">全部状态</option>{Object.entries(verificationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div>
              <div className="notes-scroll" ref={notesRef}>
                {showContents && visibleNotes.length > 0 && <nav className="contents" aria-label="解析章节目录"><div className="contents-label">章节目录</div>{visibleNotes.map((note, index) => <button key={note.id} className={paper.progress.active_note_id === note.id ? 'active' : ''} onClick={() => activateNote(note)}><span className={`contents-index ${note.completed ? 'complete' : ''}`}>{note.completed ? <Check size={12} /> : String(index + 1).padStart(2, '0')}</span><span>{note.title}</span><span className="contents-page">{note.page_start === note.page_end ? note.page_start : `${note.page_start}–${note.page_end}`}</span></button>)}</nav>}
                {!visibleNotes.length && <div className="note-empty"><FileText size={28} /><strong>{noteList.length ? '没有符合筛选条件的解析' : '还没有解析'}</strong><div className="button-row">{noteList.length > 0 && <button className="button" onClick={() => { setNoteMode('all'); setNoteKind('all'); setVerificationFilter('all'); }}>重置筛选</button>}<button className="button primary" onClick={() => setModal({ type: 'note', note: null })}><Plus size={15} />新增解析</button></div></div>}
                {noteKindOrder.filter(kind => visibleNotes.some(note => note.kind === kind)).map(kind => <section className="note-kind-section" key={kind} aria-label={kindLabels[kind]}><h2 className="note-group-heading">{kindLabels[kind]}<span>{visibleNotes.filter(note => note.kind === kind).length}</span></h2>{visibleNotes.filter(note => note.kind === kind).map(note => { const Icon = kindIcons[note.kind] || FileText; const associated = note.page_start <= paper.progress.page && note.page_end >= paper.progress.page; return <article id={`note-${note.id}`} data-note-id={note.id} key={note.id} className={`note-article ${paper.progress.active_note_id === note.id ? 'active-note' : ''}`}>
                  <div className="note-meta"><span className={`kind-label kind-${note.kind}`}><Icon size={13} />{kindLabels[note.kind] || '笔记'}</span><span className={`note-verification ${note.verification_status || 'unverified'}`}>{verificationLabels[note.verification_status || 'unverified']}</span><button className={`page-link ${associated ? 'associated' : ''}`} title={`跳转原文第 ${note.page_start} 页`} onClick={() => activateNote(note, true)}>第 {note.page_start}{note.page_end !== note.page_start ? `–${note.page_end}` : ''} 页<ChevronRight size={12} /></button><div className="note-commands"><button className="icon-button" title="编辑解析" aria-label={`编辑${note.title}`} onClick={() => setModal({ type: 'note', note })}><PenLine size={14} /></button><button className="icon-button danger-hover" title="删除解析" aria-label={`删除${note.title}`} onClick={() => askDeleteNote(note)}><Trash2 size={14} /></button></div></div>
                  <div className="note-title"><input type="checkbox" aria-label={`完成${note.title}`} title={note.completed ? '标记为未读完' : '标记为已读完'} checked={note.completed} disabled={busyNotes.has(note.id)} onChange={() => void toggleNote(note)} /><h3><button onClick={() => activateNote(note)}>{note.title}</button></h3></div><Markdown content={note.content} onPage={page => { setSourceHighlight(null); changePage(page); setMobileView('pdf'); }} />
                  {!!note.evidence?.length && <section className="note-evidence-list" aria-label={`${note.title}的原文证据`}><h4><Quote size={13} />原文证据</h4>{note.evidence.map((evidence, index) => <button className="note-evidence-link" key={`${evidence.page}:${index}`} title="定位原文摘录；原句匹配不代表论断正确" onClick={() => locateEvidence(note, evidence, index)}><span><strong>{evidence.label || `证据 ${index + 1}`}</strong><span>第 {evidence.page} 页<ChevronRight size={13} /></span></span><q>{evidence.quote}</q></button>)}</section>}
                </article>; })}</section>)}
              </div></>}
            </section>
            <div className="splitter" role="separator" aria-label="调整解析与原文宽度" aria-orientation="vertical" aria-valuemin={28} aria-valuemax={64} aria-valuenow={split} tabIndex={0} onPointerDown={resizeStart} onKeyDown={(event) => { if (event.key === 'ArrowLeft') { event.preventDefault(); event.stopPropagation(); setSplit((value) => clamp(value - 2, 28, 64)); } if (event.key === 'ArrowRight') { event.preventDefault(); event.stopPropagation(); setSplit((value) => clamp(value + 2, 28, 64)); } }}><span /></div>
            <section className="pdf-pane" aria-label="PDF 原文"><div className="pane-toolbar pdf-toolbar"><div className="page-controls"><button className="icon-button" title="上一页" aria-label="上一页" onClick={() => changePage(paper.progress.page - 1)} disabled={paper.progress.page <= 1}><ChevronLeft size={18} /></button><form onSubmit={(event) => { event.preventDefault(); changePage(Number(pageInput)); }}><input aria-label="PDF 页码" value={pageInput} inputMode="numeric" onChange={(event) => setPageInput(event.target.value.replace(/\D/g, ''))} onBlur={() => { if (pageInput) changePage(Number(pageInput)); else setPageInput(String(paper.progress.page)); }} /><span>/ {paper.page_count}</span></form><button className="icon-button" title="下一页" aria-label="下一页" onClick={() => changePage(paper.progress.page + 1)} disabled={paper.progress.page >= paper.page_count}><ChevronRight size={18} /></button></div><div className="zoom-controls"><button className="icon-button" title="缩小" aria-label="缩小" onClick={() => zoomTo(paper.progress.zoom - 0.1)} disabled={paper.progress.zoom <= 0.25}><ZoomOut size={17} /></button><select title="缩放比例" aria-label="缩放比例" value={String(Number((paper.progress.zoom * 100).toFixed(1)))} onChange={(event) => zoomTo(Number(event.target.value) / 100)}><option value={String(Number((paper.progress.zoom * 100).toFixed(1)))}>{Math.round(paper.progress.zoom * 100)}%</option>{[50, 75, 100, 125, 150, 200].filter((value) => Math.abs(value - paper.progress.zoom * 100) > 0.1).map((value) => <option key={value} value={value}>{value}%</option>)}</select><button className="icon-button" title="放大" aria-label="放大" onClick={() => zoomTo(paper.progress.zoom + 0.1)} disabled={paper.progress.zoom >= 4}><ZoomIn size={17} /></button><button className={`icon-button ${fitWidth ? 'pressed' : ''}`} title="适合宽度" aria-label="适合宽度" onClick={() => { setFitWidth(true); writeStorage(`paper-reader:fit:${paper.id}`, 'true'); }}><Maximize size={17} /></button></div><div className="pdf-extra"><button className={`icon-button ${selectable ? 'pressed' : ''}`} title={selectable ? '关闭文字选择层' : '开启文字选择层'} aria-label="切换文字选择" aria-pressed={selectable} onClick={() => setSelectable(!selectable)}><Highlighter size={16} /></button><a className="icon-button" title="下载 PDF" aria-label="下载 PDF" href={paper.file_url || `/api/papers/${encodeURIComponent(paper.id)}/pdf`} download={paper.file_name}><Download size={17} /></a></div></div>
              <PdfViewer key={paper.id} url={paper.file_url || `/api/papers/${encodeURIComponent(paper.id)}/pdf`} page={paper.progress.page} zoom={paper.progress.zoom} fitWidth={fitWidth} selectable={selectable} highlight={sourceHighlight?.paperId === paper.id && sourceHighlight.page === paper.progress.page ? sourceHighlight : null} onPageCount={(count) => { const id = paper.id; setPaper((current) => current?.id === id && current.page_count !== count ? { ...current, page_count: count } : current); }} onResolvedZoom={(value) => updateReading(paper.id, { zoom: clamp(value, 0.25, 4) })} />
            </section>
          </div>
          <footer className="reader-footer"><span>{paper.short_title || '阅读进度'}<span className="footer-divider" />第 {paper.progress.page} / {paper.page_count} 页</span><div className="reading-progress"><span style={{ width: `${(paper.progress.page / Math.max(1, paper.page_count)) * 100}%` }} /></div><button className={`sync-status ${sync}`} title={sync === 'error' ? '重试保存当前阅读进度' : '阅读进度'} onClick={() => { if (sync === 'error') { updateReading(paper.id, { ...paper.progress, status: paper.status }); void flushProgress(paper.id); } }}>{sync === 'error' ? <CloudOff size={13} /> : sync === 'pending' ? <LoaderCircle size={13} className="spin" /> : <Check size={13} />}{sync === 'error' ? '保存失败，重试' : sync === 'pending' ? '保存中' : '已保存'}</button></footer>
        </>}
      </main>
    </div>
    {modal?.type === 'api-settings' && <ApiSettingsDialog onClose={() => setModal(null)} />}
    {modal?.type === 'library-safety' && <LibrarySafetyDialog onClose={() => setModal(null)} onRestored={async () => { const id = selectedRef.current; deleted.current.clear(); cachedProgress.current.clear(); for (const item of pending.current.values()) clearTimeout(item.timer); pending.current.clear(); await loadLibrary(); if (id) { try { await reloadCurrent(id); } catch { setPaper(null); } } }} />}
    {modal?.type === 'reading-task' && paper && <ReadingTaskDialog key={paper.id} paper={paper} onClose={() => setModal(null)} onImported={async () => { await reloadCurrent(paper.id); setLeftView('notes'); setNotice(''); }} />}
    {notice && <div className="toast" role="status"><span>{notice}</span><button className="icon-button" aria-label="关闭提示" title="关闭提示" onClick={() => setNotice('')}><X size={15} /></button></div>}
    {modal?.type === 'upload' && <UploadDialog categories={categories} initialCategoryIds={currentCategory && !currentCategory.is_default ? [currentCategory.id] : []} onCreateCategory={createCategory} onClose={() => setModal(null)} onUpload={async (form) => { const created = await api<Paper>('/api/papers', { method: 'POST', body: form }); await loadLibrary(); setCategoryId(created.category_ids[0] || 'default'); selectPaper(created.id); setModal(null); setNotice('PDF 已导入并归类'); }} />}
    {modal?.type === 'category-name' && <CategoryNameDialog category={modal.category} onClose={() => setModal(null)} onSave={async (name) => {
      if (modal.category) { const updated = await api<Category>(`/api/categories/${encodeURIComponent(modal.category.id)}`, { method: 'PATCH', body: JSON.stringify({ name }) }); setCategories((current) => current.map((item) => item.id === updated.id ? updated : item)); }
      else { const created = await createCategory(name); selectCategory(created.id); }
      setModal(null);
    }} />}
    {modal?.type === 'paper-categories' && <PaperCategoriesDialog paper={modal.paper} categories={categories} onCreate={createCategory} onClose={() => setModal(null)} onSave={async (ids) => { await api(`/api/papers/${encodeURIComponent(modal.paper.id)}/categories`, { method: 'PUT', body: JSON.stringify({ category_ids: ids }) }); await loadLibrary(); setModal(null); setNotice('文献分类已保存'); }} />}
    {modal?.type === 'category-papers' && <CategoryPapersDialog category={modal.category} papers={papers} onClose={() => setModal(null)} onSave={async (ids) => { await api(`/api/categories/${encodeURIComponent(modal.category.id)}/papers`, { method: 'PUT', body: JSON.stringify({ paper_ids: ids }) }); await loadLibrary(); setModal(null); setNotice('分类文献已保存'); }} />}
    {modal?.type === 'import' && paper && <ImportDialog count={noteList.length} onClose={() => setModal(null)} onImport={async (form) => { const id = paper.id; await flushProgress(id); await api(`/api/papers/${encodeURIComponent(id)}/import`, { method: 'POST', body: form }); await reloadCurrent(id); setModal(null); setNotice('解析已导入'); }} />}
    {modal?.type === 'note' && paper && <NoteEditor key={`${paper.id}:${modal.note?.id || 'new'}`} paperId={paper.id} note={modal.note} page={paper.progress.page} pageCount={paper.page_count} onClose={() => setModal(null)} onRestored={async () => { await reloadCurrent(paper.id); }} onSave={async (input: NoteInput) => { const id = paper.id; if (modal.note) { const result = await api<Note>(`/api/papers/${encodeURIComponent(id)}/notes/${encodeURIComponent(modal.note.id)}`, { method: 'PUT', body: JSON.stringify(input) }); mergeNote(id, result || { ...modal.note, ...input }); } else { await api(`/api/papers/${encodeURIComponent(id)}/notes`, { method: 'POST', body: JSON.stringify({ ...input, sort_order: Math.max(-1, ...noteList.map((note) => note.sort_order)) + 1 }) }); await reloadCurrent(id); } setModal(null); }} />}
    {modal?.type === 'paper' && paper && <PaperDialog paper={paper} onClose={() => setModal(null)} onDelete={() => askDeletePaper(paper)} onSave={async (values) => { await api(`/api/papers/${encodeURIComponent(paper.id)}`, { method: 'PATCH', body: JSON.stringify(values) }); await reloadCurrent(paper.id); setModal(null); }} />}
    {confirm && <Modal title={confirm.title} busy={confirmBusy} onClose={() => { if (!confirmBusy) setConfirm(null); }} className="confirm-modal"><div className="dialog-form"><p className="confirm-message">{confirm.message}</p>{confirmError && <div className="form-error">{confirmError}</div>}<footer className="modal-footer"><span /><div><button className="button" disabled={confirmBusy} onClick={() => setConfirm(null)}>取消</button><button className="button danger" disabled={confirmBusy} onClick={() => void doConfirm()}><Trash2 size={15} />{confirmBusy ? '处理中…' : '确认删除'}</button></div></footer></div></Modal>}
  </div>;
}
