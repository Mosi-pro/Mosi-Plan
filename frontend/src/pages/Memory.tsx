import { useMutation, useQuery } from "@tanstack/react-query";
import { BookMarked, Pin, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { Badge, Button, Dialog, Empty, ErrorNote, Field, Input, PageHeader, Panel, Select, Skeleton, Switch, Textarea } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { ago, MEMORY_CATEGORY } from "@/lib/format";
import type { MemoryEntry } from "@/lib/types";
import { useInvalidate, useProjects } from "@/hooks/queries";

export default function Memory() {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [edit, setEdit] = useState<Partial<MemoryEntry> | null>(null);
  const projects = useProjects();
  const inv = useInvalidate();
  const toast = useToast();
  const list = useQuery({ queryKey: ["memory", q, cat], queryFn: () => api.get<MemoryEntry[]>(`/api/memory?${qs({ q, category: cat })}`), placeholderData: (p) => p });
  const save = useMutation({
    mutationFn: (m: Partial<MemoryEntry>) => {
      const body = { content: m.content, category: m.category, project_id: m.project_id || null, pinned: !!m.pinned };
      return m.id ? api.patch(`/api/memory/${m.id}`, body) : api.post("/api/memory", body);
    },
    onSuccess: () => { inv(); setEdit(null); toast.ok("Gespeichert"); },
  });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/api/memory/${id}`), onSuccess: () => { inv(); toast.ok("Eintrag gelöscht"); }, onError: toast.error });
  const pname = (id: number | null) => projects.data?.find((p) => p.id === id)?.name;
  return (
    <div>
      <PageHeader title="Gedächtnis" description="Was MOSI sich dauerhaft merkt: Entscheidungen, Planungsregeln, Ziele und Notizen."
        actions={<Button variant="primary" onClick={() => setEdit({ content: "", category: "note", pinned: false })}><Plus className="h-4 w-4" />Eintrag</Button>} />
      <div className="flex flex-wrap gap-2 mb-4">
        <div className="relative flex-1 min-w-[200px] max-w-md"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-ink-3" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Gedächtnis durchsuchen …" className="pl-8" /></div>
        <Select value={cat} onChange={(e) => setCat(e.target.value)} className="w-auto"><option value="">Alle Kategorien</option>{Object.entries(MEMORY_CATEGORY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
      </div>
      {list.isLoading ? <Skeleton className="h-64" /> : !list.data?.length ? (
        <Panel><Empty icon={BookMarked} title={q ? "Keine Treffer" : "Noch keine Einträge"} text="Sage im Assistenten zum Beispiel: „Merke dir: Freitags plane ich keine Termine nach 14 Uhr.“" /></Panel>
      ) : (
        <Panel bodyClassName="divide-y divide-line/70">
          {list.data.map((m) => (
            <div key={m.id} className="group flex gap-4 px-4 py-3 hover:bg-raised/40 cursor-pointer" onClick={() => setEdit(m)}>
              <div className="min-w-0 flex-1">
                <p className="text-base text-ink whitespace-pre-wrap">{m.content}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-3">
                  {m.pinned && <Pin className="h-3 w-3 text-accent" />}
                  <Badge>{MEMORY_CATEGORY[m.category] ?? m.category}</Badge>
                  {m.project_id && <span>{pname(m.project_id)}</span>}
                  <span>{m.source === "assistant" ? "von MOSI gespeichert" : "manuell"}, {ago(m.created_at)}</span>
                </div>
              </div>
              <Button variant="ghost" size="icon-sm" aria-label="Löschen" className="opacity-0 group-hover:opacity-100 focus:opacity-100" onClick={(e) => { e.stopPropagation(); if (confirm("Eintrag löschen?")) del.mutate(m.id); }}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}
        </Panel>
      )}
      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)} title={edit?.id ? "Eintrag bearbeiten" : "Neuer Eintrag"}
        footer={<><Button variant="ghost" onClick={() => setEdit(null)}>Abbrechen</Button><Button variant="primary" disabled={!edit?.content?.trim()} loading={save.isPending} onClick={() => edit && save.mutate(edit)}>Speichern</Button></>}>
        {edit && (
          <div className="space-y-4">
            <Field label="Inhalt" hint="Keine Passwörter, Bankdaten oder andere sensible Informationen."><Textarea autoFocus rows={4} value={edit.content} onChange={(e) => setEdit({ ...edit, content: e.target.value })} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Kategorie"><Select value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value })}>{Object.entries(MEMORY_CATEGORY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
              <Field label="Projekt"><Select value={edit.project_id ?? ""} onChange={(e) => setEdit({ ...edit, project_id: e.target.value ? Number(e.target.value) : null })}><option value="">Keins</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
            </div>
            <Switch checked={!!edit.pinned} onChange={(v) => setEdit({ ...edit, pinned: v })} label="Angeheftet" description="Angeheftete Einträge kennt MOSI in jedem Gespräch." />
            <ErrorNote error={save.error} />
          </div>
        )}
      </Dialog>
    </div>
  );
}
