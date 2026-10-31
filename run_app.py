"""Punto d'ingresso per PyInstaller (JobsHunter.app, JobsHunter.exe, AppImage)."""
import sys

if __name__ == "__main__":
    if "--smoke" in sys.argv:  # prova del pacchetto: server locale + controlli, niente finestra, niente rete
        from jobshunter.smoke import main as smoke_main

        sys.exit(smoke_main(sys.argv))
    elif "--scan-once" in sys.argv:  # scansione pianificata (launchd, Utilita' di pianificazione, systemd, cron): niente finestra
        from jobshunter.autoscan import main_scan_once

        main_scan_once()
    else:
        from jobshunter.macapp import main

        main()
