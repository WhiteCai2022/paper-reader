export interface AiOptions { model: string; reasoning_effort: string }
export const models = [{ id: 'deepseek-flash', label: 'DeepSeek Flash' }, { id: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro' }];
export const efforts = [{ id: 'none', label: '关闭（省费）' }, { id: 'low', label: '低' }, { id: 'high', label: '高' }, { id: 'max', label: '最高' }];
export const configLabel = (model: string, effort: string) => `${model === 'deepseek-v4-pro' ? 'V4 Pro' : 'Flash'} · ${effort === 'none' ? '关闭推理' : `${efforts.find(item => item.id === effort)?.label || effort}强度推理`}`;

export function OptionsFields({ options, onChange, disabled = false }: { options: AiOptions; onChange: (value: AiOptions) => void; disabled?: boolean }) {
  return <div className="translation-options"><label>模型<select aria-label="模型" value={options.model} disabled={disabled} onChange={event => onChange({ ...options, model: event.target.value })}>{models.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label><label>推理强度<select aria-label="推理强度" value={options.reasoning_effort} disabled={disabled} onChange={event => onChange({ ...options, reasoning_effort: event.target.value })}>{efforts.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label></div>;
}
