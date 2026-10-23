import { useState } from 'react';
import { Folder, FolderOpen, FolderPlus, Layers, PenLine, Save, Search, Trash2 } from 'lucide-react';
import { messageOf } from './api';
import { Modal } from './Dialogs';
import type { Category, Paper } from './types';
import { CategoryPicker } from './CategoryPicker';
import type { CreateCategory } from './CategoryPicker';

export function CategoryNav({ categories, papers, selected, onSelect, onCreate, onRename, onDelete }: {
  categories: Category[]; papers: Paper[]; selected: string; onSelect: (id: string) => void;
  onCreate: () => void; onRename: (category: Category) => void; onDelete: (category: Category) => void;
}) {
  const groups = [{ id: 'all', name: '全部文献', is_default: false }, { id: 'default', name: '默认分类', is_default: true }, ...categories.filter((item) => !item.is_default)];
  return <nav className="category-nav" aria-label="文献分类">
    <div className="category-heading"><span>分类</span><button className="icon-button" title="新建分类" aria-label="新建分类" onClick={onCreate}><FolderPlus size={16} /></button></div>
    <div className="category-list">{groups.map((category) => {
      const custom = category.id !== 'all' && !category.is_default;
      const original = custom ? categories.find((item) => item.id === category.id)! : null;
      const count = papers.filter((paper) => category.id === 'all' || (category.is_default ? !paper.category_ids?.length : paper.category_ids?.includes(category.id))).length;
      const Icon = category.id === 'all' ? Layers : selected === category.id ? FolderOpen : Folder;
      return <div className={`category-row ${selected === category.id ? 'active' : ''}`} key={category.id} data-category-id={category.id}>
        <button className="category-open" title={category.name} aria-label={`分类：${category.name}`} aria-current={selected === category.id ? 'true' : undefined} onClick={() => onSelect(category.id)}><Icon size={15} /><span>{category.name}</span><small>{count}</small></button>
        {original && <div className="category-actions"><button className="icon-button" title="重命名分类" aria-label={`重命名分类：${category.name}`} onClick={() => onRename(original)}><PenLine size={13} /></button><button className="icon-button danger-hover" title="删除分类，不删除文献" aria-label={`删除分类：${category.name}`} onClick={() => onDelete(original)}><Trash2 size={13} /></button></div>}
      </div>;
    })}</div>
  </nav>;
}

export function CategoryNameDialog({ category, onClose, onSave }: { category: Category | null; onClose: () => void; onSave: (name: string) => Promise<void> }) {
  const [name, setName] = useState(category?.name || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (!name.trim() || busy) return;
    setBusy(true); setError('');
    try { await onSave(name.trim()); } catch (failure) { setError(messageOf(failure)); setBusy(false); }
  }
  return <Modal title={category ? '重命名分类' : '新建分类'} onClose={onClose} busy={busy}><form className="dialog-form" onSubmit={submit}>
    <label>分类名称<input autoFocus required maxLength={80} value={name} onChange={(event) => setName(event.target.value)} disabled={busy} /></label>
    {error && <div className="form-error" role="alert">{error}</div>}
    <footer className="modal-footer"><span /><div><button type="button" className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy || !name.trim()}><Save size={15} />{busy ? '保存中…' : '保存'}</button></div></footer>
  </form></Modal>;
}

export function PaperCategoriesDialog({ paper, categories, onCreate, onClose, onSave }: {
  paper: Paper; categories: Category[]; onCreate: CreateCategory; onClose: () => void; onSave: (ids: string[]) => Promise<void>;
}) {
  const [ids, setIds] = useState(paper.category_ids || []);
  const [busy, setBusy] = useState(false);
  const [categoryBusy, setCategoryBusy] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (busy || categoryBusy) return;
    setBusy(true); setError('');
    try { await onSave(ids); } catch (failure) { setError(messageOf(failure)); setBusy(false); }
  }
  return <Modal title="文献分类" onClose={onClose} busy={busy || categoryBusy}><form className="dialog-form" onSubmit={submit}>
    <div className="category-paper-title">{paper.short_title || paper.title}</div>
    <CategoryPicker categories={categories} value={ids} onChange={setIds} disabled={busy} onCreate={onCreate} onBusyChange={setCategoryBusy} />
    {error && <div className="form-error" role="alert">{error}</div>}
    <footer className="modal-footer"><span /><div><button type="button" className="button" disabled={busy || categoryBusy} onClick={onClose}>取消</button><button className="button primary" disabled={busy || categoryBusy}><Save size={15} />{busy ? '保存中…' : '保存'}</button></div></footer>
  </form></Modal>;
}

export function CategoryPapersDialog({ category, papers, onClose, onSave }: { category: Category; papers: Paper[]; onClose: () => void; onSave: (ids: string[]) => Promise<void> }) {
  const [ids, setIds] = useState(papers.filter((paper) => paper.category_ids?.includes(category.id)).map((paper) => paper.id));
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const visible = papers.filter((paper) => `${paper.title} ${paper.short_title} ${paper.authors}`.toLowerCase().includes(search.trim().toLowerCase()));
  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (busy) return;
    setBusy(true); setError('');
    try { await onSave(ids); } catch (failure) { setError(messageOf(failure)); setBusy(false); }
  }
  return <Modal title="管理分类文献" onClose={onClose} busy={busy} className="category-papers-modal"><form className="dialog-form" onSubmit={submit}>
    <div className="category-paper-title"><FolderOpen size={17} />{category.name}</div>
    <div className="category-paper-search"><Search size={16} /><input aria-label="查找待归类文献" value={search} onChange={(event) => setSearch(event.target.value)} disabled={busy} /></div>
    <div className="category-paper-options">{visible.map((paper) => <label key={paper.id}><input type="checkbox" disabled={busy} checked={ids.includes(paper.id)} onChange={(event) => setIds(event.target.checked ? [...ids, paper.id] : ids.filter((id) => id !== paper.id))} /><span><strong>{paper.short_title || paper.title}</strong><small>{paper.title}</small></span></label>)}{!visible.length && <div className="empty-inline">没有匹配的文献</div>}</div>
    {error && <div className="form-error" role="alert">{error}</div>}
    <footer className="modal-footer"><span className="muted">已选择 {ids.length} 篇</span><div><button type="button" className="button" disabled={busy} onClick={onClose}>取消</button><button className="button primary" disabled={busy}><Save size={15} />{busy ? '保存中…' : '保存'}</button></div></footer>
  </form></Modal>;
}
