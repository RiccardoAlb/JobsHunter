"""Misura manuale (non e' un test): .venv/bin/python tests/qa/measure_dedupe.py  -> metriche e coppie sbagliate."""
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qa import dedupe_eval as ev  # noqa: E402


def show(name, m, cases):
    print(f"\n== {name}: precisione {m['precision']:.3f}  richiamo {m['recall']:.3f}  (TP {m['tp']}, FP {len(m['fp'])}, FN {len(m['fn'])})")
    for tag, lst in (("FALSO DUPLICATO", m["fp"]), ("DUPLICATO MANCATO", m["fn"])):
        for c in lst:
            a, b = c["a"], c["b"]
            print(f"  {tag} {c['id']} [{c['sector']}/{c['lang']}] {a['title']} | {a['company']} | {a['location']}  <>  "
                  f"{b['title']} | {b['company']} | {b['location']}  pct={c.get('_pct')}  ({c['note']})")


if __name__ == "__main__":
    import os
    os.environ["JOBSHUNTER_HOME"] = tempfile.mkdtemp()
    from jobshunter import settings
    cfg = settings.load_config(create_if_missing=True)
    cases = ev.load_cases(holdout="holdout" in sys.argv)
    which = sys.argv[1] if len(sys.argv) > 1 else "attuale"   # "fase1" = copia fedele del codice di partenza
    impl = ev.phase1() if which == "fase1" else None
    print("IMPLEMENTAZIONE:", "fase 1 (riferimento fedele)" if impl else "codice attuale in jobshunter/dedupe.py")
    pred = ev.predict_similarity(cases, 75, impl)
    show("similarity (soglia 75)", ev.metrics(cases, pred), cases)
    for thr in (60, 65, 70, 80, 85, 90):
        m = ev.metrics(cases, {c["id"]: c["_pct"] is not None and c["_pct"] >= thr for c in cases})
        print(f"   soglia {thr}: P={m['precision']:.3f} R={m['recall']:.3f}")
    if not impl:
        show("find_duplicates", ev.metrics(cases, ev.predict_find_duplicates(cases, cfg, Path(tempfile.mkdtemp()))), cases)
