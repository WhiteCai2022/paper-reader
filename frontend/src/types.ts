export type NoteKind = 'guide' | 'concept' | 'method' | 'experiment' | 'critique' | 'exercise' | 'note';
export interface Note {
  id: string;
  title: string;
  page_start: number;
  page_end: number;
  kind: NoteKind;
  content: string;
  sort_order: number;
  completed: boolean;
}
export type NoteInput = Omit<Note, 'id'>;
export interface ReadingProgress { page: number; zoom: number; active_note_id: string | null }
export interface Paper {
  id: string;
  title: string;
  short_title: string;
  authors: string;
  venue: string;
  year: number | null;
  doi: string;
  tags: string[];
  page_count: number;
  file_name: string;
  file_url: string;
  notes_count: number;
  status: 'unread' | 'reading' | 'done';
  progress: ReadingProgress;
  notes?: Note[];
  category_ids: string[];
}
export interface Category { id: string; name: string; paper_count: number; is_default: boolean }
export interface MetadataPreview {
  title: string;
  authors: string;
  venue: string;
  year: number | null;
  doi: string;
  page_count: number | null;
  sources: Record<string, 'pdf' | 'xmp' | 'first_page' | 'filename' | 'crossref'>;
  warnings: string[];
}
export const kindLabels: Record<NoteKind, string> = {
  guide: '导读', concept: '概念', method: '方法', experiment: '实验', critique: '评析', exercise: '旧版笔记', note: '笔记',
};
