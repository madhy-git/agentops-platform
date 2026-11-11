// A deliberately tiny Markdown renderer for model answers: paragraphs, "- " / "1. " lists and **bold**.
//
// LEARNING NOTES
// - It builds React elements; it never uses dangerouslySetInnerHTML. Model output is untrusted text (it can be
//   steered by retrieved documents), so if a model ever writes "<img src=x onerror=...>", it is shown as text,
//   not run. A full Markdown library would need a sanitiser to give the same guarantee.
// - Inline citations like [POL-FAQ-01#1] are removed from the prose; the chat shows them as source chips.
import type { ReactNode } from "react";

const CITE = /\s*\[([A-Z]+-[A-Z]+-\d+#\d+)\]/g;

function inline(text: string, key: string): ReactNode[] {
  // Split on **bold** spans; odd indexes are the bold parts.
  return text
    .replace(CITE, "")
    .split(/\*\*(.+?)\*\*/g)
    .map((part, i) => (i % 2 ? <strong key={`${key}-${i}`}>{part}</strong> : part));
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let para: string[] = [];
  const flushPara = () => {
    if (para.length) blocks.push(<p key={`p${blocks.length}`}>{inline(para.join(" "), `p${blocks.length}`)}</p>);
    para = [];
  };
  const flushList = () => {
    if (!list) return;
    const k = `l${blocks.length}`;
    const items = list.items.map((it, i) => <li key={`${k}-${i}`}>{inline(it, `${k}-${i}`)}</li>);
    blocks.push(
      list.ordered ? (
        <ol key={k} className="list-decimal space-y-1 pl-5">{items}</ol>
      ) : (
        <ul key={k} className="list-disc space-y-1 pl-5">{items}</ul>
      ),
    );
    list = null;
  };

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = /^[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\d+[.)]\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      flushPara();
      const ordered = !!numbered;
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push((bullet ?? numbered)![1]!);
    } else if (line === "") {
      flushPara();
      flushList();
    } else {
      flushList();
      para.push(line.replace(/^#+\s*/, "")); // headings render as plain paragraph text
    }
  }
  flushPara();
  flushList();
  return <div className="space-y-2">{blocks}</div>;
}
