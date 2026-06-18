# -*- coding: utf-8 -*-
"""
Bootstrap a persistent SIVICAP session.

Run this script ONCE (or whenever the session expires — typically every few
weeks). It opens a real, visible Chrome window with the dedicated profile
directory the scraper uses. You log in manually (handling the reCAPTCHA like
a normal user), close the window, and from then on the headless scraper
reuses the saved cookies without re-doing the reCAPTCHA.

Usage:
    python tools/setup_sivicap_session.py

What to do when the window opens:
    1. The login page appears with credentials already filled.
    2. Solve the reCAPTCHA checkbox manually.
    3. Click "Iniciar sesión".
    4. Wait until you see the reports/dashboard page (no more login form).
    5. Press Enter in this terminal — the script saves the session and exits.

Why this works: SIVICAP rejects undetected-chromedriver because Google's
reCAPTCHA scores headless sessions as bot-like. A real human login produces
a high-score session cookie valid for days. The headless scraper then just
re-uses that cookie via the persistent profile.
"""

import sys
import time
from pathlib import Path

# Make scrapers importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.irca_scraper import (
    PROFILE_DIR, SIVICAP_LOGIN, SIVICAP_USER, SIVICAP_PASS, _is_logged_in, _make_driver
)


def main() -> None:
    print(f'Perfil persistente: {PROFILE_DIR}')
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        # headless=False so the user can interact with the reCAPTCHA.
        driver = _make_driver(tmpdir, headless=False, use_profile=True)
        try:
            # Quick check: maybe we still have a valid session and don't need to log in
            if _is_logged_in(driver):
                print('\n✓ Ya hay una sesión válida guardada. Nada que hacer.')
                print(f'  ({driver.current_url})')
                return

            driver.get(SIVICAP_LOGIN)
            time.sleep(2)

            # Pre-fill credentials so the user only has to do the reCAPTCHA + click submit
            try:
                from selenium.webdriver.common.by import By
                driver.find_element(By.ID, 'Email').send_keys(SIVICAP_USER)
                driver.find_element(By.ID, 'Password').send_keys(SIVICAP_PASS)
            except Exception:
                pass

            print()
            print('=' * 70)
            print('  En la ventana de Chrome:')
            print(f'    1. Las credenciales ya están llenadas')
            print(f'       ({SIVICAP_USER} / {SIVICAP_PASS})')
            print('    2. Resuelve el reCAPTCHA (clic en "No soy un robot")')
            print('    3. Haz clic en "Iniciar sesión"')
            print('    4. Cuando veas la página principal del sistema,')
            print('       vuelve a esta terminal y presiona ENTER.')
            print('=' * 70)
            input('\nPresiona ENTER cuando hayas hecho login... ')

            if _is_logged_in(driver):
                print('\n✓ Sesión guardada correctamente.')
                print(f'  URL actual: {driver.current_url}')
                print(f'  Perfil:     {PROFILE_DIR}')
                print('\nDe ahora en adelante el scraper headless usará esta sesión')
                print('automáticamente. Re-ejecute este script si SIVICAP vuelve a')
                print('pedir login (típicamente cada pocas semanas).')
            else:
                print('\n✗ Login no detectado.')
                print(f'  URL actual: {driver.current_url}')
                print('  La sesión NO se guardó. Intenta de nuevo.')
        finally:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == '__main__':
    main()
