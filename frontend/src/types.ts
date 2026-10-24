export type NoteKind = 'guide' | 'concept' | 'method' | 'experiment' | 'critique' | 'exercise' | 'note';
export type VerificationStatus = 'unverified' | 'verified' | 'needs_review';
export interface NoteEvidence { page: number; quote: string; label: string }
export interface Note {
  id: string;
  title: string;
  page_start: number;
  page_end: number;
  kind: NoteKind;
  content: string;
  sort_order: number;
  completed: boolean;
  evidence: NoteEvidence[];
  verification_status: VerificationStatus;
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
  guide: '整篇总览', concept: '概念', method: '方法', experiment: '实验', critique: '评析', exercise: '旧版笔记', note: '个人笔记',
};
export const verificationLabels: Record<VerificationStatus, string> = {
  unverified: '未核验', verified: '已核验', needs_review: '待复核',
};
