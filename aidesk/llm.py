from __future__ import annotations

import json
import os
from pathlib import Path

# Breaker SKEPTIC : après DEAD_AFTER échecs consécutifs, fournisseur suspendu
# COOLDOWN_S — une clé morte/quota vide ne peut jamais bloquer la boucle desk.
DEAD_AFTER = 3
COOLDOWN_S = 600.0
_FAIL: dict[str, float] = {"n": 0, "until": 0.0}


def _load_dotenv() -> None:
    """Charge .env (CWD en priorité, puis racine projet) — os.environ.setdefault."""
    for p in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        try:
            if p.exists():
                for ln in p.read_text().splitlines():
                    ln = ln.strip()
                    if ln and not ln.startswith("#") and "=" in ln:
                        k, v = ln.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
        except Exception:
            pass


_load_dotenv()


def has_key() -> bool:
    return bool(os.getenv("XAI_API_KEY") or os.getenv("OPENAI_API_KEY")
                or os.getenv("AIDESK_LLM_KEY"))


def _resolve() -> tuple[str, str, str] | None:
    key = os.getenv("XAI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("AIDESK_LLM_KEY")
    if not key:
        return None
    base = os.getenv("AIDESK_LLM_BASE_URL", "https://api.x.ai/v1").rstrip("/")
    model = os.getenv("AIDESK_LLM_MODEL", "grok-3-fast")
    return key, base, model


def describe(f, checks: dict[str, bool], agg: float, verdict: bool) -> str:
    """Deterministic offline thesis. The LLM (if any) only adds the skeptic line."""
    mom15 = f.mom_15m * 100
    mom1h = f.mom_1h * 100
    ok = [k for k, v in checks.items() if v]
    ko = [k for k, v in checks.items() if not v]
    head = "THÈSE ACHAT" if verdict else "OBSERVATION"
    txt = (
        f"{head} — {f.symbol} @ {f.last:g} $ | mom15 {mom15:+.2f} % (1h {mom1h:+.2f} %) | "
        f"volume ×{f.vol_surprise:.1f} vs rythme 24h | liq {f.quote_volume_24h / 1e6:.1f} M$ | "
        f"checks OK [{', '.join(ok) or '—'}]"
        + (f" | KO [{', '.join(ko)}]" if ko else "")
        + f" | score {agg:.2f}"
    )
    return txt


def critique(features_line: str, thesis: str) -> str | None:
    """SKEPTIC counter-argument via an OpenAI-compatible endpoint.

    Resilience: after DEAD_AFTER consecutive failures the remote is suspended
    for COOLDOWN_S so a dead/quota-empty key can never stall the desk loop."""
    import time as _time
    if _time.time() < _FAIL["until"]:
        return None
    r = _resolve()
    if not r:
        return None
    key, base, model = r
    try:
        from openai import OpenAI
        try:
            import httpx
            tmo: Any = httpx.Timeout(30.0, connect=8.0, read=20.0, write=10.0, pool=8.0)
        except ImportError:
            tmo = 25.0
        client = OpenAI(
            base_url=base, api_key=key,
            timeout=tmo,
            max_retries=0,
        )
        parts: list[str] = []
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu es SKEPTIC, agent de desk irascible. En 50 mots maximum, "
                        "formule l'objection la plus forte contre l'achat décrit. Français."
                    ),
                },
                {"role": "user", "content": f"{thesis}\nDonnées: {features_line}"},
            ],
            max_tokens=150,
            temperature=0.3,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    parts.append(delta.content)
        _FAIL["n"] = 0
        return "".join(parts).strip() or None
    except Exception:
        _FAIL["n"] += 1
        if _FAIL["n"] >= DEAD_AFTER:
            _FAIL["until"] = _time.time() + COOLDOWN_S
            _FAIL["n"] = 0
        return None
