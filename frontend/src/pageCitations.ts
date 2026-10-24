interface CitationNode { type: string; value?: string; children?: CitationNode[]; url?: string }

export function splitPageCitations(text: string): CitationNode[] {
  const nodes: CitationNode[] = [];
  const pattern = /\[(?:p|pp)\.\s*(\d+)(?:\s*[-\u2013\u2014]\s*\d+)?\]/gi;
  let start = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index!;
    const page = Number(match[1]);
    if (!Number.isSafeInteger(page) || page < 1) continue;
    if (index > start) nodes.push({ type: 'text', value: text.slice(start, index) });
    nodes.push({ type: 'link', url: `#page=${page}`, children: [{ type: 'text', value: match[0] }] });
    start = index + match[0].length;
  }
  if (start < text.length || !nodes.length) nodes.push({ type: 'text', value: text.slice(start) });
  return nodes;
}

export function remarkPageCitations() {
  return (tree: CitationNode) => {
    const visit = (node: CitationNode) => {
      if (!node.children || ['link', 'linkReference', 'code', 'inlineCode', 'math', 'inlineMath'].includes(node.type)) return;
      node.children = node.children.flatMap(child => {
        if (child.type === 'text' && child.value) return splitPageCitations(child.value);
        visit(child);
        return [child];
      });
    };
    visit(tree);
  };
}
