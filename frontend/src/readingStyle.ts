export function readingStyleLabel(value: { reading_style?: string; workflow?: string; stages: { kind: string }[] }): string {
  if (value.reading_style === 'learning-tutor-v1') return '学习式全文精读';
  return value.workflow === 'whole-paper-topics-v1' || (!value.workflow && !value.stages.some(stage => stage.kind === 'detail'))
    ? '全文主题精读（原规则）' : '旧版分段精读';
}
