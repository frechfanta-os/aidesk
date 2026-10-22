"""Tests B8 — rotation archivistique du miroir JSONL.

Contrat : JAMAIS de suppression. En dépassant le seuil, le JSONL courant est
renommé `.archive-<stamp>`, un nouveau JSONL commence par un marqueur
`kind=rotate`, et TOUTES les lignes écrites restent lisibles (archives+nouveau).
SQLite reste la source de vérité (non affectée).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from aidesk.store import Store, _archive_name  # noqa: E402


def read_jsonl(p: Path) -> list[dict]:
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


def test_rotation_archive_et_marqueur(tmp_path):
    p = tmp_path / "t.jsonl"
    st = Store(str(tmp_path / "t.db"), str(p), jsonl_max_bytes=200)
    for i in range(12):
        st.add_event("pulse", {"i": i})          # ~55 o/ligne → 650 > 200 : n rotations
    main = read_jsonl(p)
    archs = sorted(x for x in tmp_path.iterdir()
                   if x.name.startswith("t.jsonl.archive-"))
    assert archs, "au moins une archive produite"
    for a in archs:
        evs = read_jsonl(a)
        # archives = pulses précédés éventuellement du marqueur de rotation
        # précédente (le courant devient archive au tour suivant) — par design
        assert set(e["kind"] for e in evs) <= {"pulse", "rotate"}
        for j, e in enumerate(evs):                 # marqueur uniquemente en tête
            assert (e["kind"] == "rotate") == (j == 0 and evs[0]["kind"] == "rotate")
    assert main[0]["kind"] == "rotate"               # marqueur en tête
    # le marqueur pointe vers une archive EXISTANTE de la même rotation
    assert main[0]["payload"]["archive"] in {a.name for a in archs}
    assert main[0]["payload"]["bytes"] >= 200        # seuil rééllement dépassé
    # zéro perte : les 12 pulses se retrouvent dans archives + fichier courant
    pulse = [e for a in archs for e in read_jsonl(a)
             if e["kind"] == "pulse"] + \
            [e for e in main if e["kind"] == "pulse"]
    assert sorted(e["payload"]["i"] for e in pulse) == list(range(12))
    # lancement : soit sous le seuil, soit au pire UNE ligne de trop (jamais
    # scindée) — la rotation se déclenche à l'émission suivante
    lines_now = read_jsonl(p)                        # tout parsable, lignes intactes
    assert lines_now and st._fh.tell() <= 200 + 2 * 200
    st.close()


def test_glob_archive_nom_unique(tmp_path):
    """Collision : l'archive existante est préservée, le suffixe .1 est nouveau."""
    existant = tmp_path / "e.jsonl.archive-20260101T000000"
    existant.write_text("ancien")                     # jamais écrasé
    base = tmp_path / "e.jsonl"
    base.write_text("courant")
    got = _archive_name(base, "20260101T000000")
    assert got.name == "e.jsonl.archive-20260101T000000.1"
    assert not got.exists()                          # nom libre pour le rename
    assert existant.read_text() == "ancien"          # l'existante intacte


def test_sous_le_seuil_aucune_rotation(tmp_path):
    p = tmp_path / "small.jsonl"
    st = Store(str(tmp_path / "t.db"), str(p), jsonl_max_bytes=10_000_000)
    for i in range(5):
        st.add_event("pulse", {"i": i})
    assert not list(tmp_path.iterdir()) == []      # fichier existe
    assert not any(x.name.startswith("small.jsonl.archive")
                   for x in tmp_path.iterdir())
    assert len(read_jsonl(p)) == 5
    st.close()


def test_sqlite_source_de_verite_independante(tmp_path):
    """La rotation du miroir ne touche PAS la table events."""
    st = Store(str(tmp_path / "t.db"), str(tmp_path / "t.jsonl"),
               jsonl_max_bytes=100)
    for i in range(15):
        st.add_event("pulse", {"i": i, "pad": "x" * 20})
    n_db = st.conn.execute("SELECT count(*) FROM events").fetchone()[0]
    assert n_db == 15                              # RIEN perdu côté SQLite
    st.close()
