import { useEffect, useRef, useState } from 'react';
import { Check, KeyRound, Link2, LoaderCircle, RefreshCw, Unlink } from 'lucide-react';
import { api, messageOf } from './api';
import { Modal } from './Dialogs';

export interface TranslationSettings {
  configured: boolean; model: string; total_budget_cny: number; spent_cny: number;
  remaining_cny: number; reserved_cny: number; uncertain_cny: number;
  key_id: string | null; key_hint: string; key_source: 'local' | 'environment' | null;
  pricing: { input_per_million: number; output_per_million: number; checked_at: string; url: string };
}
interface BalanceInfo { currency: 'CNY' | 'USD'; total_balance: string; granted_balance: string; topped_up_balance: string }
interface AccountBalance {
  status: 'ok' | 'error' | 'unconfigured'; key_id: string | null; is_available: boolean | null;
  balance_infos: BalanceInfo[]; checked_at: string | null; error: string;
}
const balanceMoney = (value: string, currency: BalanceInfo['currency']) => `${currency === 'CNY' ? '¥' : 'US$'}${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;

export function ApiBalance({ settings, detailed = false, onBind, refreshToken }: { settings: TranslationSettings; detailed?: boolean; onBind?: () => void; refreshToken?: string }) {
  const [value, setValue] = useState<AccountBalance | null>(null);
  const [loading, setLoading] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const previousToken = useRef(refreshToken);
  const currentKey = useRef(settings.key_id); currentKey.current = settings.key_id;
  async function load(refresh = false) {
    controller.current?.abort();
    if (!settings.configured) { setValue(null); setLoading(false); return; }
    const request = new AbortController(); controller.current = request; setLoading(true);
    try {
      const result = await api<AccountBalance>(`/api/translation/balance?refresh=${refresh}`, { signal: request.signal });
      if (!request.signal.aborted && currentKey.current === result.key_id) setValue(result);
    } catch (failure) {
      if (!request.signal.aborted && currentKey.current === settings.key_id) setValue({ status: 'error', key_id: settings.key_id, is_available: null, balance_infos: [], checked_at: null, error: messageOf(failure) });
    } finally { if (!request.signal.aborted) setLoading(false); }
  }
  useEffect(() => {
    setValue(null); void load();
    return () => controller.current?.abort();
  }, [settings.key_id, settings.configured]);
  useEffect(() => {
    if (previousToken.current && previousToken.current !== refreshToken) void load(true);
    previousToken.current = refreshToken;
  }, [refreshToken]);
  const balance = value?.key_id === settings.key_id ? value : null;
  const checked = balance?.checked_at ? `上次查询 ${new Date(balance.checked_at).toLocaleString('zh-CN')}；点击刷新获取最新余额` : '查询当前绑定 Key 所属 DeepSeek 账户余额';
  return <div className="api-balance" data-balance-status={!settings.configured ? 'unconfigured' : balance?.status || 'loading'}>
    <div className="api-balance-row"><span>API 账户余额</span><strong title={checked}>{!settings.configured ? '未绑定' : balance?.status === 'ok' ? balance.balance_infos.map(item => <span key={item.currency}>{balanceMoney(item.total_balance, item.currency)}</span>) : loading ? '查询中…' : '暂不可用'}</strong>
      {settings.configured ? <button type="button" className="icon-button" aria-label="刷新 API 余额" title={checked} disabled={loading} onClick={() => void load(true)}><RefreshCw size={14} className={loading ? 'spin' : ''} /></button> : onBind && <button type="button" className="button api-bind-shortcut" onClick={onBind}><KeyRound size={14} />绑定 API Key</button>}
    </div>
    {balance?.status === 'error' && <p className="api-balance-error" role="status">{balance.error}</p>}
    {balance?.status === 'ok' && balance.is_available === false && <p className="api-balance-error">当前账户余额不可用于 API 调用。</p>}
    {detailed && balance?.status === 'ok' && <div className="api-balance-detail">{balance.balance_infos.map(item => <span key={item.currency}>{item.currency} · 赠送 {balanceMoney(item.granted_balance, item.currency)} · 充值 {balanceMoney(item.topped_up_balance, item.currency)}</span>)}<span>{balance.checked_at && `更新于 ${new Date(balance.checked_at).toLocaleString('zh-CN')}`}</span></div>}
  </div>;
}

export function ApiSettingsDialog({ initialSettings, onClose, onSaved }: { initialSettings?: TranslationSettings; onClose: () => void; onSaved?: () => Promise<void> }) {
  const [settings, setSettings] = useState<TranslationSettings | null>(initialSettings || null);
  const [key, setKey] = useState('');
  const [budget, setBudget] = useState(initialSettings?.total_budget_cny || 0);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(!initialSettings);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  async function refresh() {
    setLoading(true); setError('');
    try { const data = await api<TranslationSettings>('/api/translation/settings'); setSettings(data); setBudget(data.total_budget_cny); }
    catch (failure) { setError(messageOf(failure)); } finally { setLoading(false); }
  }
  useEffect(() => { void refresh(); }, []);
  async function update(values: { api_key?: string; total_budget_cny?: number }, message: string) {
    setBusy(true); setError(''); setNotice('');
    try {
      const data = await api<TranslationSettings>('/api/translation/settings', { method: 'PATCH', body: JSON.stringify(values) });
      setSettings(data); setKey(''); setNotice(message);
      window.dispatchEvent(new Event('paper-reader:api-settings-changed'));
      if (values.total_budget_cny !== undefined) setBudget(data.total_budget_cny);
      await onSaved?.();
    } catch (failure) { setError(messageOf(failure)); } finally { setBusy(false); }
  }
  return <Modal title="API 设置" busy={busy} onClose={onClose}><div className="dialog-form api-settings-form">
    {loading && !settings && <div className="empty-inline"><LoaderCircle size={20} className="spin" />正在读取设置</div>}
    {settings && <>
      <div className="api-binding-status"><KeyRound size={17} /><strong>{settings.configured ? `已绑定 ${settings.key_hint}` : '尚未绑定 API Key'}</strong>{settings.configured && <button type="button" className="icon-button danger-hover" title="解除 API Key 绑定" aria-label="解除 API Key 绑定" disabled={busy} onClick={() => void update({ api_key: '' }, '已解除绑定')}><Unlink size={16} /></button>}</div>
      <form onSubmit={event => { event.preventDefault(); if (key.trim()) void update({ api_key: key.trim() }, 'API Key 绑定成功'); }}>
        <label className="api-key-field">DeepSeek API Key<input aria-label="DeepSeek API Key" type="password" autoComplete="new-password" value={key} onChange={event => setKey(event.target.value)} placeholder={settings.configured ? '输入新 Key 以更换绑定' : '输入 API Key'} disabled={busy} /></label>
        <div className="api-bind-action"><span>验证通过后加密保存</span><button type="submit" className="button primary" disabled={busy || !key.trim()}>{busy ? <LoaderCircle className="spin" size={15} /> : <Link2 size={15} />}验证并绑定</button></div>
      </form>
      <div className="api-settings-balance"><ApiBalance settings={settings} detailed /></div>
      <p className="translation-help">余额由 DeepSeek 官方接口返回，属于当前 Key 对应的账户。更换绑定不会删除论文或已有译文。</p>
      <details className="api-budget-settings"><summary>费用控制</summary><form onSubmit={event => { event.preventDefault(); void update({ total_budget_cny: budget }, '支出上限已保存'); }}>
        <label>本程序累计支出上限（元）<input aria-label="本程序累计支出上限（元）" type="number" min={0} max={1000} step="0.5" required value={budget} onChange={event => setBudget(Number(event.target.value))} disabled={busy} /></label>
        <div className="translation-cost-list"><span>本程序已记账<strong>¥{settings.spent_cny.toFixed(4)}</strong></span><span>任务预留<strong>¥{settings.reserved_cny.toFixed(4)}</strong></span></div>
        <p className="translation-help">支出上限约束本程序的翻译和 API 精读调用，与账户真实余额分别计算。费用按高峰价保守记账，实际扣费以官方账单为准。</p>
        {settings.uncertain_cny > 0 && <p className="translation-help">请求中断后的保守记账金额：¥{settings.uncertain_cny.toFixed(4)}。</p>}
        <button className="button" disabled={busy}><Check size={15} />保存支出上限</button>
      </form></details>
    </>}
    {notice && <div className="api-settings-notice" role="status"><Check size={15} />{notice}</div>}
    {error && <div className="form-error" role="alert">{error}</div>}
    {!settings && error && <button type="button" className="button" onClick={() => void refresh()}><RefreshCw size={14} />重试</button>}
    <footer className="modal-footer"><span className="muted">密钥仅在本机后端加密保存</span><button type="button" className="button" disabled={busy} onClick={onClose}>完成</button></footer>
  </div></Modal>;
}
