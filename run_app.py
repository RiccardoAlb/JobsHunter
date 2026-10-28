"""Punto d'ingresso per PyInstaller (JobsHunter.app)."""
import sys

if __name__ == "__main__":
    if "--scan-once" in sys.argv:  # scansione pianificata da launchd: niente finestra
        from jobshunter.autoscan import main_scan_once

        main_scan_once()
    else:
        from jobshunter.macapp import main

        main()
