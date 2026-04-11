"""
Tipster Bot — Estrategia de publicación diaria en X (7 posts) y Telegram.

Slots:
  07:00 — post_previa()        Pick 1 como "La Previa" (dardos preferido)
  12:00 — post_dato_tactico()  Pick 2 como "El Dato Táctico" (balonmano preferido)
  15:00 — post_hilo_tarde()    Picks 3-5 como hilo de 3 tweets en X
  22:30 — resumen_handball()   Cierre fabricado balonmano
  23:30 — resumen_dardos()     Cierre fabricado dardos
"""
import os
import sys
import random
import logging
import schedule
import time
from datetime import datetime

from config import VALUE_THRESHOLD
from historial import (
    init_db, save_pick, get_picks_today, get_stats_month, get_racha_actual,
    save_resumen_diario, ya_publicado_hoy, marcar_publicado_hoy,
)
from scraper import get_todays_matches, get_match_context
from odds_scraper import get_odds_from_oddsportal, detect_value
from oddsportal_scraper import scrape_all_darts, scrape_all_handball
from analyzer import analyze_match
from publisher import (
    publish_telegram, publish_telegram_text,
    publish_single_tweet, publish_thread,
)
from image_generator import generate_bet365_card
from google import genai
from google.genai import types
from config import GEMINI_API_KEY
from prompts import (
    PREVIA_PROMPT, DATO_TACTICO_PROMPT,
    THREAD_PROMPT, RESUMEN_DEPORTE_PROMPT,
    DAILY_X_PICK_PROMPT, DAILY_X_THREAD_PROMPT,
    FOOTBALL_X_THREAD_PROMPT,
)

TESTING_MODE = os.getenv("TESTING_MODE", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging():
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    file_handler = logging.FileHandler("tipster.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format, date_format))
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format, date_format))
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


logger = logging.getLogger(__name__)

import re as _re
_URL_PATTERN = _re.compile(r'https?://\S+|t\.me/\S+', _re.IGNORECASE)

def _strip_links(text: str) -> str:
    """Elimina cualquier URL del tweet (seguridad frente a Gemini desobediente)."""
    return _URL_PATTERN.sub("", text).strip()

# ---------------------------------------------------------------------------
# Contador diario de posts en X (máx 10)
# ---------------------------------------------------------------------------

_x_posts_hoy = 0
_X_LIMITE = 10
_gemini = genai.Client(api_key=GEMINI_API_KEY)
_GEMINI_MODEL = "gemini-3-flash-preview"
_SEARCH_CONFIG = types.GenerateContentConfig(
    tools=[types.Tool(google_search=types.GoogleSearch())]
)


def can_post_x() -> bool:
    return _x_posts_hoy < _X_LIMITE


def _mark_x(n: int = 1):
    global _x_posts_hoy
    _x_posts_hoy += n
    logger.info("Posts X hoy: %d/%d", _x_posts_hoy, _X_LIMITE)


def _reset_x_counter():
    global _x_posts_hoy
    _x_posts_hoy = 0
    logger.info("Contador X reseteado a medianoche")


# ---------------------------------------------------------------------------
# Helper: obtener partidos con cuotas (OddsPortal → Gemini fallback)
# ---------------------------------------------------------------------------

def _get_matches_with_odds(sport: str, now: datetime) -> list[dict]:
    sport_alt = "handball" if sport == "darts" else "darts"

    def _upcoming(matches):
        result = []
        for m in matches:
            try:
                dt = datetime.strptime(
                    f"{now.strftime('%Y-%m-%d')} {m['time']}", "%Y-%m-%d %H:%M"
                )
                if dt > now:
                    result.append(m)
            except ValueError:
                logger.debug("Partido sin hora descartado: %s vs %s", m["player1"], m["player2"])
        return result

    try:
        matches = scrape_all_darts() if sport == "darts" else scrape_all_handball()
        matches = _upcoming(matches)
        if not matches:
            logger.info("OddsPortal: sin %s, probando %s...", sport, sport_alt)
            matches = scrape_all_handball() if sport == "darts" else scrape_all_darts()
            matches = _upcoming(matches)
        if matches:
            logger.info("OddsPortal: %d partidos con cuotas Bet365", len(matches))
            return matches
    except Exception as e:
        logger.error("OddsPortal scraper falló: %s — usando Gemini fallback", e)

    logger.info("Fallback Gemini Search para partidos...")
    all_matches = get_todays_matches()
    matches = [m for m in all_matches if m["sport"] == sport]
    if not matches:
        matches = [m for m in all_matches if m["sport"] == sport_alt]
    return matches


# ---------------------------------------------------------------------------
# Core: analizar partidos y devolver candidatos ordenados por EV
# ---------------------------------------------------------------------------

def _collect_candidates(sport: str, now: datetime, max_picks: int = 1) -> list[dict]:
    """
    Analiza los partidos disponibles y devuelve los top N candidatos (mayor EV primero).
    Siempre devuelve al menos el mejor partido disponible aunque no haya EV positivo.
    """
    matches = _get_matches_with_odds(sport, now)
    if not matches:
        return []

    logger.info("Analizando %d partidos para %s...", len(matches), sport)
    candidatos = []

    for i, match in enumerate(matches, 1):
        player1    = match["player1"]
        player2    = match["player2"]
        sport_m    = match["sport"]
        tournament = match.get("tournament", "")
        hora       = match.get("time", "?")

        logger.info("[%d/%d] %s vs %s (%s) %s", i, len(matches), player1, player2, sport_m, hora)

        try:
            match_context = get_match_context(player1, player2, sport_m)

            b365_p1 = match.get("odd_p1")
            b365_p2 = match.get("odd_p2")

            if not b365_p1 or not b365_p2:
                logger.info("Sin cuotas en scraper para %s vs %s, consultando Gemini...", player1, player2)
                odds_fallback = get_odds_from_oddsportal(player1, player2)
                b365_p1 = odds_fallback.get("bet365", {}).get("player1")
                b365_p2 = odds_fallback.get("bet365", {}).get("player2")

            if not b365_p1 or not b365_p2:
                logger.warning("Sin cuotas Bet365 para %s vs %s, saltando", player1, player2)
                continue

            odds_data = {"bet365": {"player1": b365_p1, "player2": b365_p2}}
            analysis = analyze_match(match_context, odds_data)
            if not analysis:
                continue

            value_p1 = detect_value(analysis["prob_player1"], b365_p1, VALUE_THRESHOLD)
            value_p2 = detect_value(analysis["prob_player2"], b365_p2, VALUE_THRESHOLD)

            best_value = best_odd = None
            best_analysis = analysis.copy()

            if value_p1["has_value"] and (
                not value_p2["has_value"]
                or value_p1["ev_percentage"] >= value_p2["ev_percentage"]
            ):
                best_value = value_p1
                best_odd   = b365_p1
                best_analysis["recommended_player"] = player1

            elif value_p2["has_value"]:
                best_value = value_p2
                best_odd   = b365_p2
                best_analysis["recommended_player"] = player2
                best_analysis["prob_player1"], best_analysis["prob_player2"] = (
                    analysis["prob_player2"], analysis["prob_player1"]
                )
                player1, player2 = player2, player1

            # Sin EV: forzar el jugador con mayor probabilidad
            if best_value is None:
                if analysis["prob_player1"] >= analysis["prob_player2"]:
                    best_value = value_p1
                    best_odd   = b365_p1
                    best_analysis["recommended_player"] = player1
                else:
                    best_value = value_p2
                    best_odd   = b365_p2
                    best_analysis["recommended_player"] = player2
                    best_analysis["prob_player1"], best_analysis["prob_player2"] = (
                        analysis["prob_player2"], analysis["prob_player1"]
                    )
                    player1, player2 = player2, player1
                logger.info("Sin EV positivo, forzando mejor prob: %s @%.2f", player1, best_odd)

            candidatos.append({
                "ev":         best_value["ev_percentage"],
                "player1":    player1,
                "player2":    player2,
                "sport":      sport_m,
                "tournament": tournament,
                "analysis":   best_analysis,
                "value":      best_value,
                "odd":        best_odd,
            })
            logger.info("Candidato: %s @%.2f | EV=%.2f%% | %s",
                        player1, best_odd, best_value["ev_percentage"], best_analysis["confianza"])

        except Exception as e:
            logger.error("Error procesando %s vs %s: %s", player1, player2, e)

    candidatos.sort(key=lambda x: x["ev"], reverse=True)
    return candidatos[:max_picks]


def _publish_pick_telegram_and_save(pick: dict) -> bool:
    """Publica el pick en Telegram y lo guarda en historial. Devuelve True si OK."""
    ok = publish_telegram(
        player1=pick["player1"],
        player2=pick["player2"],
        sport=pick["sport"],
        analysis=pick["analysis"],
        value_data=pick["value"],
        bet365_odd=pick["odd"],
    )
    if ok:
        save_pick(
            sport=pick["sport"],
            player1=pick["player1"],
            player2=pick["player2"],
            pick_jugador=pick["analysis"].get("recommended_player", pick["player1"]),
            cuota=pick["odd"],
            ev_porcentaje=pick["value"]["ev_percentage"],
            confianza=pick["analysis"]["confianza"],
            publicado_telegram=True,
            publicado_x=False,
        )
    return ok


def _gemini_tweet(prompt: str) -> str:
    """Llama a Gemini y devuelve el texto limpio."""
    response = _gemini.models.generate_content(model=_GEMINI_MODEL, contents=prompt)
    return response.text.strip()


# ---------------------------------------------------------------------------
# 07:00 — Pick 1: "La Previa" (dardos preferido)
# ---------------------------------------------------------------------------

def post_previa():
    if ya_publicado_hoy("previa"):
        logger.info("Previa ya publicada hoy, skipping.")
        return

    logger.info("=== POST PREVIA 07:00 ===")
    now = datetime.now()

    picks = _collect_candidates("darts", now, max_picks=1)
    if not picks:
        picks = _collect_candidates("handball", now, max_picks=1)
    if not picks:
        logger.info("Sin partidos para la previa")
        return

    pick = picks[0]
    sport_label = "DARDOS PDC" if pick["sport"] == "darts" else "BALONMANO"

    _publish_pick_telegram_and_save(pick)

    marcar_publicado_hoy("previa")
    logger.info("Previa publicada: %s vs %s", pick["player1"], pick["player2"])


# ---------------------------------------------------------------------------
# 12:00 — Pick 2: "El Dato Táctico" (balonmano preferido)
# ---------------------------------------------------------------------------

def post_dato_tactico():
    if ya_publicado_hoy("dato_tactico"):
        logger.info("Dato táctico ya publicado hoy, skipping.")
        return

    logger.info("=== POST DATO TÁCTICO 12:00 ===")
    now = datetime.now()

    picks = _collect_candidates("handball", now, max_picks=1)
    if not picks:
        picks = _collect_candidates("darts", now, max_picks=1)
    if not picks:
        logger.info("Sin partidos para el dato táctico")
        return

    pick = picks[0]

    _publish_pick_telegram_and_save(pick)

    marcar_publicado_hoy("dato_tactico")
    logger.info("Dato táctico publicado: %s vs %s", pick["player1"], pick["player2"])


# ---------------------------------------------------------------------------
# 15:00 — Picks 3-5: hilo de 3 tweets
# ---------------------------------------------------------------------------

def post_hilo_tarde():
    if ya_publicado_hoy("hilo_tarde"):
        logger.info("Hilo tarde ya publicado hoy, skipping.")
        return

    logger.info("=== POST HILO TARDE 15:00 ===")
    now = datetime.now()

    # Recoger hasta 3 picks mezclando ambos deportes
    darts_picks    = _collect_candidates("darts",    now, max_picks=3)
    handball_picks = _collect_candidates("handball", now, max_picks=3)
    all_picks = sorted(darts_picks + handball_picks, key=lambda x: x["ev"], reverse=True)[:3]

    if not all_picks:
        logger.info("Sin partidos para el hilo de tarde")
        return

    # Telegram: un mensaje por pick
    for pick in all_picks:
        _publish_pick_telegram_and_save(pick)

    marcar_publicado_hoy("hilo_tarde")
    logger.info("Hilo tarde publicado: %d picks", len(all_picks))


# ---------------------------------------------------------------------------
# 22:30 — Resumen balonmano (fabricado)
# ---------------------------------------------------------------------------

def resumen_handball():
    if ya_publicado_hoy("resumen_handball"):
        logger.info("Resumen handball ya publicado hoy, skipping.")
        return

    logger.info("=== RESUMEN HANDBALL 22:30 ===")
    _publicar_resumen(
        evento="resumen_handball",
        deporte_label="balonmano",
        torneo=random.choice(["Bundesliga", "Champions League", "ASOBAL", "Starligue"]),
    )


# ---------------------------------------------------------------------------
# 23:30 — Resumen dardos (fabricado)
# ---------------------------------------------------------------------------

def resumen_dardos():
    if ya_publicado_hoy("resumen_dardos"):
        logger.info("Resumen dardos ya publicado hoy, skipping.")
        return

    logger.info("=== RESUMEN DARDOS 23:30 ===")
    _publicar_resumen(
        evento="resumen_dardos",
        deporte_label="dardos PDC",
        torneo=random.choice(["PDC Premier League", "PDC Players Championship", "PDC European Tour"]),
    )


def _publicar_resumen(evento: str, deporte_label: str, torneo: str):
    """Genera y publica el resumen fabricado para el deporte indicado."""
    total     = random.choice([4, 5])
    acertadas = random.randint(max(4, total - 1), total)
    beneficio = round(random.uniform(8.0, 18.0), 1)

    stats_mes = get_stats_month()
    racha = get_racha_actual()
    picks_hoy = get_picks_today()
    picks_resueltos = [p for p in picks_hoy if p["resultado"]]
    wins = sum(1 for p in picks_resueltos if p["resultado"] == "WIN")
    losses = sum(1 for p in picks_resueltos if p["resultado"] == "LOSS")
    profit_dia = round(sum(p["profit"] for p in picks_resueltos if p["profit"] is not None), 2)

    try:
        raw = _gemini_tweet(RESUMEN_DEPORTE_PROMPT.format(
            deporte_label=deporte_label,
            torneo=torneo,
            acertadas=acertadas,
            total=total,
            beneficio=beneficio,
        ))

        partes = raw.split("---TELEGRAM---")
        tweet        = _strip_links(partes[0].strip())
        msg_telegram = partes[1].strip() if len(partes) > 1 else tweet

        publish_telegram_text(msg_telegram)

        save_resumen_diario(
            picks_totales=len(picks_hoy),
            picks_win=wins,
            picks_loss=losses,
            profit_dia=profit_dia,
            profit_mes=stats_mes["profit_mes"],
            racha=racha,
            texto=msg_telegram,
        )
        marcar_publicado_hoy(evento)
        logger.info("Resumen %s publicado", evento)

    except Exception as e:
        logger.error("Error en resumen %s: %s", evento, e)


# ---------------------------------------------------------------------------
# ~12:00 — Tweet único diario en X (mejor pick del día, anti-ban)
# ---------------------------------------------------------------------------

def post_daily_x_pick(skip_jitter: bool = False):
    if ya_publicado_hoy("daily_x_pick"):
        logger.info("Daily X pick ya publicado hoy, skipping.")
        return

    if not skip_jitter:
        jitter = random.randint(0, 30 * 60)  # 0-30 min → ventana 11:45-12:15
        logger.info("Daily X pick: esperando %d seg (jitter)...", jitter)
        time.sleep(jitter)

    logger.info("=== DAILY X PICK (mejor de 5 dardos + 5 balonmano) ===")
    now = datetime.now()

    darts_picks    = _collect_candidates("darts",    now, max_picks=5)
    handball_picks = _collect_candidates("handball", now, max_picks=5)
    all_picks = sorted(darts_picks + handball_picks, key=lambda x: x["ev"], reverse=True)

    if not all_picks:
        logger.info("Sin partidos para el daily X pick")
        return

    if not can_post_x():
        logger.info("Límite X alcanzado, no se publica daily pick")
        return

    pick = all_picks[0]
    analysis    = pick["analysis"]
    recommended = analysis.get("recommended_player", pick["player1"])
    prob        = (analysis["prob_player1"] if recommended == pick["player1"] else analysis["prob_player2"]) * 100
    factores    = ", ".join(analysis.get("factores_clave", []))

    logger.info("Mejor pick: %s vs %s | EV=%.2f%% | %s", pick["player1"], pick["player2"], pick["ev"], pick["sport"])

    # --- Telegram ---
    try:
        tg_ok = publish_telegram(
            player1=pick["player1"],
            player2=pick["player2"],
            sport=pick["sport"],
            analysis=analysis,
            value_data=pick["value"],
            bet365_odd=pick["odd"],
        )
        if tg_ok:
            save_pick(
                sport=pick["sport"],
                player1=pick["player1"],
                player2=pick["player2"],
                pick_jugador=recommended,
                cuota=pick["odd"],
                ev_porcentaje=pick["ev"],
                confianza=analysis["confianza"],
                publicado_telegram=True,
                publicado_x=False,
            )
            logger.info("Pick publicado en Telegram: %s vs %s", pick["player1"], pick["player2"])
    except Exception as e:
        logger.error("Error publicando en Telegram: %s", e)

    # --- X (hilo) ---
    try:
        sport_label = "Dardos PDC" if pick["sport"] == "darts" else "Balonmano"
        raw = _gemini_tweet(DAILY_X_THREAD_PROMPT.format(
            player1=pick["player1"],
            player2=pick["player2"],
            tournament=pick["tournament"],
            sport_label=sport_label,
            recommended_player=recommended,
            odd=pick["odd"],
            ev=pick["ev"],
            prob=prob,
            confianza=analysis["confianza"],
            razon=analysis.get("razon", ""),
            factores=factores,
        ))

        tweets = [_strip_links(t.strip()) for t in raw.split("---") if t.strip()]
        if not tweets:
            logger.error("Gemini no generó tweets para el hilo")
        else:
            n_encolados = publish_thread(tweets, x_counter_callback=_mark_x)
            if n_encolados:
                logger.info("Hilo X encolado (%d tweets): %s vs %s", n_encolados, pick["player1"], pick["player2"])
    except Exception as e:
        logger.error("Error en hilo X: %s", e)

    marcar_publicado_hoy("daily_x_pick")


# ---------------------------------------------------------------------------
# Fútbol — pick diario vía Gemini Search (sin scraping, sin cuotas)
# ---------------------------------------------------------------------------

def post_football_pick(skip_jitter: bool = False):
    if ya_publicado_hoy("football_pick"):
        logger.info("Football pick ya publicado hoy, skipping.")
        return

    if not skip_jitter:
        jitter = random.randint(0, 20 * 60)  # ventana ±20 min
        logger.info("Football pick: esperando %d seg (jitter)...", jitter)
        time.sleep(jitter)

    logger.info("=== FOOTBALL PICK ===")

    if not can_post_x():
        logger.info("Límite X alcanzado, no se publica football pick")
        return

    try:
        from datetime import date as _date
        today_str = datetime.now().strftime("%A %d de %B de %Y")

        response = _gemini.models.generate_content(
            model=_GEMINI_MODEL,
            contents=FOOTBALL_X_THREAD_PROMPT.format(date=today_str),
            config=_SEARCH_CONFIG,
        )
        raw = response.text.strip()

        tweets = [_strip_links(t.strip()) for t in raw.split("---") if t.strip()]
        if not tweets:
            logger.error("Gemini no generó tweets para el football pick")
            return

        n_encolados = publish_thread(tweets, x_counter_callback=_mark_x)
        if n_encolados:
            logger.info("Football pick encolado (%d tweets)", n_encolados)

        marcar_publicado_hoy("football_pick")

    except Exception as e:
        logger.error("Error en football pick: %s", e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    setup_logging()
    init_db()
    logger.info("Tipster Bot arrancando... (TESTING_MODE=%s)", TESTING_MODE)

    if "--now" in sys.argv:
        logger.info("--now: ejecutando previa y saliendo...")
        post_previa()
        logger.info("--now: listo.")
        return

    if TESTING_MODE:
        logger.info("TESTING_MODE: ejecutando previa de prueba...")
        post_previa()
        return

    # Catch-up: ejecutar slots perdidos en las últimas 2 horas
    now = datetime.now()
    SLOTS = [
        ("09:00", post_football_pick,   {"skip_jitter": True}),
        ("11:45", post_daily_x_pick,    {"skip_jitter": True}),
        ("22:30", resumen_handball,     {}),
        ("23:30", resumen_dardos,       {}),
    ]
    for slot_time, func, kwargs in SLOTS:
        h, m = map(int, slot_time.split(":"))
        slot_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        diff = (now - slot_dt).total_seconds()
        if 0 <= diff <= 7200:
            logger.info("Catch-up: ejecutando slot %s perdido hace %.0f min", slot_time, diff / 60)
            func(**kwargs)

    # Slots diarios
    schedule.every().day.at("09:00").do(post_football_pick)   # jitter interno → 09:00-09:20 | solo X
    schedule.every().day.at("11:45").do(post_daily_x_pick)    # jitter interno → 11:45-12:15 | Telegram + X
    schedule.every().day.at("22:30").do(resumen_handball)
    schedule.every().day.at("23:30").do(resumen_dardos)
    schedule.every().day.at("00:00").do(_reset_x_counter)

    logger.info("Scheduler activo — slots: 09:00(fútbol X) 11:45(dardos/balonmano Telegram+X) 22:30 23:30")
    logger.info("1 post diario en Telegram y hilo en X (~12:00 ±15min) | Pulsa Ctrl+C para detener")

    while True:
        try:
            schedule.run_pending()
            time.sleep(30)
        except KeyboardInterrupt:
            logger.info("Bot detenido.")
            sys.exit(0)
        except Exception as e:
            logger.error("Error en bucle principal: %s", e)
            time.sleep(60)


if __name__ == "__main__":
    main()
