import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { minutes, dateShort } from "@/lib/format";
import type { PendingAction } from "@/lib/types";
import { Badge, Button } from "./ui";
import { useInvalidate } from "@/hooks/queries";
import { useToast } from "./toast";

interface PlanTask { key: string; title: string; estimated_minutes: number; due_date?: string | null; priority: string; depends_on: string[]; parent_key?: string | null }

function PlanPreview({ p }: { p: Record<string, any> }) {
  const tasks = (p.tasks ?? []) as PlanTask[];
  const byKey = Object.fromEntries(tasks.map((t, i) => [t.key, i + 1]));
  return (
    <div className="mt-3 space-y-3">
      {p.goal && <p className="text-sm text-ink-2"><span className="text-ink-3">Ziel: </span>{p.goal}</p>}
      <ol className="divide-y divide-line rounded border border-line bg-canvas">
        {tasks.map((t, i) => (
          <li key={t.key} className="flex items-start gap-3 px-3 py-2 text-sm">
            <span className="tnum text-ink-3 w-5 shrink-0">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <div className={t.parent_key ? "pl-3 text-ink-2" : "text-ink"}>{t.title}</div>
              {t.depends_on?.length > 0 && <div className="text-xs text-ink-3">nach Schritt {t.depends_on.map((d) => byKey[d]).join(", ")}</div>}
            </div>
            <span className="tnum text-ink-3 shrink-0">{minutes(t.estimated_minutes)}</span>
            {t.due_date && <span className="tnum text-ink-3 shrink-0 w-14 text-right">{dateShort(t.due_date)}</span>}
          </li>
        ))}
      </ol>
      {p.check && (
        <p className="text-sm text-ink-3">
          Aufwand gesamt {minutes(p.check.total_minutes)}. Freie Arbeitszeit bis {dateShort(p.check.end)}: {minutes(p.check.free_minutes_until_end)}.
        </p>
      )}
      {[...(p.check?.warnings ?? []), ...(p.assumptions ?? []).map((a: string) => `Annahme: ${a}`)].map((w: string, i: number) => (
        <p key={i} className="text-sm text-warn">{w}</p>
      ))}
    </div>
  );
}

export function PendingActionCard({ action }: { action: PendingAction }) {
  const [status, setStatus] = useState(action.status);
  const [error, setError] = useState<string | null>(null);
  const inv = useInvalidate();
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useMutation({
    mutationFn: () => api.post(`/api/actions/${action.id}/confirm`),
    onSuccess: () => { setStatus("confirmed"); inv(); qc.invalidateQueries({ queryKey: ["actions"] }); toast.ok("Ausgeführt: " + action.description); },
    onError: (e: Error) => { setError(e.message); setStatus("failed"); },
  });
  const reject = useMutation({
    mutationFn: () => api.post(`/api/actions/${action.id}/reject`),
    onSuccess: () => { setStatus("rejected"); qc.invalidateQueries({ queryKey: ["actions"] }); },
    onError: (e: Error) => setError(e.message),
  });
  const preview = action.preview ?? {};
  return (
    <div className="mt-3 rounded-md border border-warn/30 bg-warn/[0.06] p-3.5">
      <div className="flex items-start gap-2.5">
        <ShieldAlert className="h-4 w-4 text-warn mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-ink">{action.description}</div>
          <div className="text-xs text-ink-3 mt-0.5">Diese Aktion wird erst nach deiner Bestätigung ausgeführt.</div>
          {action.tool === "propose_project_plan" && <PlanPreview p={preview} />}
          {Array.isArray((preview as any).tasks) && action.tool === "bulk_update_tasks" && (
            <ul className="mt-2 text-sm text-ink-2 list-disc pl-5">{(preview as any).tasks.map((t: any) => <li key={t.id}>{t.title}</li>)}</ul>
          )}
          {error && <p className="text-sm text-danger mt-2">{error}</p>}
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2 justify-end">
        {status === "pending" && (
          <>
            <Button size="sm" variant="ghost" loading={reject.isPending} onClick={() => reject.mutate()}>Ablehnen</Button>
            <Button size="sm" variant="primary" loading={confirm.isPending} onClick={() => confirm.mutate()}>Bestätigen</Button>
          </>
        )}
        {status === "confirmed" && <Badge tone="ok"><CheckCircle2 className="h-3 w-3" />Ausgeführt</Badge>}
        {status === "rejected" && <Badge><XCircle className="h-3 w-3" />Abgelehnt</Badge>}
        {(status === "failed" || status === "expired") && <Badge tone="danger">{status === "expired" ? "Abgelaufen" : "Fehlgeschlagen"}</Badge>}
      </div>
    </div>
  );
}
