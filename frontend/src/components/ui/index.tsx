/* MOSI PLAN – Basiskomponenten des Designsystems */
import * as RDialog from "@radix-ui/react-dialog";
import * as RMenu from "@radix-ui/react-dropdown-menu";
import * as RSwitch from "@radix-ui/react-switch";
import * as RTooltip from "@radix-ui/react-tooltip";
import { AlertTriangle, Check, CircleDashed, Loader2, X } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/utils";
import type { Priority } from "@/lib/types";

/* ------------------------------------------------------------------ Button */
type Variant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
type Size = "sm" | "md" | "lg" | "icon" | "icon-sm";
const variants: Record<Variant, string> = {
  primary: "bg-white text-[#16130f] hover:bg-white/90 active:bg-white/80 shadow-[0_6px_20px_-8px_rgb(0_0_0/0.6)]",
  secondary: "bg-white/[0.10] text-ink border border-white/[0.14] backdrop-blur-xl hover:bg-white/[0.16]",
  ghost: "text-ink-2 hover:text-ink hover:bg-white/[0.08]",
  subtle: "bg-white/[0.06] text-ink-2 border border-white/[0.10] backdrop-blur-xl hover:text-ink hover:bg-white/[0.12]",
  danger: "bg-danger/15 text-danger border border-danger/30 hover:bg-danger/25",
};
const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-base gap-2",
  lg: "h-12 px-6 text-md gap-2",
  icon: "h-10 w-10 justify-center",
  "icon-sm": "h-8 w-8 justify-center",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant = "secondary", size = "md", loading, children, disabled, ...p }, ref) => (
  <button
    ref={ref}
    disabled={disabled || loading}
    className={cn("inline-flex items-center rounded-full font-medium transition-colors select-none disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap", variants[variant], sizes[size], className)}
    {...p}
  >
    {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
    {children}
  </button>
));
Button.displayName = "Button";

/* ------------------------------------------------------------------ Felder */
const field = "w-full rounded bg-black/25 border border-white/[0.12] px-3.5 text-base text-ink placeholder:text-ink-3 transition-colors hover:border-ink-3/50 focus:border-accent/70 focus:outline-none focus-visible:shadow-none disabled:opacity-60";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn(field, "h-10", className)} {...p} />
));
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => (
  <textarea ref={ref} className={cn(field, "py-2 min-h-[84px] resize-y leading-relaxed", className)} {...p} />
));
Textarea.displayName = "Textarea";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(({ className, children, ...p }, ref) => (
  <select ref={ref} className={cn(field, "h-10 pr-8 appearance-none bg-[length:16px] bg-[right_8px_center] bg-no-repeat cursor-pointer", className)}
    style={{ backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%239AA3B2' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")" }}
    {...p}>
    {children}
  </select>
));
Select.displayName = "Select";

export function Field({ label, hint, error, children, className }: { label: string; hint?: ReactNode; error?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block space-y-1.5", className)}>
      <span className="text-sm font-medium text-ink-2">{label}</span>
      {children}
      {error ? <span className="block text-sm text-danger">{error}</span> : hint ? <span className="block text-sm text-ink-3">{hint}</span> : null}
    </label>
  );
}

export function Switch({ checked, onChange, label, description, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string; disabled?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-6 py-3">
      <div className="min-w-0">
        <div className="text-base text-ink">{label}</div>
        {description && <div className="text-sm text-ink-3 mt-0.5">{description}</div>}
      </div>
      <RSwitch.Root
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
        aria-label={label}
        className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full bg-line-strong transition-colors data-[state=checked]:bg-accent disabled:opacity-50"
      >
        <RSwitch.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
      </RSwitch.Root>
    </div>
  );
}

export function Checkbox({ checked, onChange, label, className }: { checked: boolean; onChange: (v: boolean) => void; label: string; className?: string }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      onClick={(e) => { e.stopPropagation(); onChange(!checked); }}
      className={cn("grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border transition-colors", checked ? "border-accent bg-accent text-white" : "border-ink-3 hover:border-ink-2", className)}
    >
      {checked && <Check className="h-3 w-3" strokeWidth={3} />}
    </button>
  );
}

/* ------------------------------------------------------------------ Status */
export function Badge({ children, tone = "neutral", className }: { children: ReactNode; tone?: "neutral" | "accent" | "ok" | "warn" | "danger"; className?: string }) {
  const tones = {
    neutral: "bg-raised text-ink-2 border-line",
    accent: "bg-accent/12 text-accent-ink border-accent/25",
    ok: "bg-ok/12 text-ok border-ok/25",
    warn: "bg-warn/12 text-warn border-warn/25",
    danger: "bg-danger/12 text-danger border-danger/25",
  };
  return <span className={cn("inline-flex items-center gap-1 rounded-full border px-2 h-5 text-xs font-medium whitespace-nowrap", tones[tone], className)}>{children}</span>;
}

/** Priorität als kleine Balkengrafik (keine Farbe außer bei kritisch). */
export function PriorityMark({ priority, className }: { priority: Priority; className?: string }) {
  const level = { low: 1, normal: 2, high: 3, critical: 4 }[priority];
  const label = { low: "Niedrige", normal: "Normale", high: "Hohe", critical: "Kritische" }[priority] + " Priorität";
  if (priority === "critical")
    return <AlertTriangle className={cn("h-3.5 w-3.5 text-danger shrink-0", className)} aria-label={label} />;
  return (
    <span className={cn("inline-flex items-end gap-[2px] h-3 shrink-0", className)} role="img" aria-label={label} title={label}>
      {[1, 2, 3].map((i) => (
        <span key={i} className={cn("w-[3px] rounded-[1px]", i <= level ? "bg-ink-2" : "bg-line-strong")} style={{ height: `${i * 4}px` }} />
      ))}
    </span>
  );
}

export function Progress({ value, className, tone = "accent" }: { value: number; className?: string; tone?: "accent" | "ok" }) {
  return (
    <div className={cn("h-1 w-full overflow-hidden rounded-full bg-line", className)} role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <div className={cn("h-full rounded-full transition-[width] duration-500", tone === "ok" ? "bg-ok" : "bg-accent")} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin text-ink-3", className)} aria-label="Lädt" />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-raised", className)} />;
}

export function Empty({ icon: Icon = CircleDashed, title, text, action }: { icon?: React.ComponentType<{ className?: string }>; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-10 px-6">
      <Icon className="h-5 w-5 text-ink-3 mb-3" />
      <div className="text-base font-medium text-ink">{title}</div>
      {text && <p className="text-sm text-ink-3 mt-1 max-w-sm">{text}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorNote({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null;
  return (
    <div role="alert" className={cn("flex gap-2 rounded border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger", className)}>
      <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
      <span>{error instanceof Error ? error.message : String(error)}</span>
    </div>
  );
}

/* ------------------------------------------------------------------ Layout-Bausteine */
export function Panel({ title, action, children, className, bodyClassName }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; bodyClassName?: string }) {
  return (
    <section className={cn("glass rounded-md border border-white/[0.10] overflow-hidden", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 px-5 h-12">
          <h2 className="text-base font-semibold text-ink truncate">{title}</h2>
          {action}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions, children }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl md:text-3xl font-light tracking-tight text-ink">{title}</h1>
          {description && <p className="text-base text-ink-2 mt-1">{description}</p>}
        </div>
        {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

export function Segmented<T extends string>({ value, onChange, options, className }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; className?: string }) {
  return (
    <div role="tablist" className={cn("glass inline-flex rounded-full border border-white/[0.10] p-1", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn("h-8 px-3.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap", value === o.value ? "bg-white text-[#16130f]" : "text-ink-2 hover:text-ink")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ Dialog */
export function Dialog({ open, onOpenChange, title, description, children, footer, size = "md" }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: string; children: ReactNode; footer?: ReactNode; size?: "sm" | "md" | "lg";
}) {
  const w = { sm: "sm:max-w-[420px]", md: "sm:max-w-[560px]", lg: "sm:max-w-[760px]" }[size];
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="fixed inset-0 z-50 bg-black/45 backdrop-blur-sm animate-fade-in" />
        <RDialog.Content
          className={cn("fixed z-50 inset-x-0 bottom-0 sm:inset-auto sm:left-1/2 sm:top-[12vh] sm:-translate-x-1/2 w-full", w,
            "max-h-[90dvh] flex flex-col rounded-t-lg sm:rounded-lg shadow-pop glass-pop animate-pop-in safe-bottom")}
        >
          <div className="flex items-start justify-between gap-4 px-6 pt-5 pb-3">
            <div>
              <RDialog.Title className="text-md font-semibold text-ink">{title}</RDialog.Title>
              {description ? <RDialog.Description className="text-sm text-ink-3 mt-0.5">{description}</RDialog.Description> : <RDialog.Description className="sr-only">{title}</RDialog.Description>}
            </div>
            <RDialog.Close asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Schließen"><X className="h-4 w-4" /></Button>
            </RDialog.Close>
          </div>
          <div className="px-6 py-3 overflow-y-auto">{children}</div>
          {footer && <div className="flex flex-wrap justify-end gap-2 px-6 pt-3 pb-5">{footer}</div>}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

export function ConfirmDialog({ open, onOpenChange, title, text, confirmLabel, onConfirm, loading, danger = true }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; text: ReactNode; confirmLabel: string; onConfirm: () => void; loading?: boolean; danger?: boolean;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={title} size="sm"
      footer={<>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Abbrechen</Button>
        <Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm}>{confirmLabel}</Button>
      </>}>
      <div className="text-base text-ink-2">{text}</div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ Menü & Tooltip */
export const Menu = RMenu.Root;
export const MenuTrigger = RMenu.Trigger;
export function MenuContent({ children, align = "end" }: { children: ReactNode; align?: "start" | "end" | "center" }) {
  return (
    <RMenu.Portal>
      <RMenu.Content align={align} sideOffset={8} className="z-50 min-w-[200px] rounded-[18px] p-1.5 shadow-pop glass-pop animate-pop-in">
        {children}
      </RMenu.Content>
    </RMenu.Portal>
  );
}
export function MenuItem({ children, onSelect, danger, icon: Icon }: { children: ReactNode; onSelect: () => void; danger?: boolean; icon?: React.ComponentType<{ className?: string }> }) {
  return (
    <RMenu.Item onSelect={onSelect}
      className={cn("flex items-center gap-2 h-9 px-3 rounded-sm text-sm cursor-pointer outline-none data-[highlighted]:bg-white/10", danger ? "text-danger" : "text-ink")}>
      {Icon && <Icon className="h-4 w-4 text-ink-3" />}
      {children}
    </RMenu.Item>
  );
}
export const MenuSeparator = () => <RMenu.Separator className="my-1 h-px bg-line" />;

export function Tip({ label, children, side = "top" }: { label: string; children: ReactNode; side?: "top" | "right" | "bottom" | "left" }) {
  return (
    <RTooltip.Root delayDuration={350}>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content side={side} sideOffset={6} className="z-50 rounded bg-raised px-2 py-1 text-xs text-ink shadow-pop glass-pop animate-fade-in">
          {label}
        </RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  );
}
export const TooltipProvider = RTooltip.Provider;

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded-sm border border-line-strong bg-canvas px-1 text-2xs font-medium text-ink-3">{children}</kbd>;
}
