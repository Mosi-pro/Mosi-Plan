import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, MoreHorizontal, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useCreate } from "@/components/dialogs";
import { Markdown } from "@/components/markdown";
import { TaskRow } from "@/components/task-row";
import { useToast } from "@/components/toast";
import { Badge, Button, ConfirmDialog, Empty, ErrorNote, Menu, MenuContent, MenuItem, MenuTrigger, Panel, Progress, Skeleton, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { ago, dateLong, PRIORITY, PROJECT_STATUS, relDay, time } from "@/lib/format";
import type { CalEvent, Project, Task } from "@/lib/types";
import { useInvalidate } from "@/hooks/queries";

interface Detail { project: Project; tasks: Task[]; events: CalEvent[]; history: { ts: string; actor: string; summary: string }[]; problems: { type: string; text: string }[] }

export default function ProjectDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const inv = useInvalidate();
  const toast = useToast();
  const create = useCreate();
  const q = useQuery({ queryKey: ["project", id], queryFn: () => api.get<Detail>(`/api/projects/${id}`) });
  const [notes, setNotes] = useState("");
  const [del, setDel] = useState(false);
  useEffect(() => { if (q.data) setNotes(q.data.project.notes); }, [q.data]);
  const saveNotes = useMutation({ mutationFn: () => api.patch(`/api/projects/${id}`, { notes }), onSuccess: () => { inv(); toast.ok("Notizen gespeichert"); }, onError: toast.error });
  const summary = useMutation({ mutationFn: () => api.post(`/api/projects/${id}/ai-summary`), onSuccess: () => qc.invalidateQueries({ queryKey: ["project", id] }), onError: toast.error });
  const remove = useMutation({ mutationFn: () => api.del(`/api/projects/${id}`), onSuccess: () => { inv(); toast.ok("Projekt gelöscht"); nav("/projekte"); }, onError: toast.error });
  if (q.isError) return <ErrorNote error={q.error} />;
  if (!q.data) return <Skeleton className="h-96" />;
  const { project: p, tasks, events, history, problems } = q.data;
  const top = tasks.filter((t) => !t.parent_id);
  const open = top.filter((t) => t.status !== "done");
  const done = top.filter((t) => t.status === "done");
  const subs = (t: Task) => tasks.filter((s) => s.parent_id === t.id);
  return (
    <div>
      <Link to="/projekte" className="inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink mb-4"><ArrowLeft className="h-4 w-4" />Projekte</Link>
      <div className="flex flex-wrap items-start gap-4 justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-3"><span className="h-3.5 w-3.5 rounded" style={{ background: p.color }} /><h1 className="text-2xl font-semibold truncate">{p.name}</h1></div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-3">
            <Badge tone={p.status === "active" ? "accent" : "neutral"}>{PROJECT_STATUS[p.status]}</Badge>
            <span>Priorität {PRIORITY[p.priority]}</span>
            {p.deadline && <span>Deadline {dateLong(p.deadline)}</span>}
            {p.categories.map((c) => <Badge key={c}>{c}</Badge>)}
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => create.newTask({ project_id: p.id })}><Plus className="h-4 w-4" />Aufgabe</Button>
          <Menu>
            <MenuTrigger asChild><Button variant="secondary" size="icon" aria-label="Weitere Aktionen"><MoreHorizontal className="h-4 w-4" /></Button></MenuTrigger>
            <MenuContent>
              <MenuItem icon={Pencil} onSelect={() => create.editProject(p)}>Bearbeiten</MenuItem>
              <MenuItem icon={Sparkles} onSelect={() => nav(`/assistent?q=${encodeURIComponent(`Erstelle für mein Projekt ${p.name} einen vollständigen Entwicklungsplan.`)}`)}>Plan mit MOSI erstellen</MenuItem>
              <MenuItem icon={Trash2} danger onSelect={() => setDel(true)}>Löschen</MenuItem>
            </MenuContent>
          </Menu>
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="space-y-6 min-w-0">
          {(p.goal || p.description) && (
            <div className="space-y-2 max-w-[70ch]">
              {p.goal && <p className="text-md text-ink"><span className="text-ink-3">Ziel: </span>{p.goal}</p>}
              {p.description && <p className="text-base text-ink-2 whitespace-pre-wrap">{p.description}</p>}
            </div>
          )}
          <div className="flex items-center gap-3"><Progress value={p.progress} className="h-1.5" /><span className="text-sm text-ink-2 tnum whitespace-nowrap">{p.progress} % · {p.task_done} von {p.task_total} erledigt</span></div>
          <Panel title={`Offene Aufgaben (${open.length})`} bodyClassName="divide-y divide-line/70">
            {open.length ? open.map((t) => (
              <div key={t.id}>
                <TaskRow task={t} showProject={false} />
                {subs(t).map((s) => <div key={s.id} className="pl-6"><TaskRow task={s} showProject={false} dense /></div>)}
                <button className="ml-14 mb-1 text-xs text-ink-3 hover:text-ink" onClick={() => create.newTask({ project_id: p.id, parent_id: t.id })}>+ Unteraufgabe</button>
              </div>
            )) : <Empty title="Keine offenen Aufgaben" action={<Button size="sm" onClick={() => create.newTask({ project_id: p.id })}>Aufgabe hinzufügen</Button>} />}
          </Panel>
          {done.length > 0 && <Panel title={`Erledigt (${done.length})`} bodyClassName="divide-y divide-line/70">{done.map((t) => <TaskRow key={t.id} task={t} showProject={false} dense />)}</Panel>}
          <Panel title="Notizen" action={notes !== p.notes && <Button size="sm" variant="primary" loading={saveNotes.isPending} onClick={() => saveNotes.mutate()}>Speichern</Button>}>
            <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={6} className="border-0 bg-transparent rounded-none focus:border-0" placeholder="Notizen zum Projekt …" />
          </Panel>
        </div>
        <div className="space-y-6">
          <Panel title="KI-Zusammenfassung" action={<Button size="sm" variant="ghost" loading={summary.isPending} onClick={() => summary.mutate()}><Sparkles className="h-3.5 w-3.5 text-accent" />{p.ai_summary ? "Aktualisieren" : "Erstellen"}</Button>}>
            <div className="px-4 py-3 text-sm text-ink-2">
              {p.ai_summary ? <><Markdown text={p.ai_summary} className="space-y-2" /><div className="text-xs text-ink-3 mt-2">{ago(p.ai_summary_at!)}</div></> : "Noch keine Zusammenfassung."}
            </div>
          </Panel>
          {problems.length > 0 && (
            <Panel title="Offene Probleme"><ul className="px-4 py-3 space-y-2">{problems.map((x, i) => <li key={i} className="flex gap-2 text-sm text-warn"><AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />{x.text}</li>)}</ul></Panel>
          )}
          <Panel title="Termine">
            {events.length ? <ul className="divide-y divide-line/70">{events.map((e) => <li key={e.id}><button onClick={() => create.editEvent(e)} className="w-full text-left px-4 py-2.5 hover:bg-raised/60"><div className="text-sm text-ink">{e.title}</div><div className="text-xs text-ink-3 tnum">{relDay(e.start)}{!e.all_day && `, ${time(e.start)}`}</div></button></li>)}</ul> : <p className="px-4 py-3 text-sm text-ink-3">Keine verknüpften Termine.</p>}
          </Panel>
          <Panel title="Verlauf">
            <ul className="px-4 py-3 space-y-3 max-h-80 overflow-y-auto">
              {history.map((h, i) => <li key={i} className="text-sm"><div className="text-ink-2">{h.summary}</div><div className="text-xs text-ink-3">{ago(h.ts)}{h.actor === "assistant" && ", durch MOSI"}</div></li>)}
            </ul>
          </Panel>
        </div>
      </div>
      <ConfirmDialog open={del} onOpenChange={setDel} title="Projekt löschen?" text={`„${p.name}“ wird gelöscht. Offene Aufgaben werden archiviert, nicht gelöscht.`} confirmLabel="Projekt löschen" loading={remove.isPending} onConfirm={() => remove.mutate()} />
    </div>
  );
}
