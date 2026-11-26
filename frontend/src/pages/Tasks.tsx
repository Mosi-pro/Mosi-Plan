import { useQuery } from "@tanstack/react-query";
import { CheckSquare, Plus, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useCreate } from "@/components/dialogs";
import { TaskRow } from "@/components/task-row";
import { Button, Empty, Input, PageHeader, Panel, Segmented, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import type { Task } from "@/lib/types";
import { useProjects, useTasks } from "@/hooks/queries";

type F = "aktiv" | "heute" | "ueberfaellig" | "woche" | "erledigt" | "alle";

export default function Tasks() {
  const [params, setParams] = useSearchParams();
  const filter = (params.get("filter") as F) || "aktiv";
  const [q, setQ] = useState("");
  const [project, setProject] = useState("");
  const create = useCreate();
  const projects = useProjects();
  const today = new Date().toISOString().slice(0, 10);
  const weekEnd = new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10);
  const query: Record<string, string | number | undefined> = {
    status: filter === "erledigt" ? "done" : filter === "alle" ? undefined : "active",
    due_before: filter === "heute" ? today : filter === "woche" ? weekEnd : undefined,
    project_id: project ? Number(project) : undefined,
  };
  const tasks = useTasks(query);
  const deep = params.get("aufgabe");
  const deepTask = useQuery({ queryKey: ["task", deep], queryFn: () => api.get<{ task: Task }>(`/api/tasks/${deep}`), enabled: !!deep });
  useEffect(() => { if (deepTask.data) { create.editTask(deepTask.data.task); const n = new URLSearchParams(params); n.delete("aufgabe"); setParams(n, { replace: true }); } }, [deepTask.data]); // eslint-disable-line

  const list = useMemo(() => {
    let l = tasks.data ?? [];
    if (filter === "ueberfaellig") l = l.filter((t) => t.overdue);
    if (q.trim()) l = l.filter((t) => t.title.toLowerCase().includes(q.toLowerCase()) || t.description.toLowerCase().includes(q.toLowerCase()));
    return l;
  }, [tasks.data, filter, q]);
  const groups = useMemo(() => {
    if (filter === "erledigt") return [["Erledigt", list]] as [string, Task[]][];
    const g: Record<string, Task[]> = { "Überfällig": [], Heute: [], "Diese Woche": [], "Später": [], "Ohne Fälligkeit": [], Erledigt: [] };
    for (const t of list) {
      if (t.status === "done") g.Erledigt.push(t);
      else if (t.overdue) g["Überfällig"].push(t);
      else if (!t.due_date) g["Ohne Fälligkeit"].push(t);
      else if (t.due_date === today) g.Heute.push(t);
      else if (t.due_date <= weekEnd) g["Diese Woche"].push(t);
      else g["Später"].push(t);
    }
    return Object.entries(g).filter(([, v]) => v.length);
  }, [list, filter, today, weekEnd]);

  return (
    <div>
      <PageHeader title="Aufgaben" description={tasks.data ? `${list.length} Aufgaben` : undefined} actions={<Button variant="primary" onClick={() => create.newTask()}><Plus className="h-4 w-4" />Neue Aufgabe</Button>} />
      <div className="flex flex-wrap gap-2 mb-4">
        <Segmented value={filter} onChange={(v) => setParams({ filter: v })} className="overflow-x-auto max-w-full"
          options={[{ value: "aktiv", label: "Offen" }, { value: "heute", label: "Heute" }, { value: "ueberfaellig", label: "Überfällig" }, { value: "woche", label: "7 Tage" }, { value: "erledigt", label: "Erledigt" }, { value: "alle", label: "Alle" }]} />
        <Select value={project} onChange={(e) => setProject(e.target.value)} className="w-auto min-w-[160px]" aria-label="Projekt">
          <option value="">Alle Projekte</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
        <div className="relative flex-1 min-w-[180px] max-w-xs"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-ink-3" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filtern …" className="pl-8" /></div>
      </div>
      {tasks.isLoading ? <Skeleton className="h-64" /> : groups.length === 0 ? (
        <Panel><Empty icon={CheckSquare} title="Keine Aufgaben in dieser Ansicht" action={<Button size="sm" onClick={() => create.newTask()}>Aufgabe erstellen</Button>} /></Panel>
      ) : (
        <div className="space-y-5">
          {groups.map(([name, l]) => (
            <Panel key={name} title={<span className={name === "Überfällig" ? "text-danger" : undefined}>{name} <span className="text-ink-3 font-normal tnum ml-1">{l.length}</span></span>} bodyClassName="divide-y divide-line/70">
              {l.map((t) => <TaskRow key={t.id} task={t} />)}
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
