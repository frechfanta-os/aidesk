from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aidesk.market import whale  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="whale_scan",
        description="Scanner on-chain Solana : concentration, autorités mint/freeze, "
                    "mouvement whale — snapshot persistant (whale.db).",
    )
    ap.add_argument("--mint", help="adresse du mint SPL (requis sans --watchlist)")
    ap.add_argument("--watchlist", help="fichier : une adresse wallet par ligne")
    ap.add_argument("--price-symbol", default=None,
                    help="fallback CEX si Jupiter échoué (ex: BONK/USDT)")
    ap.add_argument("--offline", action="store_true",
                    help="mode offline explicite : aucun appel réseau, données "
                         "marquées ABSENTES (Phase C — jamais de zéros inventés)")
    ap.add_argument("--db", default="whale.db")
    args = ap.parse_args()

    from aidesk.market.solana import resolve_provider
    provider = resolve_provider(offline=args.offline, price_symbol=args.price_symbol)

    if args.watchlist:
        addrs = [ln.strip() for ln in Path(args.watchlist).read_text()
                 .splitlines() if ln.strip() and not ln.startswith("#")]
        tag = " (OFFLINE — données absentes)" if args.offline else ""
        print(f"== WATCHLIST ({len(addrs)} wallets){tag} ==")
        for w in provider.watch(addrs):
            sol = "RPC fail" if w.sol < 0 else f"{w.sol:,.2f} SOL"
            print(f"  {w.wallet:<48} {sol} | token accts {w.tokens}")

    if not args.mint:
        if not args.watchlist:
            ap.error("--mint et/ou --watchlist requis")
        return

    print(f"== SNAPSHOT {args.mint} ==")
    try:
        snap = whale.snapshot(args.mint, db=args.db,
                              price_symbol=args.price_symbol, provider=provider)
    except whale.WhaleError as e:
        print(f"  ÉCHEC : {e}")
        return
    print(f"  supply   : {snap['supply']:,.2f}")
    pr = f"{snap['price']:.10g} $" if snap["price"] else "prix indisponible"
    print(f"  price    : {pr}")
    t10, t20 = snap["top10_pct"], snap["top20_pct"]
    if t10 is None:
        print("  top10    : indisponible (endpoint RPC lourd refusé — clé gratuite requise)")
    else:
        print(f"  top10    : {t10 * 100:.1f} % de la supply "
              f"(top20 {t20 * 100:.1f} %)")
    if snap["delta_top10"] is not None:
        print(f"  Δ top10  : {snap['delta_top10'] * 100:+.2f} pts depuis le dernier scan")
    print(f"  authority: mint={'ACTIVE' if snap['mint_authority'] else 'revocée'} "
          f"freeze={'ACTIVE' if snap['freeze_authority'] else 'révoquée'}")
    print(f"  VERDICT  : {snap['verdict']}")
    print("\n  += top holders =+")
    for i, h in enumerate(snap["holders"][:15], 1):
        shr = (h["amount"] / snap["supply"] * 100) if snap["supply"] else 0
        print(f"  {i:>2}. {h['address']}  {shr:5.1f} %  {h['amount']:,.2f}")
    print(f"\n  features RESEARCH : {whale.features_for_research(snap)}")
    print("  (historique : whale.db, table whale_snaps)")


if __name__ == "__main__":
    main()
