"""Verwaltungsbefehle: python -m app.cli <befehl>

  create-admin --username NAME [--name ANZEIGENAME]   Passwort über STDIN oder interaktiv
  reset-password --username NAME                       Passwort über STDIN oder interaktiv
  wait-db                                              wartet, bis die Datenbank erreichbar ist
  has-admin                                            Exit-Code 0, wenn ein Benutzer existiert
"""
import argparse
import getpass
import sys
import time

from sqlalchemy import select, text

from .db import SessionLocal, engine
from .models import User
from .security import hash_password


def _read_password() -> str:
    if not sys.stdin.isatty():
        pw = sys.stdin.readline().rstrip("\n")
    else:
        pw = getpass.getpass("Passwort: ")
        if pw != getpass.getpass("Passwort wiederholen: "):
            sys.exit("Passwörter stimmen nicht überein.")
    if len(pw) < 10 or pw.lower() == pw or pw.upper() == pw or not any(c.isdigit() for c in pw):
        sys.exit("Passwort zu schwach: mind. 10 Zeichen, Groß-/Kleinbuchstaben und eine Ziffer.")
    return pw


def main() -> None:
    p = argparse.ArgumentParser(prog="mosi")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-admin")
    c.add_argument("--username", required=True)
    c.add_argument("--name", default="")
    r = sub.add_parser("reset-password")
    r.add_argument("--username", required=True)
    sub.add_parser("wait-db")
    sub.add_parser("has-admin")
    a = p.parse_args()

    if a.cmd == "wait-db":
        for _ in range(60):
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                print("Datenbank erreichbar.")
                return
            except Exception:  # noqa: BLE001
                time.sleep(2)
        sys.exit("Datenbank nicht erreichbar.")

    db = SessionLocal()
    try:
        if a.cmd == "has-admin":
            sys.exit(0 if db.scalars(select(User)).first() else 1)
        if a.cmd == "create-admin":
            if db.scalars(select(User)).first():
                sys.exit("Es existiert bereits ein Benutzer. MOSI PLAN ist eine Einzelbenutzer-Anwendung (reset-password verwenden).")
            username = a.username.strip()
            if not username or len(username) > 64:
                sys.exit("Ungültiger Benutzername.")
            db.add(User(username=username, password_hash=hash_password(_read_password()), display_name=a.name or username))
            db.commit()
            print(f"Administrator „{username}“ angelegt.")
        elif a.cmd == "reset-password":
            user = db.scalars(select(User).where(User.username == a.username)).first()
            if not user:
                sys.exit("Benutzer nicht gefunden.")
            user.password_hash = hash_password(_read_password())
            db.execute(text("DELETE FROM user_sessions WHERE user_id = :u"), {"u": user.id})
            db.commit()
            print("Passwort geändert, alle Sitzungen beendet.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
