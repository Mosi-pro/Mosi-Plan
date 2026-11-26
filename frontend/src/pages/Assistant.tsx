import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowUp, Loader2, MessageSquarePlus, MoreHorizontal, Pencil, Trash2, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Markdown } from "@/components/markdown";
import { PendingActionCard } from "@/components/pending-action";
import { useToast } from "@/components/toast";
import { Button, Menu, MenuContent, MenuItem, MenuTrigger, Spinner, Textarea } from "@/components/ui";
import { MicButton, useVoice } from "@/components/voice";
import { api } from "@/lib/api";
import { setActiveConversation, streamChat } from "@/lib/chat";
import { ago, time } from "@/lib/format";
import { speak, stopSpeaking, type VoiceSettings } from "@/lib/speech";
import type { ChatMessage, PendingAction } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useInvalidate, useSettings } from "@/hooks/queries";

const EXAMPLES = [
  "Was habe ich diese Woche noch offen?",
  "Plane meine kommende Woche.",
  "Erstelle für mein Projekt LBS einen vollständigen Entwicklungsplan.",
  "Erstelle für nächste Woche einen Projektplan für MOSI.MEDIA: Montag Website überarbeiten, Mittwoch neue Bilder bearbeiten.",
];

interface Conv { id: number; title: string; updated_at: string }
interface Live { user: string; text: string; status: string; error?: string | null; actions: PendingAction[] }

export default function Assistant() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const toast = useToast();
  const inv = useInvalidate();
  const voice = useVoice();
  const settings = useSettings();
  const convs = useQuery({ queryKey: ["conversations"], queryFn: () => api.get<Conv[]>("/api/conversations") });
  const status = useQuery({ queryKey: ["assistant-status"], queryFn: () => api.get<{ available: boolean; reason: string | null; backend: string | null }>("/api/assistant/status"), refetchInterval: 60000 });
  const cid = Number(params.get("c")) || convs.data?.[0]?.id || null;
  const conv = useQuery({ queryKey: ["conversation", cid], queryFn: () => api.get<{ id: number; title: string; messages: ChatMessage[] }>(`/api/conversations/${cid}`), enabled: !!cid });
  const [input, setInput] = useState("");
  const [live, setLive] = useState<Live | null>(null);
  const [speakingId, setSpeakingId] = useState<number | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const sentQ = useRef(false);

  useEffect(() => { if (cid) setActiveConversation(cid); }, [cid]);
  useEffect(() => { bottom.current?.scrollIntoView({ block: "end" }); }, [conv.data?.messages.length, live?.text, live?.status]);

  const newConv = useMutation({
    mutationFn: () => api.post<Conv>("/api/conversations"),
    onSuccess: (c) => { qc.invalidateQueries({ queryKey: ["conversations"] }); setParams({ c: String(c.id) }); },
  });
  const delConv = useMutation({
    mutationFn: (id: number) => api.del(`/api/conversations/${id}`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["conversations"] }); setParams({}); },
  });

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || live) return;
    let id = cid;
    if (!id) { const c = await api.post<Conv>("/api/conversations"); id = c.id; setParams({ c: String(id) }); }
    setInput("");
    setLive({ user: content, text: "", status: "Wird verarbeitet …", actions: [] });
    try {
      let acc = "";
      const done = await streamChat(id!, content, false, (ev) => {
        if (ev.type === "delta") { acc += ev.text; setLive((l) => l && { ...l, text: acc, status: "" }); }
        if (ev.type === "tool") setLive((l) => l && { ...l, status: `${ev.label} …` });
        if (ev.type === "backend" && ev.name === "direct") setLive((l) => l && { ...l, status: "Wird verarbeitet …" });
      });
      setLive((l) => l && { ...l, text: done.content, error: done.error, actions: done.pending_actions, status: "" });
      await qc.invalidateQueries({ queryKey: ["conversation", id] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
      inv();
    } catch (e) {
      toast.error(e);
    } finally {
      setLive(null);
    }
  };

  // ?q= aus der Befehlsleiste automatisch senden
  useEffect(() => {
    const q = params.get("q");
    if (q && !sentQ.current && convs.isSuccess) {
      sentQ.current = true;
      const next = new URLSearchParams(params); next.delete("q"); setParams(next, { replace: true });
      send(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, convs.isSuccess]);

  const readAloud = async (m: ChatMessage) => {
    if (speakingId === m.id) { stopSpeaking(); setSpeakingId(null); return; }
    setSpeakingId(m.id);
    try { await speak(m.content, { ...(settings.data?.voice ?? {}) } as VoiceSettings); } catch (e) { toast.error(e); } finally { setSpeakingId(null); }
  };

  const messages = conv.data?.messages ?? [];
  const empty = !messages.length && !live;
  return (
    <div className="-mx-4 md:-mx-8 -my-6 md:-my-8 flex h-[calc(100dvh-56px-64px)] md:h-[calc(100dvh-56px)]">
      {/* Gesprächsliste */}
      <aside className="hidden lg:flex w-[260px] shrink-0 flex-col border-r border-line">
        <div className="p-3"><Button variant="subtle" className="w-full justify-start" loading={newConv.isPending} onClick={() => newConv.mutate()}><MessageSquarePlus className="h-4 w-4" />Neues Gespräch</Button></div>
        <div className="flex-1 overflow-y-auto px-2 pb-3 space-y-0.5">
          {convs.data?.map((c) => (
            <div key={c.id} className={cn("group flex items-center rounded", c.id === cid ? "bg-raised" : "hover:bg-surface")}>
              <button onClick={() => setParams({ c: String(c.id) })} className="flex-1 min-w-0 text-left px-2.5 py-2">
                <div className={cn("text-sm truncate", c.id === cid ? "text-ink" : "text-ink-2")}>{c.title}</div>
                <div className="text-xs text-ink-3">{ago(c.updated_at)}</div>
              </button>
              <Menu>
                <MenuTrigger asChild><button aria-label="Gesprächsoptionen" className="opacity-0 group-hover:opacity-100 focus:opacity-100 px-2 text-ink-3 hover:text-ink"><MoreHorizontal className="h-4 w-4" /></button></MenuTrigger>
                <MenuContent>
                  <MenuItem icon={Pencil} onSelect={async () => { const t = prompt("Neuer Titel", c.title); if (t?.trim()) { await api.patch(`/api/conversations/${c.id}`, { title: t.trim() }); qc.invalidateQueries({ queryKey: ["conversations"] }); } }}>Umbenennen</MenuItem>
                  <MenuItem icon={Trash2} danger onSelect={() => delConv.mutate(c.id)}>Löschen</MenuItem>
                </MenuContent>
              </Menu>
            </div>
          ))}
        </div>
      </aside>

      {/* Chat */}
      <section className="flex-1 min-w-0 flex flex-col">
        <div className="flex items-center gap-3 h-12 px-4 md:px-6 border-b border-line">
          <h1 className="text-base font-semibold truncate flex-1">{conv.data?.title ?? "Assistent"}</h1>
          <Button variant="ghost" size="sm" className="lg:hidden" onClick={() => newConv.mutate()}><MessageSquarePlus className="h-4 w-4" />Neu</Button>
        </div>
        {status.data && !status.data.available && (
          <div className="flex gap-2 px-4 md:px-6 py-2.5 text-sm text-warn border-b border-line bg-warn/[0.05]"><AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" /><span>{status.data.reason}</span></div>
        )}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-[760px] mx-auto px-4 md:px-6 py-6 space-y-6">
            {empty && (
              <div className="pt-6 md:pt-14">
                <h2 className="text-xl font-semibold">Assistent</h2>
                <p className="text-base text-ink-2 mt-1">Zugriff auf Projekte, Aufgaben, Termine und gespeicherte Regeln. Änderungen mit Tragweite werden erst nach deiner Bestätigung ausgeführt.</p>
                <div className="mt-6 text-xs font-medium text-ink-3">Beispiele</div>
                <div className="mt-2 grid gap-2">
                  {EXAMPLES.map((e) => (
                    <button key={e} onClick={() => send(e)} className="text-left rounded border border-line px-3.5 py-2.5 text-base text-ink-2 hover:text-ink hover:border-line-strong hover:bg-surface transition-colors">{e}</button>
                  ))}
                </div>
              </div>
            )}
            {conv.isLoading && <div className="py-10 grid place-items-center"><Spinner /></div>}
            {messages.map((m) => <MessageView key={m.id} m={m} speaking={speakingId === m.id} onSpeak={() => readAloud(m)} />)}
            {live && (
              <>
                <UserBubble text={live.user} />
                <div className="max-w-full">
                  {live.text ? <Markdown text={live.text} className="space-y-2.5 leading-relaxed text-base text-ink" /> : null}
                  {live.status && <div className="flex items-center gap-2 text-sm text-ink-3 mt-1"><Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />{live.status}</div>}
                </div>
              </>
            )}
            <div ref={bottom} />
          </div>
        </div>
        <div className="border-t border-line px-4 md:px-6 py-3">
          <form className="max-w-[760px] mx-auto flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); send(input); }}>
            <Textarea value={input} onChange={(e) => setInput(e.target.value)} rows={1} placeholder="Anfrage eingeben …" aria-label="Nachricht"
              className="min-h-[40px] max-h-40 py-2 resize-none"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }} />
            <MicButton label={false} className="h-10 w-10 shrink-0" />
            <Button type="submit" variant="primary" size="icon" className="h-10 w-10 shrink-0" aria-label="Senden" disabled={!input.trim() || !!live || voice.state === "recording"}><ArrowUp className="h-4 w-4" /></Button>
          </form>
        </div>
      </section>
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return <div className="flex justify-end"><div className="max-w-[85%] rounded-lg rounded-br-sm bg-raised px-3.5 py-2 text-base text-ink whitespace-pre-wrap">{text}</div></div>;
}

function MessageView({ m, speaking, onSpeak }: { m: ChatMessage; speaking: boolean; onSpeak: () => void }) {
  if (m.role === "user") return <UserBubble text={m.content} />;
  return (
    <div className="group">
      {m.meta?.error ? (
        <div className="flex gap-2 text-base text-danger"><AlertTriangle className="h-4 w-4 mt-1 shrink-0" /><span>{m.content}</span></div>
      ) : (
        <Markdown text={m.content} className="space-y-2.5 leading-relaxed text-base text-ink" />
      )}
      {m.meta?.actions?.map((a) => <PendingActionCard key={a.id} action={a} />)}
      <div className="mt-1.5 flex items-center gap-3 text-xs text-ink-3">
        <span className="tnum">{time(m.created_at)}</span>
        {!!m.meta?.tools?.length && <span>{m.meta.tools.length} Werkzeug{m.meta.tools.length > 1 ? "e" : ""} genutzt</span>}
        {!m.meta?.error && (
          <button onClick={onSpeak} className="flex items-center gap-1 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:text-ink" aria-label="Vorlesen">
            <Volume2 className="h-3.5 w-3.5" />{speaking ? "Stopp" : "Vorlesen"}
          </button>
        )}
      </div>
    </div>
  );
}
