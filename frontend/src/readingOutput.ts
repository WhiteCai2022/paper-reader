export const MIN_READING_OUTPUT = 4096;
export const MAX_READING_OUTPUT = 393216;
export const READING_OUTPUT_PRESETS = [16384, 32768, 65536, 131072, 262144, 393216];

export function recommendedReadingOutput(effort: string): number {
  return effort === 'max' ? 262144 : effort === 'high' ? 131072 : 65536;
}

export function resolveReadingOutput(value: string, recommended: number): number | null {
  if (value === 'original') return null;
  if (value === 'auto') return recommended;
  if (!/^\d+$/.test(value)) return NaN;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= MIN_READING_OUTPUT && parsed <= MAX_READING_OUTPUT ? parsed : NaN;
}

export function matchesReadingOutput(quoted: number | null | undefined, selected: number | null): boolean {
  return quoted !== undefined && quoted === selected;
}
