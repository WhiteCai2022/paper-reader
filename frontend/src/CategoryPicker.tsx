import { useState } from 'react';
import { Check, Folder, FolderPlus, LoaderCircle, X } from 'lucide-react';
import { messageOf } from './api';
import type { Category } from './types';

export type CreateCategory = (name: string) => Promise<Category>;

export function CategoryPicker({ categories, value, onChange, disabled = false, onCreate, onBusyChange }: {
  categories: Category[]; value: string[]; onChange: (ids: string[]) => void; disabled?: boolean; onCreate: CreateCategory; onBusyChange: (busy: boolean) => void;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function create() {
    if (!name.trim() || busy || disabled) return;
    setBusy(true); onBusyChange(true); setError('');
    try { const result = await onCreate(name.trim()); onChange([...value, result.id]); setName(''); setCreating(false); }
    catch (failure) { setError(messageOf(failure)); }
    finally { setBusy(false); onBusyChange(false); }
  }
  return <fieldset className="category-picker" disabled={disabled || busy}><legend>分类</legend>
    <div className="category-options">
      <label><input type="checkbox" checked={!value.length} onChange={() => onChange([])} /><Folder size={15} /><span>默认分类</span></label>
      {categories.filter((category) => !category.is_default).map((category) => <label key={category.id}><input type="checkbox" checked={value.includes(category.id)} onChange={(event) => onChange(event.target.checked ? [...value, category.id] : value.filter((id) => id !== category.id))} /><Folder size={15} /><span>{category.name}</span></label>)}
    </div>
    {creating ? <div className="category-create-inline"><input aria-label="新分类名称" autoFocus value={name} maxLength={80} onChange={(event) => setName(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); void create(); } }} /><button type="button" className="icon-button accent" title="确认新建分类" aria-label="确认新建分类" disabled={!name.trim()} onClick={() => void create()}>{busy ? <LoaderCircle size={15} className="spin" /> : <Check size={15} />}</button><button type="button" className="icon-button" title="取消新建分类" aria-label="取消新建分类" onClick={() => { setCreating(false); setError(''); }}><X size={15} /></button></div>
      : <button type="button" className="category-create-command" onClick={() => setCreating(true)}><FolderPlus size={15} />新建分类</button>}
    {error && <div className="form-error" role="alert">{error}</div>}
  </fieldset>;
}
