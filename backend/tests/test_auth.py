from tests.conftest import PASSWORD


def test_login_logout_flow(anon, user):
    assert anon.get("/api/auth/me").status_code == 401
    bad = anon.post("/api/auth/login", json={"username": "mosi", "password": "falsch"})
    assert bad.status_code == 401
    assert "falsch" in bad.json()["detail"]
    r = anon.post("/api/auth/login", json={"username": "mosi", "password": PASSWORD})
    assert r.status_code == 200
    cookie = anon.cookies.get("mosi_session")
    assert cookie
    me = anon.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["user"]["username"] == "mosi"
    # Ohne CSRF-Token keine schreibenden Aufrufe
    assert anon.post("/api/auth/logout").status_code == 403
    anon.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert anon.post("/api/auth/logout").status_code == 200
    anon.cookies.set("mosi_session", cookie)
    assert anon.get("/api/auth/me").status_code == 401


def test_password_hash_is_argon2id(user):
    assert user.password_hash.startswith("$argon2id$")


def test_login_rate_limit(anon, user):
    codes = [anon.post("/api/auth/login", json={"username": "mosi", "password": "x"}).status_code for _ in range(12)]
    assert 429 in codes


def test_protected_endpoints_require_login(anon):
    for path in ("/api/projects", "/api/tasks", "/api/overview", "/api/settings", "/api/system/status", "/api/memory"):
        assert anon.get(path).status_code == 401, path


def test_password_change(client):
    r = client.post("/api/auth/password", json={"current_password": "falsch", "new_password": "NeuesPasswort-99"})
    assert r.status_code == 400
    r = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "schwach"})
    assert r.status_code == 422
    r = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "nurkleinbuchstaben1"})
    assert r.status_code == 400
    r = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "NeuesPasswort-99"})
    assert r.status_code == 200
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "mosi", "password": "NeuesPasswort-99"}).status_code == 200


def test_profile_and_sessions(client):
    r = client.patch("/api/auth/profile", json={"display_name": "Mosi", "timezone": "Mars/Base"})
    assert r.status_code == 422
    r = client.patch("/api/auth/profile", json={"display_name": "Mosi", "timezone": "Europe/Berlin"})
    assert r.status_code == 200 and r.json()["display_name"] == "Mosi"
    s = client.get("/api/auth/sessions").json()
    assert len(s) == 1 and s[0]["current"]


def test_avatar_upload_validation(client):
    r = client.post("/api/auth/avatar", files={"file": ("x.png", b"not an image", "image/png")})
    assert r.status_code == 400
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    r = client.post("/api/auth/avatar", files={"file": ("x.png", png, "image/png")})
    assert r.status_code == 200 and r.json()["has_avatar"]
    assert client.get("/api/auth/avatar").status_code == 200
