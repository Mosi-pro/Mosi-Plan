/** Minimaler, sicherer Markdown-Renderer (ohne HTML-Injektion). */
import { Fragment, type ReactNode } from "react";

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**")) out.push(<strong key={`${key}-${i++}`} className="font-semibold text-ink">{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={`${key}-${i++}`} className="rounded-sm bg-raised px-1 text-[0.92em]">{t.slice(1, -1)}</code>);
    else out.push(<em key={`${key}-${i++}`}>{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r/g, "").split("\n");
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const L = list.ordered ? "ol" : "ul";
    blocks.push(
      <L key={`l${blocks.length}`} className={list.ordered ? "list-decimal pl-5 space-y-1" : "list-disc pl-5 space-y-1 marker:text-ink-3"}>
        {list.items.map((it, i) => <li key={i}>{inline(it, `li${blocks.length}-${i}`)}</li>)}
      </L>,
    );
    list = null;
  };
  let para: string[] = [];
  const flushPara = () => {
    if (para.length) blocks.push(<p key={`p${blocks.length}`}>{para.map((l, i) => <Fragment key={i}>{i > 0 && <br />}{inline(l, `p${blocks.length}-${i}`)}</Fragment>)}</p>);
    para = [];
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const ul = /^\s*[-*•]\s+(.*)$/.exec(line);
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const h = /^#{1,4}\s+(.*)$/.exec(line);
    if (ul || ol) {
      flushPara();
      const ordered = !!ol;
      if (list && list.ordered !== ordered) flush();
      list = list ?? { ordered, items: [] };
      list.items.push((ul ?? ol)![1]);
    } else if (h) {
      flushPara(); flush();
      blocks.push(<p key={`h${blocks.length}`} className="font-semibold text-ink">{inline(h[1], `h${blocks.length}`)}</p>);
    } else if (!line.trim()) {
      flushPara(); flush();
    } else {
      flush();
      para.push(line);
    }
  }
  flushPara(); flush();
  return <div className={className ?? "space-y-2.5 leading-relaxed"}>{blocks}</div>;
}
