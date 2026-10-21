from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="AIDESK desk monitor")
# Lecture (GET) ouverte pour le mode « spectateur » du site GitHub Pages ;
# les contrôles POST restent réservés à l'UI locale (anti-CSRF via en-tête).
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["GET", "OPTIONS"], allow_headers=["*"])

PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIDESK — DESK MONITOR</title>
<style>
:root{--bg:#0a0d10;--pnl0:#0e1416;--fg:#d8e3e3;--dim:#5a6a6a;--brd:#1d2a2a;
 --grn:#6dffb0;--red:#ff6e6e;--amb:#ffd28a;--blu:#8fb7ff;--cy:#7fe6e0;--vi:#c9a6ff}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);margin:0;
 font:13px/1.5 "SFMono-Regular",JetBrains Mono,Menlo,Consolas,monospace}
header{display:flex;flex-wrap:wrap;gap:14px;align-items:baseline;
 padding:10px 14px;border-bottom:1px solid var(--brd)}
header b{color:var(--grn);letter-spacing:1px}
.stat{color:var(--dim)}
.stat b{color:var(--fg);margin-left:4px;font-weight:600}
.up b{color:var(--grn)}.dn b{color:var(--red)}
#paused{border:1px solid var(--amb);color:var(--amb);padding:1px 8px;animation:bl 1.2s infinite}
@keyframes bl{50%{opacity:.35}}
main{display:grid;grid-template-columns:1fr 340px;gap:0}
@media(max-width:960px){main{grid-template-columns:1fr}}
section{padding:12px 14px;border-bottom:1px solid var(--brd)}
h2{font-size:11px;letter-spacing:2px;color:var(--dim);margin:0 0 8px;font-weight:400}
#ticker{border-left:1px solid var(--brd);overflow-y:auto;max-height:calc(100vh - 42px)}
.row{padding:5px 10px;border-bottom:1px solid #10191b;white-space:pre-wrap;word-break:break-all}
.row .k{color:var(--dim);font-size:10px;letter-spacing:1px;margin-right:6px}
.b.grn{color:var(--grn)}.b.red{color:var(--red)}.b.amb{color:var(--amb)}
.b.blu{color:var(--blu)}.b.vi{color:var(--vi)}.b.dim{color:var(--dim)}
#seats{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:6px}
.seat{background:var(--pnl0);border-left:3px solid var(--dim);padding:6px 8px;font-size:12px}
.seat .nm{color:var(--fg)}.seat .ds{color:var(--dim);font-size:10px;letter-spacing:1px}
.seat .sc{float:right;color:var(--grn)}
.seat.rev{color:var(--amb)}
.bar{height:3px;background:#152022;margin-top:5px}
.bar i{display:block;height:3px;background:var(--grn)}
.c-radar{border-color:var(--cy)}.c-research{border-color:var(--vi)}
.c-execution{border-color:var(--grn)}.c-audit{border-color:var(--amb)}
.c-treasury{border-color:var(--blu)}
table{width:100%;border-collapse:collapse;font-size:12px}
td,th{padding:4px 8px;text-align:left;border-bottom:1px solid #10191b}
th{color:var(--dim);font-weight:400;letter-spacing:1px;font-size:10px}
.pos .up{color:var(--grn)}.pos .dn{color:var(--red)}
#ctrls button{background:#10191b;color:var(--fg);border:1px solid var(--brd);
 font:inherit;font-size:11px;letter-spacing:1px;padding:6px 14px;cursor:pointer;margin-right:8px}
#ctrls button:hover{border-color:var(--dim)}
#b-kill{color:var(--red);border-color:#3a1414}
footer{padding:8px 14px;color:var(--dim);font-size:11px;letter-spacing:1px}
#hb b{color:var(--fg)}
</style></head><body>
<header>
 <b>AIDESK</b>
 <span class="stat">BANK<b id="bank">—</b></span>
 <span class="stat">VAULT<b id="vault">—</b></span>
 <span class="stat" id="netp">NET<b id="net">—</b></span>
 <span class="stat">WR<b id="wr">—</b></span>
 <span class="stat">FEES<b id="fees">—</b></span>
 <span id="paused" style="display:none">PAUSE — ENTRÉES BLOQUÉES</span>
 <span style="flex:1"></span>
 <span id="ctrls">
  <button id="b-pause">PAUSE</button><button id="b-sell">SELL ALL</button>
  <button id="b-kill">KILL</button>
 </span>
</header>
<main>
<div>
 <section><h2>ÉQUITÉ PAPER (USDT)</h2><svg id="eq" viewBox="0 0 660 190"
   style="width:100%;height:190px"></svg><span id="eqr" class="stat"></span></section>
 <section><h2>POSITIONS OUVERTES</h2>
  <table><thead><tr><th>SUM</th><th>TAILLE</th><th>ENTRÉE</th><th>COURS</th>
  <th>MOVE</th><th>ÂGE</th><th>AGENT/APPR</th></tr></thead>
  <tbody id="pos"><tr><td colspan="7" style="color:var(--dim)">aucune</td></tr></tbody>
  </table></section>
 <section><h2>SEATS</h2><div id="seats"></div></section>
 <section><h2>MATRICE &amp; RISK</h2><div id="mx" class="stat"></div></section>
</div>
<div id="ticker"><h2 style="padding:12px 10px 0">FILLS &amp; JOURNAL</h2><div id="ev"></div></div>
</main>
<footer id="hb">EN ATTENTE DU DESK…</footer>
<script>
const $=id=>document.getElementById(id);
const DCL={radar:"c-radar",research:"c-research",execution:"c-execution",
 audit:"c-audit",treasury:"c-treasury"};
const KIND={"entry":["BUY","grn"],"postmortem":["POSTMORTEM","amb"],
 "risk_block":["BLOQUE","red"],"head_review":["GROK CORE","vi"],
 "sweep":["VAULT SWEEP","blu"],"boot":["BOOT","dim"]};
const m=v=>(v<0?"−$":"$")+Math.abs(v).toFixed(2);
const p6=v=>v>=1?v.toFixed(4):v.toFixed(8);
function cls(eqpnl){return eqpnl<0?"dn":"up"}
async function poll(){
 try{const s=await fetch("/api/state").then(r=>r.json());
  if(s&&s.ledger)render(s);else hbWait();}catch(e){hbWait()}
 try{const ev=await fetch("/api/events?n=70").then(r=>r.json());
  renderEvents(ev.events||[])}catch(e){}
}
const hbWait=()=>{$("hb").innerHTML="EN ATTENTE DU DESK… lancez : <b>python3 -m aidesk</b>"};
function render(s){
 const L=s.ledger,mtm=L.mtm_usdt||0,net=L.wallet_usdt+L.vault_usdt,
  pnl=net+mtm-L.start_usdt;
 $("bank").textContent=m(L.wallet_usdt);
 $("vault").textContent=m(L.vault_usdt);
 $("net").textContent=m(net)+((mtm?`/MTM ${m(mtm)}`:""));
 $("netp").className="stat "+cls(pnl);
 $("wr").textContent=(L.wins+L.losses)?((100*L.wins/(L.wins+L.losses)).toFixed(0)+"%"):"—";
 $("fees").textContent=m(L.fees_paid);
 $("paused").style.display=s.paused?"inline":"none";
 drawEquity(L.equity||[]);
 const pos=(s.positions||[]);
 $("pos").innerHTML=pos.length?pos.map(p=>{
  const mv=p.last>0?((p.last-p.entry)/p.entry*100):0;
  return `<tr class="pos"><td>${p.symbol}</td><td>$${p.usdt.toFixed(2)}</td>
   <td>${p6(p.entry)}</td><td>${p6(p.last)}</td>
   <td class="${mv<0?'dn':'up'}">${mv>=0?"+":""}${mv.toFixed(2)}%</td>
   <td>${p.age_min.toFixed(0)}m</td>
   <td>${p.agent}/${p.approver||"—"}</td></tr>`}).join("")
  :`<tr><td colspan="7" style="color:var(--dim)">aucune</td></tr>`;
 $("seats").innerHTML=(s.agents||[]).map(a=>`<div class="seat ${DCL[a.desk]||''}">
  <span class="nm">${a.name}</span><span class="sc">${a.score.toFixed(2)}</span>
  <div class="ds">${a.desk.toUpperCase()} · ${a.rev}${a.budget!=1?' · ×'+a.budget:''}</div>
  <div class="ds">${a.wins}W / ${a.losses}L</div>
  <div class="bar"><i style="width:${Math.round(a.score*100)}%"></i></div></div>`).join("");
 const M=s.matrix,R=s.risk;
 $("mx").innerHTML=`seuil ${M.pass_threshold.toFixed(3)} · mom≥${(M.min_momentum*100).toFixed(2)}% ·
  vol×${M.min_vol_surprise.toFixed(2)} · 1h≤${(M.max_momentum_1h*100).toFixed(0)}% |
 <b class="amb">rev ${M.revisions}</b><br>
 RISK : blocages ${R.blocks} · PnL jour <b class="${cls(R.day_pnl)}">${m(R.day_pnl)}</b>
 ${R.day_frozen?' · <span class="red">STOP JOURNALIER</span>':''}
 ${R.frozen_treasury?' · <span class="red">GEL TRÉSORERIE</span>':''}`;
 const C=s.counters||{},F=s.feed||{};
 $("hb").innerHTML=
  `&lt;${F.offline?"MODE OFFLINE DE DÉMO":("FEED "+(F.name||"?").toUpperCase())}··
  ticks <b>${s.ticks}</b> · sig <b>${C.signals}</b> · dec <b>${C.decisions}</b> ·
  ent <b>${C.entries}</b> · pm <b>${C.postmortems}</b> ·
  prom <b>${C.promotions||0}</b> · lic <b>${C.firings||0}</b> · ${s.ts}&gt;
  — interface FACTUELLE : chiffres réels, pertes comprises`;
 $("b-pause").textContent=s.paused?"RESUME":"PAUSE";
}
function drawEquity(pts){
 if(!pts.length)return;
 if(pts.length===1)pts=[pts[0],pts[0]];
 const W=660,H=190,p=8,mn=Math.min(...pts),mx=Math.max(...pts),sp=mx-mn||1;
 const xy=pts.map((v,i)=>[p+i*(W-2*p)/Math.max(1,pts.length-1),
  H-p-(v-mn)/sp*(H-2*p)]);
 const up=pts[pts.length-1]>=pts[0];
 const y0=H-p-(pts[0]-mn)/sp*(H-2*p);
 $("eq").innerHTML=
  `<line x1="${p}" y1="${y0.toFixed(1)}" x2="${W-p}" y2="${y0.toFixed(1)}"
   stroke="#2a3a3a" stroke-dasharray="4 4" stroke-width="1"/>
   <polyline points="${xy.map(q=>q[0].toFixed(1)+","+q[1].toFixed(1)).join(" ")}"
   fill="none" stroke="${up?"var(--grn)":"var(--red)"}" stroke-width="2"/>`;
 $("eqr").innerHTML=`min ${m(mn)} · max ${m(mx)}`;
}
const shown=new Set();
function renderEvents(evs){
 const html=[];
 for(const e of evs){
  const k=e.kind||"?";const kk=KIND[k]||[k.toUpperCase(),"dim"];
  const tag=`<span class="k">${kk[0]}</span>`;
  if(k==="trade"){
   const d=e.note||"";const win=d.startsWith("GAIN");
   html.push(`<div class="row"><span class="b ${win?'grn':'red'}">${tag}${d}</span></div>`);
  }else if(k==="decision"){
   html.push(`<div class="row"><span class="b ${e.verdict?'grn':'dim'}">
    ${tag}${e.note}</span></div>`);
  }else{
   html.push(`<div class="row"><span class="b ${kk[1]}">${tag}${e.note||""}</span></div>`);
  }
 }
 $("ev").innerHTML=html.join("")||`<div class="row"><span class="b dim">—</span></div>`;
}
for(const [id,act] of [["b-pause","pause-toggle"],["b-sell","sell_all"],["b-kill","kill"]])
 $(id).onclick=async()=>{
  if(id==="b-kill"&&!confirm("KILL : fermer toutes les positions et arrêter le desk ?"))return;
  await fetch("/api/ctl?action="+act,{method:"POST"});setTimeout(poll,400);};
setInterval(poll,2000);poll();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return PAGE


@app.get("/api/state")
def api_state() -> dict:
    p = ROOT / "state.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


@app.get("/api/events")
def api_events(n: int = 60) -> dict:
    f = ROOT / "events.jsonl"
    out: list[dict] = []
    if f.exists():
        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
        for ln in lines:
            try:
                d = json.loads(ln)
            except Exception:
                continue
            pay = d.get("payload", {}) or {}
            kind = d.get("kind")
            if kind == "decision":
                note = (f"{pay.get('symbol','')} "
                        f"{'acheté' if pay.get('verdict') else 'refusé'} "
                        f"score {pay.get('agg',0):.2f} ({pay.get('agent','')})")
                out.append({"kind": kind, "note": note,
                            "verdict": bool(pay.get("verdict"))})
            elif kind == "head_review":
                logs = pay.get("logs") or ([pay.get("line")] if pay.get("line") else [])
                out.append({"kind": kind, "note": " · ".join(logs)[:120]})
            elif kind == "trade":
                note = (f"{('GAIN' if (pay.get('pnl') or 0) > 0 else 'PERTE')} "
                        f"{pay.get('note','')}")
                out.append({"kind": kind, "note": note})
            else:
                note = pay.get("note") or pay.get("symbol") or pay.get("line") or ""
                if kind == "entry":
                    note = (f"{pay.get('symbol')} ${pay.get('usdt')} @ "
                            f"{pay.get('price')} — {pay.get('agent')}/{pay.get('approver')}")
                elif kind == "risk_block":
                    note = f"{pay.get('symbol','')} — {pay.get('reason','')}"
                elif kind == "boot":
                    note = f"mode {pay.get('mode')} · banque ${pay.get('start_usdt')}"
                out.append({"kind": kind, "note": str(note)[:140]})
    return {"events": out}


@app.post("/api/ctl")
async def api_ctl(request: Request, action: str = "") -> dict:
    # anti-CSRF : un formulaire cross-origin ne peut pas poser cet en-tête
    if request.headers.get("x-requested-with") != "desk-ui":
        raise HTTPException(status_code=403, detail="contrôle réservé à l'UI du desk")
    ctl = ROOT / "ctl"
    ctl.mkdir(exist_ok=True)
    if action == "pause":
        (ctl / "PAUSE").touch()
    elif action == "pause-toggle":
        if (ctl / "PAUSE").exists():
            (ctl / "PAUSE").unlink()
        else:
            (ctl / "PAUSE").touch()
    elif action == "sell_all":
        (ctl / "SELL_ALL").touch()
    elif action == "kill":
        (ctl / "KILL").touch()
    else:
        return {"ok": False, "error": "action inconnue"}
    return {"ok": True, "action": action}


def main() -> None:
    import uvicorn
    host = os.getenv("AIDESK_BIND", "127.0.0.1")   # sécurité : localhost par défaut
    uvicorn.run(app, host=host, port=8787, log_level="warning")


if __name__ == "__main__":
    main()
