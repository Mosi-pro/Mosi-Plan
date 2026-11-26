import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarCheck, History, RefreshCw, MessageSquareText, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Markdown } from "@/components/markdown";
import { useToast } from "@/components/toast";
import { Badge, Button, Dialog, Empty, ErrorNote, Field, Input, PageHeader, Panel, PriorityMark, Progress, Segmented, Skeleton, Switch } from "@/components/ui";
import { api } from "@/lib/api";
import { dateShort, fmt, minutes, time } from "@/lib/format";
import type { PlanItem, WeeklyPlan as Plan } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useInvalidate } from "@/hooks/queries";

const STATUS: Record<string, { l: string; t: "accent" | "ok" | "neutral" | "warn" }> = {
  draft: { l: "Entwurf", t: "warn" }, confirmed: { l: "Freigegeben", t: "ok" }, discarded: { l: "Verworfen", t: "neutral" }, superseded: { l: "Ersetzt", t: "neutral" },
};

function PlanView({ plan }: { plan: Plan }) {
  const qc = useQueryClient();
  const inv = useInvalidate();
  const toast = useToast();
  const [move, setMove] = useState<PlanItem | null>(null);
  const [when, setWhen] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pushGoogle, setPushGoogle] = useState(false);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["planner"] }); inv(); };
  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => api.post<any>(path, body),
    onSuccess: (_r, v) => { refresh(); toast.ok(v.path.endsWith("confirm") ? "Wochenplan freigegeben und in den Kalender übernommen" : v.path.endsWith("discard") ? "Entwurf verworfen" : v.path.endsWith("regenerate") ? "Neuer Entwurf erstellt" : "Gespeichert"); setConfirmOpen(false); setMove(null); },
    onError: toast.error,
  });
  const remove = useMutation({ mutationFn: (id: number) => api.del(`/api/planner/items/${id}`), onSuccess: refresh, onError: toast.error });
  const ai = useMutation({ mutationFn: () => api.post(`/api/planner/plans/${plan.id}/ai-notes`), onSuccess: refresh, onError: toast.error });
  const editable = plan.status === "draft" || plan.status === "confirmed";
  const d = plan.data;
  const items = plan.items.filter((i) => i.status !== "removed");
  const util = d.stats.capacity_minutes ? Math.round((d.stats.planned_minutes / d.stats.capacity_minutes) * 100) : 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <Badge tone={STATUS[plan.status].t}>{STATUS[plan.status].l}</Badge>
        <span className="text-sm text-ink-3">Erstellt {fmt(plan.created_at, "EEEE, d. MMM, HH:mm")} {plan.generated_by === "schedule" ? "(automatisch)" : plan.generated_by === "assistant" ? "(durch MOSI)" : ""}</span>
        <div className="ml-auto flex flex-wrap gap-2">
          {plan.status === "draft" && <>
            <Button variant="ghost" size="sm" loading={act.isPending && act.variables?.path.endsWith("discard")} onClick={() => act.mutate({ path: `/api/planner/plans/${plan.id}/discard` })}><X className="h-4 w-4" />Verwerfen</Button>
            <Button variant="secondary" size="sm" loading={act.isPending && act.variables?.path.endsWith("regenerate")} onClick={() => act.mutate({ path: `/api/planner/plans/${plan.id}/regenerate` })}><RefreshCw className="h-4 w-4" />Neu generieren</Button>
            <Button variant="primary" size="sm" onClick={() => setConfirmOpen(true)}><CalendarCheck className="h-4 w-4" />Bestätigen</Button>
          </>}
        </div>
      </div>

      {d.warnings.length > 0 && <div className="space-y-1.5">{d.warnings.map((w, i) => <p key={i} className="flex gap-2 text-sm text-warn"><AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />{w}</p>)}</div>}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-3 min-w-0">
          {d.days.map((day) => {
            const its = items.filter((i) => i.date === day.date);
            return (
              <section key={day.date} className={cn("rounded-md border border-line bg-surface", !day.workday && "opacity-80")}>
                <header className="flex items-center gap-3 px-4 h-10 border-b border-line">
                  <h3 className="text-sm font-semibold">{day.label}</h3>
                  {!day.workday && <span className="text-xs text-ink-3">kein Arbeitstag</span>}
                  <span className="ml-auto text-xs text-ink-3 tnum">{minutes(day.planned_minutes)} geplant{day.workday ? `, ${minutes(Math.max(0, day.capacity_minutes - day.planned_minutes))} frei` : ""}</span>
                </header>
                <div className="divide-y divide-line/60">
                  {[...day.events.map((e) => ({ kind: "event" as const, start: e.start, e })), ...its.map((i) => ({ kind: "item" as const, start: i.start, i }))]
                    .sort((a, b) => a.start.localeCompare(b.start))
                    .map((row) => row.kind === "event" ? (
                      <div key={"e" + row.e.title + row.e.start} className="flex items-center gap-3 px-4 py-2 text-sm text-ink-3">
                        <span className="w-24 tnum shrink-0">{row.e.all_day ? "ganztägig" : `${time(row.e.start)}–${time(row.e.end)}`}</span>
                        <span className="truncate">{row.e.title}</span><span className="ml-auto text-xs">Termin</span>
                      </div>
                    ) : (
                      <div key={row.i.id} className="group flex items-center gap-3 px-4 py-2">
                        <span className="w-24 text-sm tnum text-ink-2 shrink-0">{time(row.i.start)}–{time(row.i.end)}</span>
                        <span className="h-2 w-2 rounded-[3px] shrink-0" style={{ background: row.i.project_color ?? "#6B7484" }} />
                        <span className={cn("min-w-0 flex-1 truncate text-base", row.i.done ? "line-through text-ink-3" : "text-ink")}>{row.i.title}{row.i.note && <span className="text-ink-3"> ({row.i.note})</span>}</span>
                        {row.i.status === "moved" && <span className="text-xs text-ink-3">verschoben</span>}
                        <span className="hidden sm:inline text-sm text-ink-3 truncate max-w-[120px]">{row.i.project_name}</span>
                        <PriorityMark priority={row.i.priority} />
                        {editable && <div className="flex opacity-100 md:opacity-0 group-hover:opacity-100 focus-within:opacity-100">
                          <Button variant="ghost" size="sm" onClick={() => { setMove(row.i); setWhen(fmt(row.i.start, "yyyy-MM-dd'T'HH:mm")); }}>Verschieben</Button>
                          <Button variant="ghost" size="icon-sm" aria-label="Entfernen" onClick={() => remove.mutate(row.i.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
                        </div>}
                      </div>
                    ))}
                  {!its.length && !day.events.length && <p className="px-4 py-2.5 text-sm text-ink-3">{day.workday ? "Nichts geplant." : "Frei."}</p>}
                </div>
              </section>
            );
          })}
        </div>

        <div className="space-y-5">
          <Panel title="Wochenziele">
            {d.goals.length ? <ol className="px-4 py-3 space-y-2 list-decimal pl-8 text-base">{d.goals.map((g, i) => <li key={i} className="text-ink">{g.title}</li>)}</ol> : <p className="px-4 py-3 text-sm text-ink-3">Keine Ziele ableitbar – es sind keine passenden Aufgaben vorhanden.</p>}
          </Panel>
          <Panel title="Auslastung">
            <div className="px-4 py-3 space-y-2"><Progress value={util} /><p className="text-sm text-ink-2">{minutes(d.stats.planned_minutes)} von {minutes(d.stats.capacity_minutes)} freier Arbeitszeit verplant ({util} %).</p></div>
          </Panel>
          {d.deadlines.length > 0 && <Panel title="Kritische Deadlines"><ul className="px-4 py-3 space-y-1.5">{d.deadlines.map((x) => <li key={x.type + x.id} className="flex gap-3 text-sm"><span className="w-14 tnum text-ink-3 shrink-0">{dateShort(x.date)}</span><span className="text-ink">{x.title}</span></li>)}</ul></Panel>}
          {d.carryover.length > 0 && <Panel title="Offen aus der Vorwoche"><ul className="px-4 py-3 space-y-1.5 text-sm text-ink-2">{d.carryover.map((c) => <li key={c.task_id}>{c.title}</li>)}</ul></Panel>}
          {d.unscheduled.length > 0 && <Panel title="Nicht eingeplant"><ul className="px-4 py-3 space-y-2 text-sm">{d.unscheduled.map((u) => <li key={u.task_id}><div className="text-ink">{u.title}</div><div className="text-ink-3">{u.reason}, {minutes(u.minutes)} offen</div></li>)}</ul></Panel>}
          <Panel title="Empfehlungen" action={<Button size="sm" variant="ghost" loading={ai.isPending} onClick={() => ai.mutate()}><MessageSquareText className="h-3.5 w-3.5 text-accent" />MOSI fragen</Button>}>
            <div className="px-4 py-3 space-y-3 text-sm text-ink-2">
              {d.recommendations.length ? <ul className="list-disc pl-4 space-y-1">{d.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul> : <p>Keine Auffälligkeiten.</p>}
              {d.ai_notes && <div className="border-t border-line pt-3"><Markdown text={d.ai_notes} className="space-y-1.5" /></div>}
            </div>
          </Panel>
          {d.project_progress.length > 0 && <Panel title="Projektfortschritt"><div className="px-4 py-3 space-y-2.5">{d.project_progress.map((p) => <div key={p.project_id}><div className="flex justify-between text-sm"><span className="text-ink truncate">{p.name}</span><span className="text-ink-3 tnum">{p.progress} %</span></div><Progress value={p.progress} className="mt-1" /></div>)}</div></Panel>}
          {plan.review && plan.status === "confirmed" && <Panel title="Auswertung"><p className="px-4 py-3 text-sm text-ink-2">{plan.review.done_tasks} von {plan.review.planned_tasks} geplanten Aufgaben erledigt, {plan.review.moved} verschoben, {plan.review.removed} entfernt.</p></Panel>}
        </div>
      </div>

      <Dialog open={!!move} onOpenChange={(o) => !o && setMove(null)} title="Block verschieben" size="sm"
        footer={<><Button variant="ghost" onClick={() => setMove(null)}>Abbrechen</Button><Button variant="primary" loading={act.isPending} onClick={() => act.mutate({ path: `/api/planner/items/${move!.id}/move`, body: { start: new Date(when).toISOString() } })}>Verschieben</Button></>}>
        <Field label={`Neuer Beginn für „${move?.title}“`} hint={`Dauer bleibt ${minutes(move?.minutes)}.`}><Input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
        <ErrorNote error={act.error} className="mt-3" />
      </Dialog>
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen} title="Wochenplan freigeben?" size="sm"
        footer={<><Button variant="ghost" onClick={() => setConfirmOpen(false)}>Abbrechen</Button><Button variant="primary" loading={act.isPending} onClick={() => act.mutate({ path: `/api/planner/plans/${plan.id}/confirm`, body: { push_to_google: pushGoogle } })}>Freigeben</Button></>}>
        <p className="text-base text-ink-2">{items.length} Arbeitsblöcke werden als Termine in den MOSI-Kalender übernommen.</p>
        <Switch checked={pushGoogle} onChange={setPushGoogle} label="Auch in Google Calendar eintragen" description="Nur mit verbundenem Google-Konto. Ohne diese Option bleibt Google unverändert." />
      </Dialog>
    </div>
  );
}

export default function WeeklyPlan() {
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"this_week" | "next_week" | "history">(new Date().getDay() === 0 || new Date().getDay() >= 5 ? "next_week" : "this_week");
  const [histId, setHistId] = useState<number | null>(null);
  const cur = useQuery({ queryKey: ["planner", "current"], queryFn: () => api.get<Record<"this_week" | "next_week", { week_start: string; plan: Plan | null }>>("/api/planner/current") });
  const hist = useQuery({ queryKey: ["planner", "history"], queryFn: () => api.get<{ id: number; week_start: string; week_number: number; status: string; items: number; created_at: string }[]>("/api/planner/plans"), enabled: tab === "history" });
  const histPlan = useQuery({ queryKey: ["planner", "plan", histId], queryFn: () => api.get<Plan>(`/api/planner/plans/${histId}`), enabled: !!histId });
  const gen = useMutation({
    mutationFn: (week_start: string) => api.post<Plan>("/api/planner/generate", { week_start }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["planner"] }); toast.ok("Wochenplan-Entwurf erstellt"); },
    onError: toast.error,
  });
  const slot = tab !== "history" ? cur.data?.[tab] : null;
  return (
    <div>
      <PageHeader title="Wochenplan" description="MOSI erstellt jeden Sonntag um 18 Uhr einen Entwurf. Termine entstehen erst nach deiner Freigabe." />
      <Segmented value={tab} onChange={(v) => { setTab(v); setHistId(null); }} className="mb-6" options={[{ value: "this_week", label: "Diese Woche" }, { value: "next_week", label: "Nächste Woche" }, { value: "history", label: "Verlauf" }]} />
      {tab !== "history" && (cur.isLoading ? <Skeleton className="h-96" /> : slot?.plan ? <PlanView plan={slot.plan} /> : (
        <Panel><Empty icon={CalendarCheck} title={`Noch kein Plan für die Woche ab ${slot ? dateShort(slot.week_start) : ""}`} text="MOSI berücksichtigt Termine, offene Aufgaben, Deadlines, Prioritäten und deine Planungsregeln."
          action={<Button variant="primary" loading={gen.isPending} onClick={() => slot && gen.mutate(slot.week_start)}><MessageSquareText className="h-4 w-4" />Wochenplan erstellen</Button>} /></Panel>
      ))}
      {tab === "history" && (histId ? (
        <div><Button variant="ghost" size="sm" className="mb-4" onClick={() => setHistId(null)}>Zurück zum Verlauf</Button>{histPlan.data ? <PlanView plan={histPlan.data} /> : <Skeleton className="h-96" />}</div>
      ) : (
        <Panel bodyClassName="divide-y divide-line/70">
          {!hist.data?.length ? <Empty icon={History} title="Noch keine Wochenpläne" /> : hist.data.map((h) => (
            <button key={h.id} onClick={() => setHistId(h.id)} className="w-full flex items-center gap-4 px-4 py-3 text-left hover:bg-raised/60">
              <span className="w-16 text-base font-medium tnum">KW {h.week_number}</span>
              <span className="text-sm text-ink-3">ab {dateShort(h.week_start)}</span>
              <Badge tone={STATUS[h.status]?.t ?? "neutral"}>{STATUS[h.status]?.l ?? h.status}</Badge>
              <span className="ml-auto text-sm text-ink-3 tnum">{h.items} Blöcke</span>
            </button>
          ))}
        </Panel>
      ))}
    </div>
  );
}
