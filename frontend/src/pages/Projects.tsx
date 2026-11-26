import { FolderKanban, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useCreate } from "@/components/dialogs";
import { Badge, Button, Empty, PageHeader, Panel, PriorityMark, Progress, Segmented, Skeleton } from "@/components/ui";
import { dateShort, PROJECT_STATUS, relDay } from "@/lib/format";
import { useProjects } from "@/hooks/queries";

const PRESETS = ["LBS", "MOSI.MEDIA", "TM Sailing", "TSVH Wassersport", "Private Projekte"];

export default function Projects() {
  const [status, setStatus] = useState<"open" | "completed" | "archived">("open");
  const projects = useProjects(status);
  const all = useProjects();
  const create = useCreate();
  const existing = new Set((all.data ?? []).map((p) => p.name.toLowerCase()));
  const missing = PRESETS.filter((p) => !existing.has(p.toLowerCase()));
  return (
    <div>
      <PageHeader title="Projekte" actions={<Button variant="primary" onClick={() => create.newProject()}><Plus className="h-4 w-4" />Neues Projekt</Button>} />
      <Segmented value={status} onChange={setStatus} className="mb-4" options={[{ value: "open", label: "Laufend" }, { value: "completed", label: "Abgeschlossen" }, { value: "archived", label: "Archiv" }]} />
      {projects.isLoading ? <Skeleton className="h-64" /> : !projects.data?.length ? (
        <Panel><Empty icon={FolderKanban} title="Keine Projekte" text="Lege dein erstes Projekt an – oder lass MOSI im Assistenten einen Projektplan erstellen." /></Panel>
      ) : (
        <Panel bodyClassName="divide-y divide-line/70">
          <div className="hidden md:grid grid-cols-[minmax(0,1fr)_110px_160px_90px_110px] gap-4 px-4 h-9 items-center text-xs text-ink-3"><span>Projekt</span><span>Status</span><span>Fortschritt</span><span className="text-right">Offen</span><span className="text-right">Deadline</span></div>
          {projects.data.map((p) => (
            <Link key={p.id} to={`/projekte/${p.id}`} className="grid grid-cols-[minmax(0,1fr)_auto] md:grid-cols-[minmax(0,1fr)_110px_160px_90px_110px] gap-x-4 gap-y-2 px-4 py-3 items-center hover:bg-raised/60">
              <div className="min-w-0 flex items-center gap-2.5"><span className="h-2.5 w-2.5 rounded-[3px] shrink-0" style={{ background: p.color }} /><span className="truncate text-base text-ink">{p.name}</span><PriorityMark priority={p.priority} /></div>
              <div><Badge tone={p.status === "active" ? "accent" : p.status === "completed" ? "ok" : "neutral"}>{PROJECT_STATUS[p.status]}</Badge></div>
              <div className="flex items-center gap-2 col-span-2 md:col-span-1"><Progress value={p.progress} /><span className="text-xs text-ink-3 tnum w-9 text-right">{p.progress} %</span></div>
              <div className="hidden md:block text-sm text-right tnum">{p.task_open}{p.task_overdue > 0 && <span className="text-danger"> · {p.task_overdue} überfällig</span>}</div>
              <div className="hidden md:block text-sm text-ink-3 text-right tnum">{p.deadline ? relDay(p.deadline) : "–"}</div>
            </Link>
          ))}
        </Panel>
      )}
      {status === "open" && missing.length > 0 && (
        <div className="mt-6">
          <div className="text-sm text-ink-3 mb-2">Schnell anlegen</div>
          <div className="flex flex-wrap gap-2">{missing.map((n) => <Button key={n} size="sm" variant="subtle" onClick={() => create.newProject(n)}><Plus className="h-3.5 w-3.5" />{n}</Button>)}</div>
        </div>
      )}
      <span className="hidden">{dateShort(new Date())}</span>
    </div>
  );
}
