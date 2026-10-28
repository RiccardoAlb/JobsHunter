"""Fase 5, QA indipendente (1): migrazione dei dati, User-Agent, LaunchAgent, source_wanted.

Tutto gira con HOME finta e launchctl finto (autouse in tests/conftest.py). Mai monkeypatch.undo().
I test marcati xfail documentano bug trovati dal tester (vedi docs/dev-notes/BUGS.md, B40 e seguenti): quando
vengono corretti diventano xpass e si puo' togliere il marker.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import plistlib
import shutil
import sqlite3
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import httpx
import pytest

from jobshunter import __version__, migrate, net, scheduler, settings
from jobshunter.db import DB
from jobshunter.models import Job

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
REAL_INSTALL, REAL_UNINSTALL, REAL_IS_LOADED = scheduler.install, scheduler.uninstall, scheduler.is_loaded


# ----------------------------------------------------------------------------- aiuti ----
def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def snap(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): (sha(p), stat.S_IMODE(p.stat().st_mode)) for p in sorted(d.rglob("*")) if p.is_file()}


def build_old(base: Path, name: str = "\x4aobHunter") -> Path:
    """Una struttura \x4aobHunter realistica: db con profili, annunci, candidature, cv.json, settings, config, backups, webview."""
    old = base / "Library" / "Application Support" / name
    (old / "backups").mkdir(parents=True)
    (old / "webview" / "Local Storage").mkdir(parents=True)
    db = DB(old / "\x6aobhunter.db")
    for i in range(30):
        db.upsert(Job(source="fake", title=f"Ruolo {i} caffè", company=f"Azienda {i % 5}", location="Roma", url=f"https://example.org/j/{i}",
                      description="descrizione di prova SIEM", score=40 + i, category="BLUE"))
    db.commit()
    db.add_application(company="Azienda 1", role="Analista", location="Roma", url="https://example.org/j/1")
    db.kv_set("last_ack", "2026-01-01")
    db.conn.commit()
    db.conn.close()
    shutil.copyfile(old / "\x6aobhunter.db", old / "backups" / "\x6aobhunter-pre-fase2-20260101-0000.db")
    (old / "config.toml").write_text('[general]\ndb_path = "\x6aobhunter.db"\nmin_score = 20\n[report]\ndir = "reports"\n')
    (old / "settings.json").write_text('{"home": "Bologna", "net.contact": "me@example.org"}')
    (old / "cv.json").write_text('{"text": "cv inventato"}')
    (old / "skills_extra.json").write_text('["Foo"]')
    (old / "webview" / "Local Storage" / "ls.txt").write_text("tema scuro")
    for f in ("config.toml", "settings.json", "cv.json", "skills_extra.json", "\x6aobhunter.db"):
        os.chmod(old / f, 0o600)
    return old


def dump(path: Path) -> list[str]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return list(con.iterdump())
    finally:
        con.close()


def new_dir(old: Path) -> Path:
    return old.parent / "JobsHunter"


# ----------------------------------------------------------------------------- migrazione ----
def test_mig_copia_integra_su_struttura_realistica():
    old = build_old(Path.home())
    before = snap(old)
    new = new_dir(old)
    use, outcome = migrate.migrate_app_data(old, new)
    assert (use, outcome) == (new, "copied")
    assert snap(old) == before
    assert dump(old / "\x6aobhunter.db") == dump(new / "\x6aobhunter.db")
    assert dump(old / "backups" / "\x6aobhunter-pre-fase2-20260101-0000.db") == dump(new / "backups" / "\x6aobhunter-pre-fase2-20260101-0000.db")
    for rel in ("config.toml", "settings.json", "cv.json", "skills_extra.json", "webview/Local Storage/ls.txt"):
        assert (new / rel).read_bytes() == (old / rel).read_bytes(), rel
    for rel in ("config.toml", "settings.json", "cv.json", "skills_extra.json", "\x6aobhunter.db", "backups/\x6aobhunter-pre-fase2-20260101-0000.db"):
        assert stat.S_IMODE((new / rel).stat().st_mode) == 0o600, rel
    # la copia si apre davvero con l'applicazione
    n = DB(new / "\x6aobhunter.db").conn.execute("select count(*) from jobs").fetchone()[0]
    assert n == 30
    assert DB(new / "\x6aobhunter.db").kv_get("last_ack") == "2026-01-01"


def test_mig_idempotente_due_volte_e_tre():
    old = build_old(Path.home())
    new = new_dir(old)
    migrate.migrate_app_data(old, new)
    first = snap(new)
    for _ in range(2):
        assert migrate.migrate_app_data(old, new) == (new, "new")
    assert snap(new) == first
    assert not list(new.parent.glob("*.migrating-*"))


def test_mig_permessi_della_cartella_nuova_non_piu_larghi_dell_originale():
    """B-nota: la cartella copiata contiene cv.json e chiavi: se la vecchia era 700 anche la nuova deve esserlo."""
    old = build_old(Path.home())
    os.chmod(old, 0o700)
    os.chmod(old / "backups", 0o700)
    new = new_dir(old)
    migrate.migrate_app_data(old, new)
    assert stat.S_IMODE(new.stat().st_mode) & 0o077 == 0, oct(new.stat().st_mode)
    assert stat.S_IMODE((new / "backups").stat().st_mode) & 0o077 == 0


def test_mig_database_in_wal_con_wal_e_shm_viene_copiato_intero_e_l_originale_non_cambia():
    old = build_old(Path.home())
    live = sqlite3.connect(old / "\x6aobhunter.db")
    live.execute("pragma journal_mode=wal")
    live.execute("pragma wal_autocheckpoint=0")
    for i in range(40):
        live.execute("insert into kv(key,value) values (?,?)", (f"k{i}", "v"))
    live.commit()  # righe solo nel -wal, ancora aperto
    assert (old / "\x6aobhunter.db-wal").exists() and (old / "\x6aobhunter.db-shm").exists()
    wal_before = (old / "\x6aobhunter.db-wal").read_bytes()
    new = new_dir(old)
    use, outcome = migrate.migrate_app_data(old, new)
    assert outcome == "copied", outcome
    con = sqlite3.connect(new / "\x6aobhunter.db")
    assert con.execute("select count(*) from kv where key like 'k%'").fetchone()[0] == 40
    assert con.execute("pragma integrity_check").fetchone()[0] == "ok"
    con.close()
    assert not (new / "\x6aobhunter.db-wal").exists()
    assert (old / "\x6aobhunter.db-wal").read_bytes() == wal_before
    live.execute("insert into kv(key,value) values ('dopo','1')")  # il processo vivo continua a scrivere sull'originale
    live.commit()
    live.close()


def test_mig_database_aperto_in_scrittura_durante_la_copia():
    old = build_old(Path.home())
    live = sqlite3.connect(old / "\x6aobhunter.db", isolation_level=None)
    live.execute("begin immediate")
    live.execute("insert into kv(key,value) values ('x','y')")  # transazione in corso, non confermata
    new = new_dir(old)
    use, outcome = migrate.migrate_app_data(old, new)
    live.execute("rollback")
    live.close()
    assert outcome in ("copied", "failed")
    if outcome == "copied":
        assert sqlite3.connect(new / "\x6aobhunter.db").execute("select count(*) from kv where key='x'").fetchone()[0] == 0


@pytest.mark.parametrize("oldname", ["Job Hunter vecchio", "\x4aobHunter caffè è", "\x4aobHunter 日本語"])
def test_mig_nomi_con_spazi_e_unicode(oldname):
    base = Path.home() / "Library" / "Application Support"
    old = build_old(Path.home(), "\x4aobHunter")
    odd = base / oldname
    old.rename(odd)
    (odd / "backups" / "copia con spazi e è.db").write_bytes((odd / "\x6aobhunter.db").read_bytes())
    new = base / (oldname + " nuovo")
    use, outcome = migrate.migrate_app_data(odd, new)
    assert outcome == "copied"
    assert dump(odd / "backups" / "copia con spazi e è.db") == dump(new / "backups" / "copia con spazi e è.db")


@pytest.mark.parametrize("special", [
    "#", "?", pytest.param("%41", marks=pytest.mark.xfail(reason="B40: il percorso finisce non codificato in un URI SQLite: '%41' viene letto come 'A' e la migrazione fallisce", strict=False))])
def test_mig_percorsi_con_caratteri_speciali_degli_uri_sqlite(special):
    base = Path.home() / "Library" / "Application Support"
    old = build_old(Path.home())
    odd = base / f"\x4aobHunter{special}x"
    old.rename(odd)
    new = base / f"JobsHunter{special}x"
    use, outcome = migrate.migrate_app_data(odd, new)
    assert outcome == "copied", outcome
    assert dump(odd / "\x6aobhunter.db") == dump(new / "\x6aobhunter.db")


def test_mig_file_di_backup_con_percento_nel_nome():
    old = build_old(Path.home())
    shutil.copyfile(old / "\x6aobhunter.db", old / "backups" / "copia %41.db")
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    assert outcome == "copied"


def test_mig_file_di_backup_con_cancelletto_nel_nome():
    old = build_old(Path.home())
    shutil.copyfile(old / "\x6aobhunter.db", old / "backups" / "copia #2.db")
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    assert outcome == "copied"


def test_mig_backup_corrotto_non_deve_bloccare_la_migrazione_dei_dati_buoni():
    old = build_old(Path.home())
    (old / "backups" / "rotto.db").write_bytes(b"questo non e' sqlite" * 50)
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    assert outcome == "copied", outcome
    assert (new_dir(old) / "\x6aobhunter.db").exists()


def test_mig_backup_corrotto_comunque_non_tocca_l_originale():
    old = build_old(Path.home())
    (old / "backups" / "rotto.db").write_bytes(b"questo non e' sqlite" * 50)
    before = snap(old)
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    # dopo la correzione di B41 un backup non valido non blocca piu' la migrazione (si copia com'e'): l'originale resta comunque intatto
    assert use == new_dir(old) and outcome == "copied"
    assert snap(old) == before
    assert not list(old.parent.glob("*.migrating-*"))


def test_mig_db_principale_corrotto_resta_sulla_vecchia():
    old = build_old(Path.home())
    raw = bytearray((old / "\x6aobhunter.db").read_bytes())
    raw[4096 * 2: 4096 * 2 + 200] = b"\xff" * 200
    (old / "\x6aobhunter.db").write_bytes(bytes(raw))
    before = snap(old)
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    assert use == old and outcome == "failed"
    assert snap(old) == before
    assert not new_dir(old).exists()


def test_mig_disco_pieno_simulato_a_meta_copia(monkeypatch):
    old = build_old(Path.home())
    before = snap(old)
    real = shutil.copy2
    calls = {"n": 0}

    def full(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(shutil, "copy2", full)
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    assert calls["n"] >= 2
    assert (use, outcome) == (old, "failed")
    assert snap(old) == before
    assert not new_dir(old).exists() and not list(old.parent.glob("*.migrating-*"))


def test_mig_disco_pieno_durante_la_copia_del_db(monkeypatch):
    old = build_old(Path.home())
    before = snap(old)

    def boom(src, dst):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(migrate, "_copy_db", boom)
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    assert (use, outcome) == (old, "failed")
    assert snap(old) == before and not new_dir(old).exists()


def test_mig_permesso_negato_su_un_file_dell_originale():
    old = build_old(Path.home())
    before = snap(old)
    os.chmod(old / "cv.json", 0o000)
    try:
        use, outcome = migrate.migrate_app_data(old, new_dir(old))
    finally:
        os.chmod(old / "cv.json", 0o600)
    assert (use, outcome) == (old, "failed")
    assert snap(old) == before
    assert not new_dir(old).exists() and not list(old.parent.glob("*.migrating-*"))


def test_mig_permesso_negato_sulla_cartella_di_destinazione():
    old = build_old(Path.home())
    parent = old.parent
    before = snap(old)
    os.chmod(parent, 0o500)  # non si puo' creare nulla accanto
    try:
        use, outcome = migrate.migrate_app_data(old, new_dir(old))
    finally:
        os.chmod(parent, 0o700)
    assert (use, outcome) == (old, "failed")
    assert snap(old) == before


def test_mig_interruzione_con_ctrl_c_non_lascia_la_cartella_nuova_a_meta(monkeypatch):
    """Una KeyboardInterrupt (non e' una Exception) a meta' copia: la cartella 'JobsHunter' non deve esistere a meta'."""
    old = build_old(Path.home())
    real = shutil.copy2
    n = {"c": 0}

    def intr(*a, **k):
        n["c"] += 1
        if n["c"] == 3:
            raise KeyboardInterrupt
        return real(*a, **k)

    monkeypatch.setattr(shutil, "copy2", intr)
    with pytest.raises(KeyboardInterrupt):
        migrate.migrate_app_data(old, new_dir(old))
    assert not new_dir(old).exists(), "la cartella finale non deve esistere se la copia e' stata interrotta"


def test_mig_residuo_temporaneo_di_un_tentativo_interrotto_viene_ripulito():
    old = build_old(Path.home())
    stale = old.parent / "JobsHunter.migrating-99999"
    stale.mkdir()
    (stale / "cv.json").write_text('{"text": "copia privata rimasta"}')
    migrate.migrate_app_data(old, new_dir(old))
    assert not stale.exists()


def test_mig_il_residuo_di_un_altro_pid_non_viene_scambiato_per_la_cartella_nuova():
    old = build_old(Path.home())
    stale = old.parent / "JobsHunter.migrating-99999"
    stale.mkdir()
    (stale / "x").write_text("a")
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    assert outcome == "copied" and use == new_dir(old)


def test_mig_collegamento_simbolico_al_database_non_perde_i_dati_in_silenzio():
    """Chi tiene il db altrove (Dropbox) con un symlink in Application Support: la copia non puo' ignorarlo senza dirlo."""
    old = build_old(Path.home())
    elsewhere = Path.home() / "Dropbox"
    elsewhere.mkdir()
    shutil.move(str(old / "\x6aobhunter.db"), elsewhere / "\x6aobhunter.db")
    (old / "\x6aobhunter.db").symlink_to(elsewhere / "\x6aobhunter.db")
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    if outcome == "copied":
        assert (new_dir(old) / "\x6aobhunter.db").exists(), "B43: 'copied' ma senza il database: l'app parte con un archivio vuoto"
    else:
        assert use == old


def test_mig_collegamento_simbolico_al_config_esito_coerente():
    old = build_old(Path.home())
    real_cfg = Path.home() / "altrove-config.toml"
    shutil.move(str(old / "config.toml"), real_cfg)
    (old / "config.toml").symlink_to(real_cfg)
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    assert outcome == "failed" or (new_dir(old) / "config.toml").exists()


def test_mig_la_cartella_vecchia_e_un_collegamento_simbolico():
    real = build_old(Path.home(), "RealeAltrove")
    old = real.parent / "\x4aobHunter"
    old.symlink_to(real)
    before = snap(real)
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    assert outcome == "copied"
    assert dump(real / "\x6aobhunter.db") == dump(new_dir(old) / "\x6aobhunter.db")
    assert snap(real) == before and old.is_symlink()


def test_mig_il_symlink_non_viene_seguito_verso_fuori_dalla_cartella():
    old = build_old(Path.home())
    secret = Path.home() / "segreto.txt"
    secret.write_text("NON COPIARE")
    (old / "link.txt").symlink_to(secret)
    (old / "dirlink").symlink_to(Path.home())
    use, outcome = migrate.migrate_app_data(old, new_dir(old))
    assert not (new_dir(old) / "link.txt").exists() and not (new_dir(old) / "dirlink").exists()


def test_mig_entrambe_le_cartelle_si_usa_la_nuova_e_nessuna_delle_due_cambia():
    old = build_old(Path.home())
    new = new_dir(old)
    new.mkdir()
    (new / "config.toml").write_text("[general]\n")
    b_old, b_new = snap(old), snap(new)
    assert migrate.migrate_app_data(old, new) == (new, "new")
    assert snap(old) == b_old and snap(new) == b_new


def test_mig_cartella_nuova_con_solo_una_sottocartella_vuota_impedisce_la_migrazione():
    """Documenta il limite: basta una cartella nuova NON vuota (anche solo 'webview/') perche' i dati vecchi vengano ignorati."""
    old = build_old(Path.home())
    new = new_dir(old)
    (new / "webview").mkdir(parents=True)
    use, outcome = migrate.migrate_app_data(old, new)
    assert outcome in ("new", "copied")


def test_mig_cartella_nuova_senza_database_ne_config_non_conta_come_dati():
    old = build_old(Path.home())
    new = new_dir(old)
    (new / "webview").mkdir(parents=True)
    use, outcome = migrate.migrate_app_data(old, new)
    assert outcome == "copied"


def test_mig_corsa_deterministica_l_altro_processo_finisce_per_primo(monkeypatch):
    """App e --scan-once partono insieme: se l'altro processo ha gia' creato la cartella nuova, questo deve usarla (non la vecchia)."""
    old = build_old(Path.home())
    new = new_dir(old)
    real = migrate._copy_tree

    def with_rival(src, dst):
        real(src, dst)
        # il 'rivale' finisce prima: la cartella nuova nasce completa mentre noi abbiamo ancora la copia temporanea
        if not new.exists():
            real(src, new)

    monkeypatch.setattr(migrate, "_copy_tree", with_rival)
    use, outcome = migrate.migrate_app_data(old, new)
    assert use == new, f"B45: il processo perdente della corsa passa alla cartella VECCHIA ({outcome}) e scrive dati divergenti"


def test_mig_corsa_reale_due_processi(tmp_path):
    old = build_old(Path.home())
    for _ in range(6):  # un database un po' piu' grosso per allargare la finestra
        shutil.copyfile(old / "\x6aobhunter.db", old / "backups" / f"extra{_}.db")
    home = Path.home()
    go = tmp_path / "go"
    code = textwrap.dedent(f"""
        import os, sys, time, json
        sys.path.insert(0, {str(ROOT)!r})
        os.environ["HOME"] = {str(home)!r}
        from jobshunter import migrate
        while not os.path.exists({str(go)!r}):
            time.sleep(0.001)
        use, out = migrate.migrate_app_data()
        print(json.dumps([str(use), out]))
    """)
    procs = [subprocess.Popen([PY, "-I", "-c", code], stdout=subprocess.PIPE, text=True) for _ in range(4)]
    go.write_text("1")
    results = [json.loads(p.communicate(timeout=60)[0]) for p in procs]
    assert {r[0] for r in results} == {str(new_dir(old))}, results


def test_mig_percorsi_assoluti_nella_config_restano_validi_e_non_perdono_dati():
    """db_path assoluto verso la vecchia cartella: dopo la migrazione continua a puntare ai dati veri (nessuna perdita)."""
    old = build_old(Path.home())
    (old / "config.toml").write_text(f'[general]\ndb_path = "{old / "\x6aobhunter.db"}"\n[report]\ndir = "{old / "rep"}"\n')
    new = new_dir(old)
    migrate.migrate_app_data(old, new)
    os.environ["JOBSHUNTER_HOME"] = str(new)
    cfg = settings.load_config(new / "config.toml")
    assert settings.resolve_path(cfg["general"]["db_path"]).exists()


def test_mig_percorsi_assoluti_vengono_riscritti_o_segnalati(caplog):
    old = build_old(Path.home())
    (old / "config.toml").write_text(f'[general]\ndb_path = "{old / "\x6aobhunter.db"}"\n')
    new = new_dir(old)
    with caplog.at_level("WARNING"):
        migrate.migrate_app_data(old, new)
    txt = (new / "config.toml").read_text()
    assert str(old) not in txt or any("assolut" in r.message or "percors" in r.message for r in caplog.records)


def test_mig_chiavi_kv_e_tabelle_identiche_dopo_la_copia():
    old = build_old(Path.home())
    new = new_dir(old)
    migrate.migrate_app_data(old, new)
    a, b = sqlite3.connect(old / "\x6aobhunter.db"), sqlite3.connect(new / "\x6aobhunter.db")
    assert a.execute("select key,value from kv order by key").fetchall() == b.execute("select key,value from kv order by key").fetchall()
    assert [r[0] for r in a.execute("select name from sqlite_master order by name")] == [r[0] for r in b.execute("select name from sqlite_master order by name")]
    # nessuna chiave di stato con il vecchio nome
    assert not [k for (k,) in b.execute("select key from kv") if "\x6aobhunter" in k.lower()]
    assert not [n for (n,) in b.execute("select name from sqlite_master") if "\x6aobhunter" in n.lower()]


def test_mig_config_senza_db_dopo_migrazione_trova_il_vecchio_nome_di_database():
    """Se config.toml manca e viene ricreato dall'esempio (db_path='jobshunter.db') ma i dati stanno in \x6aobhunter.db."""
    old = build_old(Path.home())
    new = new_dir(old)
    migrate.migrate_app_data(old, new)
    (new / "config.toml").unlink()
    os.environ["JOBSHUNTER_HOME"] = str(new)
    cfg = settings.load_config(create_if_missing=True)
    db_file = settings.resolve_path(cfg["general"]["db_path"])
    assert db_file.exists(), "B47: config ricreata punta a jobshunter.db, ma i dati stanno in \x6aobhunter.db: archivio apparentemente vuoto"


def test_mig_app_import_dopo_la_migrazione_non_sovrascrive_senza_force(monkeypatch):
    from click.testing import CliRunner

    from jobshunter import cli

    from jobshunter import macapp

    old = build_old(Path.home())
    new = new_dir(old)
    monkeypatch.setattr(macapp, "APP_DIR", new)
    migrate.migrate_app_data(old, new)
    proj = Path.home() / "proj"
    proj.mkdir()
    DB(proj / "\x6aobhunter.db").conn.close()
    (proj / "config.toml").write_text('[general]\ndb_path="\x6aobhunter.db"\n')
    monkeypatch.setenv("JOBSHUNTER_HOME", str(proj))
    r = CliRunner().invoke(cli.main, ["app-import"])
    assert r.exit_code == 1 and "gia'" in r.output


@pytest.mark.xfail(reason="B48 (corretto in modo diverso, vedi phase5_status.md: app-import migra prima i dati vecchi, poi rifiuta di sovrascriverli senza --force, exit 1): ./jh app-import prima della migrazione crea la cartella nuova col solo contenuto del progetto: i dati vecchi (\x4aobHunter) non verranno MAI migrati", strict=False)
def test_mig_app_import_non_deve_impedire_la_migrazione_dei_dati_vecchi(monkeypatch):
    from click.testing import CliRunner

    from jobshunter import cli

    from jobshunter import macapp

    old = build_old(Path.home())
    monkeypatch.setattr(macapp, "APP_DIR", new_dir(old))
    proj = Path.home() / "proj"
    proj.mkdir()
    pdb = DB(proj / "jobshunter.db")
    pdb.conn.close()
    (proj / "config.toml").write_text('[general]\ndb_path="jobshunter.db"\n')
    monkeypatch.setenv("JOBSHUNTER_HOME", str(proj))
    r = CliRunner().invoke(cli.main, ["app-import"])
    assert r.exit_code == 0, r.output
    use, outcome = migrate.migrate_app_data()
    assert outcome == "copied", f"i dati vecchi non sono stati migrati ({outcome})"


# ----------------------------------------------------------------------------- variabile d'ambiente vecchia ----
def test_variabile_vecchia_home_ancora_riconosciuta(monkeypatch, tmp_path):
    monkeypatch.delenv("JOBSHUNTER_HOME", raising=False)
    monkeypatch.setenv("\x4aOBHUNTER_HOME", str(tmp_path / "miei-dati"))
    assert settings.home() == tmp_path / "miei-dati"


def test_variabile_nuova_ha_la_precedenza_sulla_vecchia(monkeypatch, tmp_path):
    monkeypatch.setenv("\x4aOBHUNTER_HOME", str(tmp_path / "vecchia"))
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "nuova"))
    assert settings.home() == tmp_path / "nuova"


# ----------------------------------------------------------------------------- LaunchAgent ----
class Launchd:
    def __init__(self):
        self.loaded: set[str] = set()
        self.calls: list[tuple] = []

    def __call__(self, *args):
        self.calls.append(args)
        rc = 0
        if args[0] == "print":
            rc = 0 if args[1].rsplit("/", 1)[1] in self.loaded else 1
        elif args[0] == "bootout":
            self.loaded.discard(args[1].rsplit("/", 1)[1])
        elif args[0] == "bootstrap":
            self.loaded.add(plistlib.loads(Path(args[2]).read_bytes())["Label"])
        return subprocess.CompletedProcess(["launchctl", *args], rc, "", "")


@pytest.fixture
def ld(monkeypatch):
    f = Launchd()
    monkeypatch.setattr(scheduler, "_launchctl", f)
    for name, fn in (("install", REAL_INSTALL), ("uninstall", REAL_UNINSTALL), ("is_loaded", REAL_IS_LOADED)):
        monkeypatch.setattr(scheduler, name, fn)  # tests/qa/conftest.py li sostituisce con finti: qui servono quelli veri (launchctl e' finto)
    monkeypatch.setattr(sys, "platform", "darwin")
    return f


def legacy_plist(extra: dict | None = None) -> Path:
    p = scheduler.legacy_plist_paths()[0]
    p.parent.mkdir(parents=True, exist_ok=True)
    d = {"Label": "local.\x6aobhunter.scan", "ProgramArguments": ["/Users/x/Applications/\x4aobHunter.app/Contents/MacOS/\x4aobHunter", "--scan-once"],
         "EnvironmentVariables": {"\x4aOBHUNTER_HOME": "/Users/x/Library/Application Support/\x4aobHunter"},
         "StartCalendarInterval": [{"Hour": 9, "Minute": 0}]}
    d.update(extra or {})
    p.write_bytes(plistlib.dumps(d))
    return p


def test_ld_plist_nuovo_ha_variabile_e_percorsi_giusti(home):
    d = scheduler.build_plist("daily", [(9, 0)], 6)
    assert d["Label"] == "local.jobshunter.scan"
    env = d["EnvironmentVariables"]
    assert env["JOBSHUNTER_HOME"] == str(settings.home()) and "\x4aOBHUNTER_HOME" not in env
    assert "JobsHunter" in d["StandardOutPath"] and "\x4aobHunter" not in d["StandardOutPath"].replace("JobsHunter", "")
    assert d["ProgramArguments"][-2:] == ["jobshunter", "scan-auto"] or d["ProgramArguments"][-1] == "--scan-once"


def test_ld_remove_legacy_toglie_plist_e_scarica_solo_il_vecchio_label(ld):
    p = legacy_plist()
    ld.loaded.add("local.\x6aobhunter.scan")
    ld.loaded.add("local.jobshunter.scan")
    assert scheduler.remove_legacy() is True
    assert not p.exists()
    assert "local.jobshunter.scan" in ld.loaded and "local.\x6aobhunter.scan" not in ld.loaded
    assert not any(c[0] == "bootout" and c[1].endswith("local.jobshunter.scan") for c in ld.calls)
    assert scheduler.remove_legacy() is False  # idempotente


def test_ld_remove_legacy_non_cancella_altri_plist_nella_cartella(ld):
    p = legacy_plist()
    other = p.parent / "com.altra.app.plist"
    other.write_bytes(plistlib.dumps({"Label": "com.altra.app"}))
    similar = p.parent / "local.\x6aobhunter.scan.backup.plist"
    similar.write_bytes(b"x")
    scheduler.remove_legacy()
    assert other.exists() and similar.exists()


def test_ld_remove_legacy_plist_vecchio_illeggibile_viene_tolto_senza_errori(ld):
    p = scheduler.legacy_plist_paths()[0]
    p.parent.mkdir(parents=True)
    p.write_bytes(b"\x00garbage")
    assert scheduler.remove_legacy() is True and not p.exists()


def test_ld_remove_legacy_se_il_plist_e_un_symlink_non_tocca_il_bersaglio(ld):
    target = Path.home() / "importante.plist"
    target.write_text("dato dell'utente")
    p = scheduler.legacy_plist_paths()[0]
    p.parent.mkdir(parents=True)
    p.symlink_to(target)
    scheduler.remove_legacy()
    assert target.exists() and target.read_text() == "dato dell'utente"


def test_ld_ensure_current_con_scansione_attiva_installa_il_nuovo_e_toglie_il_vecchio(ld, home):
    legacy_plist()
    ld.loaded.add("local.\x6aobhunter.scan")
    cfg = {"schedule": {"enabled": True, "kind": "daily", "times": "09:00"}}
    assert scheduler.ensure_current(cfg) is True
    new = plistlib.loads(scheduler.plist_path().read_bytes())
    assert new["Label"] == "local.jobshunter.scan" and new["EnvironmentVariables"]["JOBSHUNTER_HOME"] == str(settings.home())
    assert stat.S_IMODE(scheduler.plist_path().stat().st_mode) == 0o644
    assert not scheduler.legacy_plist_paths()[0].exists()
    assert ld.loaded == {"local.jobshunter.scan"}
    n = len(ld.calls)
    assert scheduler.ensure_current(cfg) is False  # secondo avvio: nulla da fare
    assert not any(c[0] in ("bootstrap",) for c in ld.calls[n:])


def test_ld_ensure_current_scansione_spenta_non_crea_nulla(ld, home):
    legacy_plist()
    assert scheduler.ensure_current({"schedule": {"enabled": False}}) is True
    assert not scheduler.plist_path().exists()
    assert scheduler.ensure_current({"schedule": {"enabled": False}}) is False


def test_ld_ensure_current_riscrive_se_cambia_la_cartella_dati(ld, home, tmp_path, monkeypatch):
    cfg = {"schedule": {"enabled": True, "kind": "every", "hours": 6}}
    scheduler.ensure_current(cfg)
    monkeypatch.setenv("JOBSHUNTER_HOME", str(tmp_path / "altra"))
    assert scheduler.ensure_current(cfg) is True
    assert plistlib.loads(scheduler.plist_path().read_bytes())["EnvironmentVariables"]["JOBSHUNTER_HOME"] == str(tmp_path / "altra")


def test_ld_ensure_current_con_launchctl_che_fallisce_non_perde_il_plist_vecchio(ld, home, monkeypatch):
    legacy_plist()
    real = ld.__call__

    def failing(*args):
        r = real(*args)
        if args[0] == "bootstrap":
            return subprocess.CompletedProcess(["launchctl", *args], 5, "", "Bootstrap failed: 5")
        return r

    monkeypatch.setattr(scheduler, "_launchctl", failing)
    with pytest.raises(RuntimeError):
        scheduler.ensure_current({"schedule": {"enabled": True, "kind": "daily", "times": "09:00"}})


def test_ld_macapp_main_non_fa_esplodere_l_avvio_se_ensure_current_fallisce():
    src = (ROOT / "jobshunter" / "macapp.py").read_text()
    assert "except Exception:\n        logging.exception(\"impossibile verificare la scansione automatica\")" in src


def test_ld_dev_mode_comando_non_dipende_da_cartella_corrente():
    """Fuori da PyInstaller il plist lancia 'python -m jobshunter' SENZA WorkingDirectory: serve il pacchetto installato."""
    d = scheduler.build_plist("daily", [(9, 0)], 6)
    if not getattr(sys, "frozen", False):
        assert "WorkingDirectory" in d or "PYTHONPATH" in d["EnvironmentVariables"], "B50: -m jobshunter da launchd senza WorkingDirectory/PYTHONPATH non trova il pacchetto se non e\' installato"


# ----------------------------------------------------------------------------- User-Agent ----
@pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\r\nX-Injected: 1", "a\x00b", "a\x7fb", "a\tb", "é", "日本", "a b", "a\u0085b", "x" * 121, "(a)", "a)", "(b"])
def test_ua_contatto_rifiutato(bad):
    with pytest.raises(ValueError):
        net.clean_contact(bad)


@pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\x00b", "a\tb", "é", "x" * 201, "​zero-width", "UA x"])
def test_ua_personalizzato_rifiutato(bad):
    with pytest.raises(ValueError):
        net.clean_user_agent(bad)


@pytest.mark.parametrize("ok", ["", "   ", "me@example.org", "https://github.com/OWNER/jobshunter", "x" * 120, "a b; c=d, e"])
def test_ua_contatto_accettato(ok):
    assert net.clean_contact(ok) == ok.strip()


@pytest.mark.parametrize("net_cfg", [
    {"contact": ""}, {"contact": "   "}, {"contact": None}, {"contact": 5}, {"contact": ["a", "b"]}, {"contact": {"x": 1}},
    {"user_agent": None}, {"user_agent": 7}, {"user_agent": ["x"]}, {"user_agent": "   "}, {}, None, "stringa", 5, [],
])
def test_ua_configurazioni_strane_non_rompono_le_richieste(net_cfg):
    ua = net.build_user_agent({"net": net_cfg})
    assert ua.isascii() and "\n" not in ua and "\r" not in ua
    assert ua.startswith("JobsHunter/") or (isinstance(net_cfg, dict) and net_cfg.get("user_agent") in (7, ["x"]))
    httpx.Headers({"User-Agent": ua})  # httpx deve accettarla


def test_ua_contatto_vuoto_non_lascia_punto_e_virgola():
    ua = net.build_user_agent({"net": {"contact": "   "}})
    assert ua == f"JobsHunter/{__version__} (+personal job search tool)" and "contact" not in ua


def test_ua_user_agent_personalizzato_non_valido_perde_anche_il_contatto_valido():
    """Un UA custom sbagliato scarta pure il contatto, anche se valido (si torna al predefinito senza contatto)."""
    ua = net.build_user_agent({"net": {"user_agent": "é", "contact": "me@example.org"}})
    assert "me@example.org" in ua, "B51: l'errore sull'UA personalizzato cancella anche il contatto valido"


def test_ua_arriva_davvero_sul_filo_e_senza_header_extra_di_browser():
    seen = []

    def h(req):
        seen.append(dict(req.headers))
        return httpx.Response(200, text="")

    settings_cfg = {"net": {"contact": "me@example.org"}}
    net.configure(settings_cfg)
    with net.client(transport=httpx.MockTransport(h)) as c:
        c.get("https://example.org/")
    hdr = seen[0]
    assert hdr["user-agent"] == f"JobsHunter/{__version__} (+personal job search tool; contact: me@example.org)"
    for k in ("sec-ch-ua", "sec-fetch-mode", "sec-fetch-site", "upgrade-insecure-requests", "referer", "origin"):
        assert k not in hdr


def test_ua_sui_redirect_resta_lo_stesso():
    seen = []

    def h(req):
        seen.append(req.headers["user-agent"])
        if req.url.path == "/a":
            return httpx.Response(302, headers={"location": "https://altro.example.org/b"})
        return httpx.Response(200)

    with net.client(transport=httpx.MockTransport(h), follow_redirects=True) as c:
        c.get("https://example.org/a")
    assert len(seen) == 2 and seen[0] == seen[1] and seen[0].startswith("JobsHunter/")


def test_ua_ogni_creazione_di_client_nel_pacchetto_passa_da_net(monkeypatch):
    """Scansione statica con AST: nessun httpx.Client/AsyncClient/get/post/request/stream, urllib, requests o http.client fuori da net.py."""
    import ast

    bad = []
    for f in (ROOT / "jobshunter").rglob("*.py"):
        if f.name == "net.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for m in mods:
                    if m.split(".")[0] in ("requests", "urllib3", "aiohttp", "pycurl") or m in ("urllib.request", "http.client") or (m == "socket" and f.name != "macapp.py"):
                        bad.append((f.name, m))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "httpx":
                if node.func.attr in ("Client", "AsyncClient", "get", "post", "put", "delete", "head", "options", "patch", "request", "stream"):
                    bad.append((f.name, f"httpx.{node.func.attr}"))
    assert not bad, bad


def test_ua_nessuna_stringa_da_browser_in_tutto_il_progetto_pubblicabile():
    pat = ("Mozilla/", "AppleWebKit", "Chrome/", "Safari/", "Gecko/")
    hits = []
    for f in list((ROOT / "jobshunter").rglob("*")) + [ROOT / "scripts" / n for n in os.listdir(ROOT / "scripts")] + [ROOT / "run_app.py", ROOT / "build_mac_app.sh"]:
        if f.is_file() and f.suffix in (".py", ".html", ".js", ".sh", ".toml"):
            t = f.read_text(encoding="utf-8", errors="ignore")
            hits += [(f.name, p) for p in pat if p in t]
    # take_screenshots.py lancia Edge: i nomi dei browser compaiono, ma non come User-Agent
    hits = [h for h in hits if h[0] != "take_screenshots.py"]
    assert not hits, hits


def test_ua_api_impostazioni_rifiuta_contatti_ostili(home):
    from jobshunter.gui.app import create_app

    c = create_app(None, 8765).test_client()
    H = {"Host": "127.0.0.1:8765"}
    for bad in ("a\r\nX: y", "(ciao)", "è", "x" * 121):
        r = c.post("/api/settings", json={"values": {"net.contact": bad}}, headers=H)
        assert r.status_code == 400, (bad, r.status_code)
    r = c.post("/api/settings", json={"values": {"net.user_agent": "Z" * 201}}, headers=H)
    assert r.status_code == 400
    assert c.post("/api/settings", json={"values": {"net.contact": "ok@example.org"}}, headers=H).status_code == 200
    assert "ok@example.org" in net.user_agent()


def test_ua_api_impostazioni_null_non_diventa_none(home):
    from jobshunter.gui.app import create_app

    c = create_app(None, 8765).test_client()
    H = {"Host": "127.0.0.1:8765"}
    c.post("/api/settings", json={"values": {"net.contact": None}}, headers=H)
    assert "None" not in net.user_agent()


def test_ua_modifica_dal_vivo_si_applica_subito_ai_nuovi_client(home):
    from jobshunter.gui.app import create_app

    c = create_app(None, 8765).test_client()
    H = {"Host": "127.0.0.1:8765"}
    c.post("/api/settings", json={"values": {"net.contact": "uno@example.org"}}, headers=H)
    assert net.client().headers["user-agent"].endswith("contact: uno@example.org)")
    c.post("/api/settings", json={"values": {"net.contact": ""}}, headers=H)
    assert "contact" not in net.client().headers["user-agent"]


def test_ua_notify_ntfy_invia_header_validi_e_ua(monkeypatch):
    from jobshunter import notify

    seen = {}

    def h(req):
        seen.update(dict(req.headers))
        return httpx.Response(200)

    real = net.client
    monkeypatch.setattr(notify.net, "client", lambda **k: real(transport=httpx.MockTransport(h), **k))
    rows = [{"category": "BLUE", "title": "Analista è", "company": "X", "score": 50, "url": "https://example.org/a"}]
    assert notify.send_ntfy({"topic": "t-1", "server": "https://ntfy.example.org"}, rows) is True
    assert seen["user-agent"].startswith("JobsHunter/")


# ----------------------------------------------------------------------------- source_wanted ----
class P:
    def __init__(self, preset="cybersecurity", countries=("it",), remote=False):
        self.preset, self.countries, self.remote = preset, list(countries), remote


def test_sw_non_cyber_non_interroga_greenhouse_e_lever():
    from jobshunter.scanner import source_wanted

    for preset in ("software_dev", "healthcare", "custom", "", None):
        assert not source_wanted("greenhouse", [P(preset)]) and not source_wanted("lever", [P(preset)]), preset
    assert source_wanted("greenhouse", [P("cybersecurity")]) and source_wanted("lever", [P("cybersecurity")])
    assert source_wanted("greenhouse", [P("software_dev"), P("cybersecurity")])
    assert not source_wanted("greenhouse", [])


def test_sw_altre_fonti_invariate():
    from jobshunter.scanner import source_wanted

    assert source_wanted("adzuna", [P("software_dev")]) and source_wanted("jooble", [])
    assert not source_wanted("arbeitnow", [P("software_dev", ("it",))]) and source_wanted("arbeitnow", [P("software_dev", ("de",))])
    assert not source_wanted("remoteok", [P(remote=False)]) and source_wanted("remotive", [P(remote=True)])


def _set_preset(db, preset):
    from jobshunter.profiles import ProfileStore

    store = ProfileStore(db)
    for pr in store.list():
        d = pr.to_dict()
        d["preset"] = preset
        store.update(pr.id, d)
    return store


def test_sw_config_con_greenhouse_esplicito_e_profilo_non_cyber_non_fa_richieste(cfg, db):
    """Una config esistente con [sources.greenhouse] enabled=true e solo profili non cyber: nessuna richiesta, nessun errore."""
    from jobshunter.scanner import run_scan
    from jobshunter.sources import REGISTRY
    from jobshunter.sources.base import Source

    calls = []

    class Spy(Source):
        name = "greenhouse"

        def fetch_queries(self, queries):
            calls.append("greenhouse")
            return []

        def fetch(self):
            calls.append("greenhouse")
            return []

    old = REGISTRY.get("greenhouse")
    REGISTRY["greenhouse"] = Spy
    try:
        cfg["sources"] = {"greenhouse": {"enabled": True, "companies": ["x"]}}
        _set_preset(db, "software_dev")
        events = []
        res = run_scan(cfg, db, on_event=lambda k, d: events.append((k, d)))
        assert not calls, "greenhouse non doveva essere interrogato per un profilo non cyber"
        assert not [e for e in events if e[0] in ("queued", "start")]
        assert res.errors == []
        _set_preset(db, "cybersecurity")
        run_scan(cfg, db)
        assert calls, "con un profilo cyber greenhouse esplicito deve essere interrogato"
    finally:
        if old is not None:
            REGISTRY["greenhouse"] = old
        else:
            REGISTRY.pop("greenhouse", None)


def test_sw_stima_richieste_non_conta_greenhouse_per_profili_non_cyber(cfg, db):
    from jobshunter import profiles as prof

    cfg["sources"]["greenhouse"] = {"enabled": True, "companies": ["a", "b"]}
    store = _set_preset(db, "software_dev")
    est = prof.estimate_requests(store.active(), cfg)
    assert not est.get("greenhouse"), f"la stima conta greenhouse per un profilo non cyber: {est}"
