"""
Scraper de cuotasahora.com con Selenium headless para obtener partidos
y cuotas de Bet365 directamente de la web.
Usa JSON-LD (schema.org) para extraer nombres y horas, y Selenium para las cuotas.
"""
import json
import logging
import re
import time
from datetime import datetime, date, timezone
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logger = logging.getLogger(__name__)

BASE = "https://www.cuotasahora.com"

URLS_DARTS = [
    f"{BASE}/darts/world/premier-league/",
    f"{BASE}/darts/world/modus-super-series/",
]

URLS_HANDBALL = [
    f"{BASE}/handball/germany/bundesliga/",
    f"{BASE}/handball/spain/liga-asobal/",
    f"{BASE}/handball/france/starligue/",
    f"{BASE}/handball/denmark/herre-handbold-ligaen/",
    f"{BASE}/handball/norway/rema-1000-ligaen/",
    f"{BASE}/handball/poland/superliga/",
    f"{BASE}/handball/croatia/premijer-liga/",
]


def _build_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-setuid-sandbox")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--disable-default-apps")
    opts.add_argument("--disable-sync")
    opts.add_argument("--no-first-run")
    opts.add_argument("--remote-debugging-port=0")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=es-ES")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    import shutil
    for binary in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(binary)
        if path:
            opts.binary_location = path
            logger.info("Chrome binario: %s", path)
            break

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(30)
    return driver


def _dismiss_cookie_banner(driver: webdriver.Chrome):
    """Cierra el banner de cookies y el modal de verificación de edad."""
    xpaths = [
        "//*[contains(text(),'MAYOR DE 18')]",
        "//*[contains(text(),'Mayor de 18')]",
        "//*[contains(@id,'accept') or contains(@class,'accept')]",
        "//*[contains(text(),'Accept') or contains(text(),'Aceptar')]",
    ]
    for xpath in xpaths:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            btn.click()
            time.sleep(0.5)
        except Exception:
            pass


def _extract_tournament_from_url(url: str) -> str:
    parts = [p for p in url.rstrip("/").split("/") if p and "cuotasahora" not in p and "http" not in p]
    if parts:
        return parts[-1].replace("-", " ").title()
    return ""


def _parse_jsonld_matches(page_source: str, sport: str, tournament: str) -> list[dict]:
    """
    Extrae partidos del JSON-LD (schema.org) incrustado en el HTML.
    Devuelve lista de dicts con player1, player2, time — sin cuotas aún.
    """
    matches = []
    now = datetime.now()
    today = date.today()

    pattern = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.DOTALL)
    for m in pattern.finditer(page_source):
        try:
            data = json.loads(m.group(1))
            items = data if isinstance(data, list) else [data]
            for item in items:
                types = item.get("@type", [])
                if isinstance(types, str):
                    types = [types]
                if not any(t in types for t in ("SportsEvent", "Event")):
                    continue

                name = item.get("name", "")
                start_date = item.get("startDate", "")
                if not name or not start_date or " - " not in name:
                    continue

                p1, p2 = [x.strip() for x in name.split(" - ", 1)]
                placeholders = {"tba", "tbd", "?", "-", ""}
                if p1.lower() in placeholders or p2.lower() in placeholders:
                    continue

                # Parsear hora
                try:
                    dt = datetime.fromisoformat(start_date)
                    # Convertir a hora local si tiene timezone
                    if dt.tzinfo is not None:
                        dt = dt.astimezone().replace(tzinfo=None)
                    if dt.date() != today:
                        continue
                    if dt <= now:
                        continue
                    hora = dt.strftime("%H:%M")
                except Exception:
                    continue

                matches.append({
                    "player1":    p1,
                    "player2":    p2,
                    "sport":      sport,
                    "time":       hora,
                    "tournament": tournament,
                    "odd_p1":     None,
                    "odd_p2":     None,
                    "match_url":  item.get("url", ""),
                })
        except Exception as e:
            logger.debug("Error parseando JSON-LD: %s", e)

    return matches


def _parse_odds_from_body_text(body_text: str) -> dict:
    """
    Parsea el texto visible del body para extraer cuotas por partido.
    Estructura en cuotasahora.com:
        HH:MM
        Equipo1
        –
        Equipo2
        odd1
        oddX   (solo si 3 columnas: balonmano)
        odd2
    Devuelve dict: { "equipo1 vs equipo2": (odd_p1, odd_p2) }
    """
    result = {}
    lines = [l.strip() for l in body_text.split("\n") if l.strip()]

    i = 0
    while i < len(lines):
        # Detectar línea de hora HH:MM
        if not re.match(r'^\d{1,2}:\d{2}$', lines[i]):
            i += 1
            continue

        # Estructura esperada: time, team1, –, team2, odds...
        if i + 3 >= len(lines):
            i += 1
            continue

        team1 = lines[i + 1]
        sep   = lines[i + 2]
        team2 = lines[i + 3]

        if sep != "–" or not team1 or not team2:
            i += 1
            continue

        # Leer cuotas a partir de i+4
        odds = []
        j = i + 4
        while j < len(lines) and len(odds) < 3:
            try:
                val = float(lines[j])
                if 1.01 <= val <= 50:
                    odds.append(val)
                    j += 1
                else:
                    break
            except ValueError:
                break

        if len(odds) >= 2:
            odd_p1 = odds[0]
            odd_p2 = odds[-1]  # último: visitante (tanto en 2 como en 3 columnas)
            key = f"{team1.lower()}||{team2.lower()}"
            result[key] = (odd_p1, odd_p2)
            logger.debug("Cuotas parseadas: %s @ %.2f vs %s @ %.2f", team1, odd_p1, team2, odd_p2)
            i = j
        else:
            i += 1

    return result


def _extract_odds_from_page(driver: webdriver.Chrome, matches: list[dict]) -> list[dict]:
    """
    Extrae cuotas del texto visible del body y las asigna a los partidos ya identificados.
    """
    if not matches:
        return matches

    try:
        time.sleep(3)
        body_text = driver.find_element(By.TAG_NAME, "body").text
        odds_map = _parse_odds_from_body_text(body_text)

        for match in matches:
            p1 = match["player1"].lower()
            p2 = match["player2"].lower()
            key = f"{p1}||{p2}"

            if key in odds_map:
                match["odd_p1"], match["odd_p2"] = odds_map[key]
            else:
                # Búsqueda parcial flexible: cualquier palabra clave del nombre
                p1_words = [w for w in p1.split() if len(w) >= 4]
                p2_words = [w for w in p2.split() if len(w) >= 4]
                for k, (o1, o2) in odds_map.items():
                    t1, t2 = k.split("||")
                    match1 = any(w in t1 for w in p1_words) if p1_words else p1[:5] in t1
                    match2 = any(w in t2 for w in p2_words) if p2_words else p2[:5] in t2
                    if match1 and match2:
                        match["odd_p1"], match["odd_p2"] = o1, o2
                        logger.debug("Match parcial: %s → %s (%.2f/%.2f)", p1, k, o1, o2)
                        break

    except Exception as e:
        logger.error("Error extrayendo cuotas: %s", e)

    return matches



def _scrape_urls(urls: list[str], sport: str) -> list[dict]:
    """Scrape múltiples URLs reutilizando un único driver para evitar bloqueos."""
    seen = set()
    all_matches = []
    driver = None

    try:
        driver = _build_driver()
        for url in urls:
            try:
                logger.info("Abriendo cuotasahora: %s", url)
                driver.get(url)
                time.sleep(4)  # esperar carga JS

                current_url = driver.current_url
                sport_path = f"/{sport}/"
                if sport_path not in current_url:
                    logger.warning("Redirección inesperada: %s → %s", url, current_url)
                    continue

                _dismiss_cookie_banner(driver)

                page_source = driver.page_source
                tournament = _extract_tournament_from_url(url)
                matches = _parse_jsonld_matches(page_source, sport, tournament)
                logger.info("JSON-LD: %d partidos en %s", len(matches), tournament)

                if matches:
                    matches = _extract_odds_from_page(driver, matches)
                    for m in matches:
                        key = (m["player1"].lower(), m["player2"].lower())
                        if key not in seen:
                            seen.add(key)
                            all_matches.append(m)

                time.sleep(2)  # pausa entre URLs

            except Exception as e:
                logger.error("Error scrapeando %s: %s", url, e)

    except Exception as e:
        logger.error("Error creando driver: %s", e)
    finally:
        if driver:
            driver.quit()

    return all_matches


def scrape_all_darts() -> list[dict]:
    return _scrape_urls(URLS_DARTS, "darts")


def scrape_all_handball() -> list[dict]:
    return _scrape_urls(URLS_HANDBALL, "handball")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    print("\n=== DARDOS ===")
    for m in scrape_all_darts():
        cuota = f"{m['odd_p1']} / {m['odd_p2']}" if m["odd_p1"] else "sin cuota"
        print(f"  {m['time']} | {m['tournament']:25} | {m['player1']} vs {m['player2']} | {cuota}")

    print("\n=== BALONMANO ===")
    for m in scrape_all_handball():
        cuota = f"{m['odd_p1']} / {m['odd_p2']}" if m["odd_p1"] else "sin cuota"
        print(f"  {m['time']} | {m['tournament']:25} | {m['player1']} vs {m['player2']} | {cuota}")
