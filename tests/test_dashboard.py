"""Tests B1 — dashboard anti-CSRF (isolés : ROOT pointé vers tmp_path).

Aucun contact avec le desk réel : les fichiers ctl/ créés par /api/ctl sont
écrits dans un répertoire temporaire, jamais dans /root/aidesk/ctl.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT = Path(__file__).resolve().parent.parent

HEADER = {"X-Requested-With": "desk-ui"}


def load_dashboard_module():
    """Charge tools/dashboard.py sans exécuter le serveur (garde __main__)."""
    p = PROJECT / "tools" / "dashboard.py"
    spec = importlib.util.spec_from_file_location("_dashboard_under_test", str(p))
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_dashboard_under_test", mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def dash(tmp_path):
    mod = load_dashboard_module()
    mod.ROOT = tmp_path          # isolation : toutes les écritures ctl/ sont dans tmp
    client = TestClient(mod.app)
    return mod, tmp_path, client


# --- 1. protection anti-CSRF : requête sans en-tête refusée -------------------

def test_post_sans_en_tete_refuse_403(dash):
    _, tmp, client = dash
    r = client.post("/api/ctl?action=pause")
    assert r.status_code == 403
    # aucun fichier ctl créé par la requête refusée
    assert not (tmp / "ctl").exists() or not list((tmp / "ctl").iterdir())


def test_post_sans_en_tete_reste_refuse_pour_toutes_les_actions(dash):
    _, tmp, client = dash
    for action in ("pause", "pause-toggle", "sell_all", "kill", "__probe"):
        r = client.post(f"/api/ctl?action={action}")
        assert r.status_code == 403, action
    assert not (tmp / "ctl").exists() or not list((tmp / "ctl").iterdir())


# --- 2. requêtes légitimes de l'UI : autorisées, sémantique inchangée ---------

def test_action_inconnue_avec_en_tete_aucun_effet(dash):
    _, tmp, client = dash
    r = client.post("/api/ctl?action=__probe", headers=HEADER)
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "action inconnue"}
    assert not (tmp / "ctl").exists() or not list((tmp / "ctl").iterdir())


def test_pause_toggle_bascule_le_fichier(dash):
    _, tmp, client = dash
    r1 = client.post("/api/ctl?action=pause-toggle", headers=HEADER)
    assert r1.json() == {"ok": True, "action": "pause-toggle"}
    assert (tmp / "ctl" / "PAUSE").exists()
    r2 = client.post("/api/ctl?action=pause-toggle", headers=HEADER)
    assert r2.json() == {"ok": True, "action": "pause-toggle"}
    assert not (tmp / "ctl" / "PAUSE").exists()


def test_pause_sell_kill_creatent_leur_fichier_isole(dash):
    _, tmp, client = dash
    for action, name in (("pause", "PAUSE"), ("sell_all", "SELL_ALL"), ("kill", "KILL")):
        r = client.post(f"/api/ctl?action={action}", headers=HEADER)
        assert r.json() == {"ok": True, "action": action}
        assert (tmp / "ctl" / name).exists()


# --- 3. la page transmet l'en-tête (correctif B1) ------------------------------

def test_la_page_js_pose_l_en_tete_anti_csrf(dash):
    mod, _, _ = dash
    page = mod.home()
    assert 'X-Requested-With":"desk-ui"' in page
    # le fetch ctl embarque bien l'en-tête dans sa config
    assert 'method:"POST",headers:{' in page


# --- 4. lectures GET inchangées (spectateur Pages) ------------------------------

def test_get_state_lit_state_json_isole(dash):
    _, tmp, client = dash
    (tmp / "state.json").write_text(json.dumps({"ledger": {"wallet_usdt": 12.5}}),
                                     encoding="utf-8")
    r = client.get("/api/state")
    assert r.status_code == 200
    assert r.json()["ledger"]["wallet_usdt"] == 12.5


def test_get_state_vide_si_absent(dash):
    _, _, client = dash
    assert client.get("/api/state").json() == {}


def test_get_events_parse_le_jsonl_isole(dash):
    _, tmp, client = dash
    (tmp / "events.jsonl").write_text(
        json.dumps({"ts": 1, "kind": "boot",
                    "payload": {"mode": "live", "start_usdt": 30}}) + "\n",
        encoding="utf-8")
    r = client.get("/api/events?n=10")
    assert r.status_code == 200
    assert r.json()["events"][0]["kind"] == "boot"


# --- 5. protections non autorisées restent en place (CORS) ----------------------

def test_preflight_cors_marque_post_non_autorise(dash):
    _, _, client = dash
    r = client.options("/api/ctl", headers={
        "Origin": "https://example-externe.invalid",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "X-Requested-With",
    })
    # le préflight cross-origin POST n'est pas autorisé (allow_methods = GET, OPTIONS)
    allowed = r.headers.get("access-control-allow-methods", "")
    assert r.status_code != 200 or "POST" not in allowed


def test_preflight_cors_get_autorise(dash):
    _, _, client = dash
    r = client.options("/api/state", headers={
        "Origin": "https://frechfanta-os.github.io",
        "Access-Control-Request-Method": "GET",
    })
    assert r.status_code == 200
    assert "GET" in r.headers.get("access-control-allow-methods", "")
