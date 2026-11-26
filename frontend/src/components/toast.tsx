import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

type Tone = "ok" | "error" | "info";
interface ToastItem { id: number; tone: Tone; text: string; action?: { label: string; onClick: () => void } }
const Ctx = createContext<(tone: Tone, text: string, action?: ToastItem["action"]) => void>(() => {});
let seq = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((tone: Tone, text: string, action?: ToastItem["action"]) => {
    const id = ++seq;
    setItems((s) => [...s.slice(-3), { id, tone, text, action }]);
    setTimeout(() => setItems((s) => s.filter((t) => t.id !== id)), tone === "error" ? 7000 : 4000);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="fixed z-[60] bottom-20 md:bottom-5 right-4 left-4 md:left-auto flex flex-col gap-2 items-end pointer-events-none" aria-live="polite">
        {items.map((t) => {
          const Icon = t.tone === "ok" ? CheckCircle2 : t.tone === "error" ? XCircle : Info;
          return (
            <div key={t.id} className="pointer-events-auto flex items-start gap-2.5 w-full md:w-auto md:max-w-sm rounded-md bg-raised px-3.5 py-2.5 shadow-pop animate-pop-in">
              <Icon className={cn("h-4 w-4 mt-0.5 shrink-0", t.tone === "ok" ? "text-ok" : t.tone === "error" ? "text-danger" : "text-accent")} />
              <span className="text-sm text-ink flex-1">{t.text}</span>
              {t.action && <button className="text-sm font-medium text-accent-ink hover:underline" onClick={t.action.onClick}>{t.action.label}</button>}
              <button aria-label="Schließen" className="text-ink-3 hover:text-ink" onClick={() => setItems((s) => s.filter((x) => x.id !== t.id))}><X className="h-3.5 w-3.5" /></button>
            </div>
          );
        })}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  const push = useContext(Ctx);
  return {
    ok: (t: string, a?: ToastItem["action"]) => push("ok", t, a),
    error: (e: unknown) => push("error", e instanceof Error ? e.message : String(e)),
    info: (t: string) => push("info", t),
  };
}
