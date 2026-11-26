import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Logo } from "@/components/layout";
import { Button, ErrorNote, Field, Input } from "@/components/ui";
import { useAuth } from "@/hooks/auth";

export default function Login() {
  const { login } = useAuth();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { await login(u.trim(), p); } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <div className="min-h-full grid place-items-center px-4 py-12">
      <div className="w-full max-w-[360px]">
        <Logo className="mb-10" />
        <h1 className="text-2xl font-semibold">Anmelden</h1>
        <p className="text-base text-ink-2 mt-1">Your personal AI planning assistant.</p>
        <form onSubmit={submit} className="mt-8 space-y-4">
          <Field label="Benutzername"><Input autoFocus autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} required /></Field>
          <Field label="Passwort"><Input type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} required /></Field>
          <ErrorNote error={err} />
          <Button type="submit" variant="primary" size="lg" className="w-full justify-center" loading={busy}>Anmelden</Button>
        </form>
        {!window.isSecureContext && (
          <p className="mt-8 flex gap-2 text-sm text-warn"><ShieldAlert className="h-4 w-4 mt-0.5 shrink-0" />Unverschlüsselte Verbindung. Mikrofon, Push und App-Installation funktionieren nur über HTTPS.</p>
        )}
      </div>
    </div>
  );
}
