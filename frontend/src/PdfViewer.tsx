import { useEffect, useRef, useState } from 'react';
import { FileWarning, LoaderCircle, MessageSquare, MessageSquarePlus, RotateCw } from 'lucide-react';
import { getDocument, GlobalWorkerOptions, TextLayer } from 'pdfjs-dist';
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { messageOf } from './api';
import { matchSourceRanges } from './pdfAlignment';
import type { SourceHighlight } from './pdfAlignment';
import { selectedPdfText } from './pdfSelection';
import type { PdfAnnotation, TextAnchor } from './types';

GlobalWorkerOptions.workerSrc = workerUrl;

interface Props {
  url: string;
  page: number;
  zoom: number;
  fitWidth: boolean;
  selectable: boolean;
  highlight?: SourceHighlight | null;
  annotations: PdfAnnotation[];
  activeAnnotationId: string | null;
  onAnnotate: (anchor: TextAnchor) => void;
  onSelectAnnotation: (annotation: PdfAnnotation) => void;
  onPageCount: (count: number) => void;
  onResolvedZoom: (zoom: number) => void;
}

export function PdfViewer({ url, page, zoom, fitWidth, selectable, highlight, annotations, activeAnnotationId, onAnnotate, onSelectAnnotation, onPageCount, onResolvedZoom }: Props) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [rendering, setRendering] = useState(false);
  const [retry, setRetry] = useState(0);
  const [width, setWidth] = useState(600);
  const [layerRevision, setLayerRevision] = useState(0);
  const [rectangles, setRectangles] = useState<{ left: number; top: number; width: number; height: number }[]>([]);
  const [unmatched, setUnmatched] = useState(false);
  const [selection, setSelection] = useState<{ anchor: TextAnchor; left: number; top: number } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onPageCount, onResolvedZoom });
  callbacks.current = { onPageCount, onResolvedZoom };

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(160, entry.contentRect.width - 40)));
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let disposed = false;
    setLoading(true); setError(''); setDocument(null);
    const task = getDocument({ url, cMapUrl: '/pdfjs/cmaps/', cMapPacked: true,
      standardFontDataUrl: '/pdfjs/standard_fonts/', wasmUrl: '/pdfjs/wasm/' });
    task.promise.then((pdf) => {
      if (disposed) { void pdf.destroy(); return; }
      setDocument(pdf); callbacks.current.onPageCount(pdf.numPages); setLoading(false);
    }).catch((failure) => { if (!disposed) { setError(messageOf(failure)); setLoading(false); } });
    return () => { disposed = true; void task.destroy(); };
  }, [url, retry]);

  useEffect(() => {
    if (!document || !canvasRef.current || !pageRef.current || !textRef.current) return;
    let disposed = false;
    let task: RenderTask | null = null;
    let layer: TextLayer | null = null;
    const canvas = canvasRef.current;
    const textContainer = textRef.current;
    const pageContainer = pageRef.current;
    setRendering(true); setError('');
    canvas.style.visibility = 'hidden'; textContainer.replaceChildren(); setRectangles([]); setUnmatched(false);
    document.getPage(Math.max(1, Math.min(page, document.numPages))).then(async (pdfPage) => {
      if (disposed) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const scale = fitWidth ? Math.min(3, Math.max(0.25, width / base.width)) : zoom;
      if (fitWidth && Math.abs(scale - zoom) > 0.005) callbacks.current.onResolvedZoom(Number(scale.toFixed(3)));
      const viewport = pdfPage.getViewport({ scale });
      const density = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(viewport.width * density); canvas.height = Math.floor(viewport.height * density);
      canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`;
      pageContainer.style.width = `${viewport.width}px`; pageContainer.style.height = `${viewport.height}px`;
      pageContainer.style.setProperty('--scale-factor', String(scale));
      pageContainer.style.setProperty('--total-scale-factor', String(scale));
      const context = canvas.getContext('2d', { alpha: false });
      if (!context) throw new Error('无法创建 PDF 画布');
      task = pdfPage.render({ canvas, canvasContext: context, viewport,
        transform: density === 1 ? undefined : [density, 0, 0, density, 0, 0] });
      await task.promise;
      if (disposed) return;
      canvas.style.visibility = 'visible'; setRendering(false);
      const textContent = await pdfPage.getTextContent();
      if (disposed) return;
      // Match PDF.js's measurement language, not the Chinese application's generic serif font.
      textContent.lang ||= 'en';
      textContainer.lang = textContent.lang;
      layer = new TextLayer({ textContentSource: textContent, container: textContainer, viewport });
      await layer.render();
      if (!disposed) setLayerRevision(value => value + 1);
    }).catch((failure) => {
      if (!disposed && failure?.name !== 'RenderingCancelledException') { setError(messageOf(failure)); setRendering(false); }
    });
    return () => { disposed = true; task?.cancel(); layer?.cancel(); };
  }, [document, page, zoom, fitWidth, width]);

  useEffect(() => {
    setRectangles([]); setUnmatched(false);
    if (!highlight || highlight.page !== page || highlight.wholePage || !textRef.current || !pageRef.current) return;
    const container = textRef.current, sheet = pageRef.current;
    const walker = window.document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const nodes: { node: Text; start: number; end: number }[] = [];
    let text = '', next: Node | null;
    while ((next = walker.nextNode())) {
      const start = text.length;
      text += next.textContent || '';
      nodes.push({ node: next as Text, start, end: text.length });
    }
    if (!nodes.length) return;
    const matches = matchSourceRanges(text, highlight.sourceText);
    const bounds = sheet.getBoundingClientRect();
    const boxes: typeof rectangles = [];
    for (const match of matches) {
      // Cross-span ranges also include transformed element boxes, which can bleed into another column.
      for (const item of nodes) {
        if (item.end <= match.start || item.start >= match.end) continue;
        const range = window.document.createRange();
        range.setStart(item.node, Math.max(0, match.start - item.start));
        range.setEnd(item.node, Math.min(item.end, match.end) - item.start);
        for (const rect of Array.from(range.getClientRects())) {
          if (rect.width < 1 || rect.height < 1) continue;
          const left = Math.max(0, rect.left - bounds.left), top = Math.max(0, rect.top - bounds.top);
          const width = Math.min(rect.right - bounds.left, bounds.width) - left;
          const height = Math.min(rect.bottom - bounds.top, bounds.height) - top;
          if (width > 0 && height > 0) boxes.push({ left, top, width, height });
        }
      }
    }
    setRectangles(boxes); setUnmatched(!boxes.length);
    if (boxes.length && scrollRef.current && scrollRef.current.clientHeight) {
      const scroll = scrollRef.current;
      const target = sheet.offsetTop + Math.min(...boxes.map(box => box.top));
      const bottom = sheet.offsetTop + Math.max(...boxes.map(box => box.top + box.height));
      if (target < scroll.scrollTop + 18 || bottom > scroll.scrollTop + scroll.clientHeight - 18) {
        scroll.scrollTo({ top: Math.max(0, target - 60), behavior: 'auto' });
      }
    }
  }, [highlight, page, url, layerRevision]);

  useEffect(() => { scrollRef.current?.scrollTo({ top: 0, left: 0 }); }, [page, url]);

  useEffect(() => {
    setSelection(null);
    if (!selectable || rendering) return;
    let timer: ReturnType<typeof setTimeout>;
    const capture = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const layer = textRef.current, sheet = pageRef.current;
        const anchor = layer && sheet ? selectedPdfText(layer, sheet, page) : null;
        if (!anchor || !sheet) { setSelection(null); return; }
        const bounds = sheet.getBoundingClientRect(), last = anchor.rects[anchor.rects.length - 1];
        setSelection({ anchor, left: Math.max(8, Math.min(window.innerWidth - 110, bounds.left + last.x * bounds.width)),
          top: Math.max(8, Math.min(window.innerHeight - 48, bounds.top + (last.y + last.height) * bounds.height + 6)) });
      }, 160);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { clearTimeout(timer); setSelection(null); } };
    window.document.addEventListener('selectionchange', capture);
    window.document.addEventListener('keydown', escape);
    return () => { clearTimeout(timer); window.document.removeEventListener('selectionchange', capture); window.document.removeEventListener('keydown', escape); };
  }, [selectable, rendering, page, url, zoom, layerRevision]);

  useEffect(() => {
    const item = annotations.find(value => value.id === activeAnnotationId && value.page === page);
    if (!item || !pageRef.current || !scrollRef.current) return;
    const target = pageRef.current.offsetTop + item.rects[0].y * pageRef.current.clientHeight;
    scrollRef.current.scrollTo({ top: Math.max(0, target - 80), behavior: 'auto' });
  }, [activeAnnotationId, annotations, page, layerRevision]);

  return <div className="pdf-scroll" ref={scrollRef} aria-label={`PDF 第 ${page} 页`} onScroll={() => setSelection(null)}>
    {loading && <div className="surface-state"><LoaderCircle className="spin" size={26} /><span>正在载入原文</span></div>}
    {error && <div className="pdf-error"><FileWarning size={25} /><strong>原文载入失败</strong><p>{error}</p>
      <button className="button" onClick={() => setRetry((value) => value + 1)}><RotateCw size={15} />重试</button></div>}
    {!loading && document && !error && <div className="pdf-sheet" ref={pageRef}>
      <canvas ref={canvasRef} />
      <div className="textLayer" ref={textRef} style={{ pointerEvents: selectable ? undefined : 'none', userSelect: selectable ? undefined : 'none' }} />
      <div className={`pdf-source-highlights ${highlight?.wholePage && highlight.page === page ? 'whole-page-reference' : ''}`} aria-hidden="true">
        {rectangles.map((rect, index) => <span key={index} style={rect} />)}
      </div>
      {!rendering && <div className="pdf-annotation-highlights">
        {annotations.filter(item => item.page === page).map(item => <div className={activeAnnotationId === item.id ? 'active' : ''} key={item.id}>
          {item.rects.map((rect, index) => <span aria-hidden="true" key={index} style={{ left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.width * 100}%`, height: `${rect.height * 100}%` }} />)}
          <button className="pdf-annotation-marker" style={{ top: `min(calc(100% - 28px), ${item.rects[0].y * 100}%)` }} title={item.content.slice(0, 200)} aria-label={`查看第 ${item.page} 页批注：${item.content.slice(0, 60)}`} onClick={() => onSelectAnnotation(item)}><MessageSquare size={14} /></button>
        </div>)}
      </div>}
      {unmatched && <div className="pdf-alignment-status" role="status">此段原文暂无法精确定位</div>}
      {rendering && <div className="page-loading"><LoaderCircle className="spin" size={22} /></div>}
    </div>}
    {selection && <button className="button pdf-selection-action" style={{ left: selection.left, top: selection.top }} title="添加批注" aria-label="添加批注" onPointerDown={event => event.preventDefault()} onClick={() => { onAnnotate(selection.anchor); setSelection(null); window.getSelection()?.removeAllRanges(); }}><MessageSquarePlus size={16} />批注</button>}
    {!loading && document && <div className="page-caption">{page} / {document.numPages}</div>}
  </div>;
}
