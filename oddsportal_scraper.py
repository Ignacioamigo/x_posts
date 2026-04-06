"""
Scraper de OddsPortal con Selenium headless para obtener partidos
y cuotas de Bet365 directamente de la web.
"""
import logging
import time
from datetime import datetime, date
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

URLS_DARTS = [
    "https://www.oddsportal.com/darts/world/premier-league/",
    "https://www.oddsportal.com/darts/world/modus-super-series/",
    "https://www.oddsportal.com/darts/europe/european-tour-4/",
]

URLS_TABLE_TENNIS = [
    "https://www.oddsportal.com/table-tennis/",
]


def _build_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=es-ES")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(30)
    return driver


def _dismiss_cookie_banner(driver: webdriver.Chrome):
    """Cierra el banner de cookies si aparece."""
    try:
        btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH,
                "//*[contains(@id,'accept') or contains(@class,'accept') "
                "or contains(text(),'Accept') or contains(text(),'Aceptar')]"
            ))
        )
        btn.click()
        time.sleep(0.5)
    except Exception:
        pass


def _parse_time(time_str: str) -> str | None:
    """Convierte la hora de OddsPortal (HH:MM) a string. Devuelve None si no es válida."""
    try:
        datetime.strptime(time_str.strip(), "%H:%M")
        return time_str.strip()
    except ValueError:
        return None


def scrape_oddsportal(url: str, sport: str) -> list[dict]:
    """
    Abre la URL con Selenium headless y extrae partidos con cuotas Bet365.
    Devuelve lista de dicts: {player1, player2, sport, time, tournament, odd_p1, odd_p2}
    """
    driver = None
    matches = []

    try:
        logger.info("Abriendo OddsPortal: %s", url)
        driver = _build_driver()
        driver.get(url)

        _dismiss_cookie_banner(driver)

        # Esperar a que carguen las filas de partidos
        logger.info("Esperando carga de partidos...")
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[class*='eventRow']"))
            )
        except Exception:
            logger.warning("Timeout esperando eventRow, intentando parsear lo que hay...")

        time.sleep(3)  # margen extra para JS asíncrono

        # Extraer HTML para debug
        page_source = driver.page_source
        logger.debug("Tamaño página: %d chars", len(page_source))

        # ── Buscar filas de partidos ──────────────────────────────────────────
        row_selectors = [
            "[class*='eventRow']",
            "[class*='event-row']",
            "div[class*='border-black-borders']",
            "div[class*='group flex']",
        ]

        rows = []
        for sel in row_selectors:
            rows = driver.find_elements(By.CSS_SELECTOR, sel)
            if rows:
                logger.info("Selector '%s' encontró %d filas", sel, len(rows))
                break

        if not rows:
            logger.warning("No se encontraron filas de partidos en %s", url)
            return []

        today = date.today()
        now   = datetime.now()
        tournament = _extract_tournament_from_url(url)

        for row in rows:
            try:
                match = _parse_row(row, sport, today, now, tournament)
                if match:
                    matches.append(match)
            except Exception as e:
                logger.debug("Error parseando fila: %s", e)

        logger.info("Partidos extraídos de OddsPortal: %d", len(matches))

    except Exception as e:
        logger.error("Error en scrape_oddsportal(%s): %s", url, e)
    finally:
        if driver:
            driver.quit()

    return matches


def _extract_tournament_from_url(url: str) -> str:
    """Extrae nombre de torneo de la URL."""
    parts = [p for p in url.rstrip("/").split("/") if p and "oddsportal" not in p and "http" not in p]
    if parts:
        return parts[-1].replace("-", " ").title()
    return ""


def _parse_row(row, sport: str, today: date, now: datetime, tournament: str) -> dict | None:
    """Extrae datos de una fila de partido."""

    row_text = row.text.strip()
    if not row_text or len(row_text) < 5:
        return None

    # ── Hora ────────────────────────────────────────────────────────────────
    hora = None
    time_selectors = [
        "[class*='table-time']", "[class*='time']",
        "p[class*='date']", "div[class*='date']",
    ]
    for sel in time_selectors:
        elems = row.find_elements(By.CSS_SELECTOR, sel)
        for el in elems:
            t = _parse_time(el.text)
            if t:
                hora = t
                break
        if hora:
            break

    # Si no encontramos hora en atributo, buscar patrón HH:MM en el texto
    if not hora:
        import re
        m = re.search(r'\b(\d{1,2}:\d{2})\b', row_text)
        if m:
            hora = _parse_time(m.group(1))

    # ── Jugadores ────────────────────────────────────────────────────────────
    player_selectors = [
        "[class*='participant']", "[class*='team-name']",
        "p[class*='name']", "a[class*='participant']",
    ]
    players = []
    for sel in player_selectors:
        elems = row.find_elements(By.CSS_SELECTOR, sel)
        names = [e.text.strip() for e in elems if e.text.strip()]
        if len(names) >= 2:
            players = names[:2]
            break

    if len(players) < 2:
        return None

    player1, player2 = players[0], players[1]
    placeholders = {"tba", "tbd", "?", "-", ""}
    if player1.lower() in placeholders or player2.lower() in placeholders:
        return None

    # ── Cuotas Bet365 ────────────────────────────────────────────────────────
    odd_p1, odd_p2 = None, None
    try:
        odds_elems = row.find_elements(By.CSS_SELECTOR,
            "[class*='odds-link'], [class*='odd'], a[class*='flex'][href*='bet365']"
        )
        odds_vals = []
        for el in odds_elems:
            try:
                val = float(el.text.strip())
                if 1.01 <= val <= 50:
                    odds_vals.append(val)
            except ValueError:
                pass
        if len(odds_vals) >= 2:
            odd_p1, odd_p2 = odds_vals[0], odds_vals[1]
    except Exception:
        pass

    # ── Filtrar solo partidos futuros de hoy ─────────────────────────────────
    if hora:
        try:
            match_dt = datetime.strptime(f"{today} {hora}", "%Y-%m-%d %H:%M")
            if match_dt <= now:
                return None  # ya empezó
        except ValueError:
            pass  # hora inválida → incluir por precaución

    return {
        "player1":    player1,
        "player2":    player2,
        "sport":      sport,
        "time":       hora or "?",
        "tournament": tournament,
        "odd_p1":     odd_p1,
        "odd_p2":     odd_p2,
    }


def scrape_all_darts() -> list[dict]:
    """Scrape todas las URLs de dardos y devuelve lista unificada sin duplicados."""
    seen = set()
    all_matches = []
    for url in URLS_DARTS:
        for m in scrape_oddsportal(url, "darts"):
            key = (m["player1"].lower(), m["player2"].lower())
            if key not in seen:
                seen.add(key)
                all_matches.append(m)
    return all_matches


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    for url in URLS_DARTS:
        print(f"\n{'='*60}")
        print(f"URL: {url}")
        print('='*60)
        results = scrape_oddsportal(url, "darts")
        if results:
            print(f"✅ {len(results)} partidos encontrados:\n")
            for m in results:
                odd_str = f"Bet365: {m['odd_p1']} / {m['odd_p2']}" if m['odd_p1'] else "Sin cuotas Bet365"
                print(f"  {m['time']} | {m['player1']} vs {m['player2']} | {m['tournament']} | {odd_str}")
        else:
            print("❌ Sin partidos encontrados")
