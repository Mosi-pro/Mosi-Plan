# HTTPS, Mikrofon & PWA

Browser erlauben Mikrofonzugriff, Service Worker, Push und App-Installation **nur in einem sicheren Kontext**: HTTPS mit gültigem Zertifikat oder `localhost`. Eine reine `http://SERVER-IP`-Adresse reicht dafür **nicht**.

`TLS_MODE` in `.env`:

| Modus | Wann | Mikrofon/PWA |
|---|---|---|
| `custom` | Domain mit Let's-Encrypt- oder eigenem Zertifikat (`data/certs/fullchain.pem`, `privkey.pem`). `install.sh` richtet Let's Encrypt automatisch ein. | voll funktionsfähig |
| `selfsigned` | Nur IP oder internes Netz/VPN. Zertifikat wird automatisch erzeugt. | funktioniert, nachdem das Zertifikat im Browser bzw. Gerät als vertrauenswürdig akzeptiert wurde; iOS/Android-PWA-Push meist nur mit vertrauenswürdigem Zertifikat |
| `off` | Nur hinter einem anderen TLS-Proxy oder für Tests über `localhost` | nur über localhost |

## Empfehlungen
1. **Domain + Let's Encrypt** (einfachste Lösung): DNS-A-Eintrag auf den Server, Port 80/443 offen, bei der Installation Domain angeben.
2. **Privater Zugang ohne öffentliche Ports:** Ein VPN wie WireGuard oder Tailscale; Tailscale kann mit `tailscale cert` gültige Zertifikate für den `*.ts.net`-Namen ausstellen – diese als `custom` nach `data/certs/` kopieren.

Nach Zertifikatswechsel: `docker compose restart frontend`.
