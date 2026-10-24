import { useId } from 'react';
import { MAX_READING_OUTPUT, MIN_READING_OUTPUT, READING_OUTPUT_PRESETS, resolveReadingOutput } from './readingOutput';

export function ReadingOutput({ value, onChange, recommended, disabled, resume = false, thinking = false }: {
  value: string; onChange: (value: string) => void; recommended: number; disabled: boolean; resume?: boolean; thinking?: boolean;
}) {
  const id = useId();
  const resolved = resolveReadingOutput(value, recommended);
  const preset = value === 'auto' || value === 'original' || READING_OUTPUT_PRESETS.some(limit => String(limit) === value) ? value : 'custom';
  const label = resume ? '续读每阶段输出上限（token）' : '每阶段输出上限（token）';
  return <div className="reading-output">
    <label htmlFor={id}>{label}</label>
    <span className="reading-output-controls">
      <input id={id} aria-label={label} aria-describedby={`${id}-hint`} aria-invalid={Number.isNaN(resolved)} type="number" min={MIN_READING_OUTPUT} max={MAX_READING_OUTPUT} step={1}
        disabled={disabled || resolved === null} value={value === 'auto' ? recommended : value === 'original' ? '' : value}
        placeholder="保留原值" onChange={event => onChange(event.target.value)} />
      <select aria-label={resume ? '续读输出上限预设' : '输出上限预设'} disabled={disabled} value={preset} onChange={event => onChange(event.target.value)}>
        <option value="auto">推荐 {recommended / 1024}K</option>
        {resume && <option value="original">保留原上限</option>}
        {READING_OUTPUT_PRESETS.map(limit => <option key={limit} value={limit}>{limit / 1024}K</option>)}
        <option value="custom" disabled>自定义</option>
      </select>
    </span>
    <small id={`${id}-hint`}>4,096–393,216 token / 阶段{thinking ? '，包含推理与正文' : '，推理已关闭'}。费用按所选上限重新估算。</small>
    {Number.isNaN(resolved) && <span className="form-error" role="alert">请输入范围内的整数输出上限。</span>}
  </div>;
}
