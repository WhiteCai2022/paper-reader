import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

export function normalizeMath(content: string): string {
  return content.split(/(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/g).map((part, index) => {
    if (index % 2) return part;
    return part.replace(/\\\[([\s\S]*?)\\\]/g, (_match, body: string) => `\n$$\n${body}\n$$\n`)
      .replace(/\\\(([\s\S]*?)\\\)/g, (_match, body: string) => `$${body}$`);
  }).join('');
}

export function Markdown({ content, onPage }: { content: string; onPage?: (page: number) => void }) {
  return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} skipHtml
    components={{ a: ({ href, children }) => {
      const page = href?.match(/(?:#|[?&])page=(\d+)/)?.[1];
      if (page && onPage) return <button className="inline-link" onClick={() => onPage(Number(page))}>{children}</button>;
      return <a href={href} target="_blank" rel="noreferrer">{children}</a>;
    } }}
  >{normalizeMath(content)}</ReactMarkdown></div>;
}
