from __future__ import annotations

import base64
import json
import os
import sqlite3
import struct
import time
import urllib.request
from typing import Any

PUBLIC_RPCS = [
    "https://api.mainnet-beta.solana.com",      # léger : infos mint uniquement
    "https://solana-rpc.publicnode.com",
    "https://rpc.ankr.com/solana",
    "https://1rpc.io/sol",
]

JUP_PRICE_V3 = "https://lite-api.jup.ag/price/v3?ids={mint}"


class WhaleError(RuntimeError):
    pass


def rpc(method: str, params: list, timeout: float = 12.0,
        retries: int = 2, backoff: float = 4.0) -> Any:
    """JSON-RPC over free endpoints. Env AIDESK_RPC_URL (clé gratuite Helius/QuickNode/dRPC)
    passe en tête. 429 → backoff+retry ; 401/403 → endpoint exclu de la session."""
    urls: list[str] = []
    env = os.getenv("AIDESK_RPC_URL")
    if env:
        urls.append(env)
    urls += [u for u in PUBLIC_RPCS if u != env]
    dead: set[str] = set()
    last_err = ""
    for attempt in range(retries + 1):
        for url in urls:
            if url in dead:
                continue
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                               "params": params}).encode()
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.load(resp)
                if "error" in data:
                    last_err = str(data["error"])[:120]
                    continue
                return data["result"]
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code} ({url})"
                if e.code in (401, 403):
                    dead.add(url)                  # endpoint refuses (IP/géoblocage)
                elif e.code == 429:
                    time.sleep(backoff * (attempt + 1))
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"[:120]
    raise WhaleError(
        f"{method} échoué ({last_err}). Aucun RPC public gratuit n'accepte les "
        "endpoints token depuis ce réseau — créez une clé RPC gratuite "
        "(Helius/QuickNode/dRPC) et posez-la dans AIDESK_RPC_URL.")


def price_jupiter(mint: str) -> float | None:
    try:
        with urllib.request.urlopen(JUP_PRICE_V3.format(mint=mint), timeout=10) as r:
            d = json.load(r)
        node = (d.get("data") or {}).get(mint) or {}
        usd = node.get("usdPrice") or node.get("price")
        return float(usd) if usd else None
    except Exception:
        return None


def price_ccxt(symbol: str | None) -> float | None:
    """Emergency fallback: BONK/USDT-style symbol on CEX (--price-symbol)."""
    if not symbol:
        return None
    try:
        import ccxt
        ex = ccxt.binance({"enableRateLimit": True})
        return float(ex.fetch_ticker(symbol).get("last") or 0) or None
    except Exception:
        return None


def mint_info(mint: str) -> dict[str, Any]:
    """supply + autorités depuis le SEL mint account (offsets SPL fixes :
    0..4 = mint option, 4..36 = mint auth, 36..44 = supply u64, 44 = decimals,
    46..50 = freeze option, 50..82 = freeze auth)."""
    res = rpc("getAccountInfo", [mint, {"encoding": "base64"}])
    info = res.get("value") if isinstance(res, dict) else None
    if not info:
        raise WhaleError(f"compte mint introuvable : {mint}")
    raw = base64.b64decode(info["data"][0])
    (mint_opt, mint_auth) = struct.unpack("<I", raw[0:4])[0], raw[4:36]
    return {
        "supply": struct.unpack("<Q", raw[36:44])[0],
        "decimals": raw[44],
        "mint_authority": mint_opt != 0,
        "mint_authority_key": mint_auth.hex() if mint_opt else None,
        "freeze_authority": struct.unpack("<I", raw[46:50])[0] != 0,
        "freeze_authority_key": raw[50:82].hex()
        if struct.unpack("<I", raw[46:50])[0] else None,
    }


def largest_holders(mint: str, top: int = 20) -> list[dict]:
    res = rpc("getTokenLargestAccounts", [mint, {"commitment": "confirmed"}])
    out = []
    for a in (res.get("value") or [])[:top]:
        out.append({"address": a["address"],
                    "amount": float(a.get("uiAmount") or 0.0)})
    return out


def snapshot(mint: str, db: str = "whale.db",
             price_symbol: str | None = None,
             provider: "Any | None" = None) -> dict:
    """Snapshot whales + persistance + verdict. Dégrade poliment si endpoint lourd.

    Phase C : `provider` (SolanaDataProvider) consommé pour TOUTES les sources
    ; None → `resolve_provider()` (RpcProvider lecture-seule par défaut,
    OfflineProvider si `--offline`/AIDESK_SOLANA=offline). Les verdicts et le
    schéma de sortie restent identiques au chemin historique."""
    from .solana import resolve_provider

    if provider is None:
        provider = resolve_provider(price_symbol=price_symbol)
    mi_obs = provider.mint_info(mint)
    if not mi_obs.ok or mi_obs.value is None:
        raise WhaleError(f"compte mint introuvable : {mint} "
                         f"({(mi_obs.note or 'erreur inconnue')[:80]})")
    mi = mi_obs.value
    sup = mi["supply"] / (10 ** mi["decimals"]) if mi["decimals"] else 0.0
    hold_obs = provider.largest_holders(mint)
    heavy_ok = bool(hold_obs.ok) and hold_obs.value is not None
    holders = list(hold_obs.value) if heavy_ok else []
    heavy_err = "" if heavy_ok else (hold_obs.note or "indisponible")
    top10 = sum(h["amount"] for h in holders[:10]) if heavy_ok else None
    top20 = sum(h["amount"] for h in holders) if heavy_ok else None
    # sémantique legacy conservée : heavy_ok + supply nulle → 0.0 (comportement
    # historique). supply inconnue en pratique impossible pour un mint valide.
    top10_pct = (top10 / sup) if (heavy_ok and sup) else (0.0 if heavy_ok else None)
    top20_pct = (top20 / sup) if (heavy_ok and sup) else (0.0 if heavy_ok else None)
    px_obs = provider.price(mint)
    price = px_obs.value if px_obs.ok else None
    prev = previous(mint, db)
    delta = (top10_pct - prev) if (top10_pct is not None and prev is not None) else None
    if not heavy_ok:
        verdict = f"PARTIEL (RPC lourd indisponible — {heavy_err[:80]})"
    elif mi["mint_authority"] or mi["freeze_authority"]:
        verdict = "RUG-RISK (autorité mint/freeze NON révoquée)"
    elif top10_pct > 0.55:
        verdict = "CONCENTRÉ (top10 > 55 % de la supply)"
    elif delta is not None and abs(delta) > 0.10:
        verdict = f"MOUVEMENT WHALE (Δ top10 {delta * 100:+.1f} pts)"
    else:
        verdict = "OBSERVATION (distribution normale)"
    delta = (top10_pct - prev) if (top10_pct is not None and prev is not None) else None
    if not heavy_ok:
        verdict = f"PARTIEL (RPC lourd indisponible — {heavy_err[:80]})"
    elif mi["mint_authority"] or mi["freeze_authority"]:
        verdict = "RUG-RISK (autorité mint/freeze NON révoquée)"
    elif top10_pct > 0.55:
        verdict = "CONCENTRÉ (top10 > 55 % de la supply)"
    elif delta is not None and abs(delta) > 0.10:
        verdict = f"MOUVEMENT WHALE (Δ top10 {delta * 100:+.1f} pts)"
    else:
        verdict = "OBSERVATION (distribution normale)"
    data: dict[str, Any] = {
        "ts": time.time(), "mint": mint,
        "supply": sup, "decimals": mi["decimals"],
        "price": price,
        "top10_pct": round(top10_pct, 4) if top10_pct is not None else None,
        "top20_pct": round(top20_pct, 4) if top20_pct is not None else None,
        "delta_top10": None if delta is None else round(delta, 4),
        "mint_authority": mi["mint_authority"],
        "freeze_authority": mi["freeze_authority"],
        "verdict": verdict, "holders": holders,
    }
    persist(mint, data, db)
    return data


def _mdb(db: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS whale_snaps ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, mint TEXT, supply REAL, "
        "price REAL, top10_pct REAL, top20_pct REAL, delta REAL, "
        "mint_authority INTEGER, freeze_authority INTEGER, verdict TEXT, details TEXT)"
    )
    conn.commit()
    return conn


def persist(mint: str, data: dict, db: str = "whale.db") -> None:
    conn = _mdb(db)
    conn.execute(
        "INSERT INTO whale_snaps (ts, mint, supply, price, top10_pct, top20_pct,"
        " delta, mint_authority, freeze_authority, verdict, details) VALUES"
        " (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (data["ts"], data["mint"], data["supply"], data["price"],
         data["top10_pct"], data["top20_pct"], data["delta_top10"],
         int(data["mint_authority"]), int(data["freeze_authority"]),
         data["verdict"], json.dumps(data["holders"])),
    )
    conn.commit()
    conn.close()


def previous(mint: str, db: str = "whale.db") -> float | None:
    conn = _mdb(db)
    row = conn.execute(
        "SELECT top10_pct FROM whale_snaps WHERE mint = ? ORDER BY id DESC LIMIT 1",
        (mint,),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def watch_balances(addresses: list[str]) -> list[dict]:
    """Lamports + comptes tokens pour chaque wallet surveillé."""
    out = []
    for addr in addresses:
        try:
            res = rpc("getAccountInfo", [addr])
            info = res.get("value")
            lam = float(info["lamports"]) / 1e9 if info else 0.0
        except Exception:
            lam = -1.0
        try:
            toks = rpc("getTokenAccountsByOwner", [
                addr,
                {"programId": "TokenkegQfeZyiNwAJb77gSddzibwY6b4m2JhcMc9m2V"},
                {"encoding": "jsonParsed"}])
            n_tok = len(toks.get("value") or [])
        except Exception:
            n_tok = -1
        out.append({"wallet": addr, "sol": lam, "tokens": n_tok})
    return out


def features_for_research(snap: dict) -> dict:
    """Features pour une future intégration RESEARCH (module memecoin).
    top10 inconnu (RPC lourd fermé) → None porté au scoring, jamais confondu avec 0."""
    t10 = snap.get("top10_pct")
    base = {
        "rug_risk": int(snap["mint_authority"] or snap["freeze_authority"]),
        "price_floor": snap.get("price"),
    }
    if t10 is None:
        base |= {"whale_top10_pct": None, "whale_concentration": None,
                 "whale_delta": None, "whale_known": False}
    else:
        base |= {"whale_top10_pct": t10,
                 "whale_concentration": round(max(0.0, (t10 - 0.35)) / 0.65, 3),
                 "whale_delta": snap.get("delta_top10"),
                 "whale_known": True}
    return base
