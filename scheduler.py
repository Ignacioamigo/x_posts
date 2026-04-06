"""
Punto de entrada principal del tipster bot.
Slots diarios: 07:00 preview | 11:00 13:00 17:00 19:00 21:00 pipelines | 23:30 resumen
Límite: 7 posts en X por día. Contador en memoria, reset a medianoche.
"""
import os
import sys
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
from analyzer import analyze_match, is_publishable_pick
from publisher import (
    publish_telegram, publish_telegram_text,
    generate_x_tweets, publish_x_tweets, publish_single_tweet,
)
from image_generator import generate_bet365_card
from google import genai
from google.genai import types
from config import GEMINI_API_KEY
from prompts import PREVIEW_PROMPT, RESUMEN_PROMPT

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

# ---------------------------------------------------------------------------
# Contador diario de posts en X (máx 7)
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
# 07:00 — Preview diario
# ---------------------------------------------------------------------------

def preview_diario():
    """Genera expectación sobre el día sin revelar picks concretos."""
    if ya_publicado_hoy("preview"):
        logger.info("Preview diario ya publicado hoy, skipping.")
        return

    now = datetime.now()
    fecha = now.strftime("%Y-%m-%d")
    dia_semana_es = ["Lunes", "Martes", "Miércoles", "Jueves",
                     "Viernes", "Sábado", "Domingo"][now.weekday()]

    logger.info("=== PREVIEW DIARIO (%s) ===", fecha)

    # Buscar partidos del día para el preview
    matches = get_todays_matches()
    if matches:
        n_darts = sum(1 for m in matches if m["sport"] == "darts")
        n_tt    = sum(1 for m in matches if m["sport"] == "handball")
        torneos = list({m.get("tournament", "") for m in matches if m.get("tournament")})[:3]
        resumen_partidos = (
            f"{n_darts} partidos de dardos, {n_tt} de balonmano. "
            f"Torneos: {', '.join(torneos) if torneos else 'varios'}"
        )
        primer_slot = "11:00"
    else:
        resumen_partidos = "Agenda pendiente de confirmar"
        primer_slot = "11:00"

    prompt = PREVIEW_PROMPT.format(
        dia_semana=dia_semana_es,
        fecha=fecha,
        resumen_partidos=resumen_partidos,
        primer_slot=primer_slot,
    )

    try:
        response = _gemini.models.generate_content(model=_GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        partes = raw.split("---TWEET---")
        msg_telegram = partes[0].strip()
        tweet = partes[1].strip() if len(partes) > 1 else msg_telegram[:280]

        publish_telegram_text(msg_telegram)

        if can_post_x():
            if publish_single_tweet(tweet):
                _mark_x(1)

        marcar_publicado_hoy("preview")
        logger.info("Preview diario publicado")

    except Exception as e:
        logger.error("Error en preview_diario: %s", e)


# ---------------------------------------------------------------------------
# Pipeline principal (parametrizado por sport y session)
# ---------------------------------------------------------------------------

def run_pipeline(sport: str = None, session: str = ""):
    """
    Ejecuta el pipeline para un deporte y sesión concretos.
    Si no hay partidos del deporte solicitado, intenta el alternativo.
    Si no hay nada, termina silenciosamente.
    """
    now = datetime.now()
    label = f"{sport or 'any'}/{session}" if session else (sport or "any")
    logger.info("=" * 55)
    logger.info("PIPELINE %s — %s", label.upper(), now.strftime("%Y-%m-%d %H:%M"))
    logger.info("=" * 55)

    # Obtener partidos y filtrar por deporte
    all_matches = get_todays_matches()
    sport_alt = "handball" if sport == "darts" else "darts"

    matches = [m for m in all_matches if sport is None or m["sport"] == sport]

    if not matches and sport:
        logger.info("Sin partidos de %s. Buscando %s como alternativa...", sport, sport_alt)
        matches = [m for m in all_matches if m["sport"] == sport_alt]

    if not matches:
        logger.info("Sin partidos para el slot %s. Skipping.", label)
        return

    logger.info("Partidos a procesar: %d", len(matches))

    # ── Fase 1: analizar todos los partidos y recoger candidatos ────────────
    candidatos = []  # lista de (ev, player1, player2, sport_m, tournament, best_analysis, best_value, best_odd)

    for i, match in enumerate(matches, 1):
        player1    = match["player1"]
        player2    = match["player2"]
        sport_m    = match["sport"]
        hora       = match.get("time", "?")
        tournament = match.get("tournament", "")

        logger.info("[%d/%d] %s vs %s (%s) %s", i, len(matches), player1, player2, sport_m, hora)

        try:
            match_context = get_match_context(player1, player2, sport_m)

            odds_data = get_odds_from_oddsportal(player1, player2)
            b365_p1 = odds_data.get("bet365", {}).get("player1")
            b365_p2 = odds_data.get("bet365", {}).get("player2")

            if not b365_p1 or not b365_p2:
                logger.warning("Sin cuotas Bet365 para %s vs %s, saltando", player1, player2)
                continue

            analysis = analyze_match(match_context, odds_data)
            if not analysis:
                logger.warning("Análisis fallido para %s vs %s", player1, player2)
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

            # TESTING_MODE: forzar candidato aunque no haya EV
            if TESTING_MODE and best_value is None:
                if analysis["prob_player1"] >= analysis["prob_player2"]:
                    best_value = value_p1; best_odd = b365_p1
                    best_analysis["recommended_player"] = player1
                else:
                    best_value = value_p2; best_odd = b365_p2
                    best_analysis["recommended_player"] = player2
                    best_analysis["prob_player1"], best_analysis["prob_player2"] = (
                        analysis["prob_player2"], analysis["prob_player1"]
                    )
                    player1, player2 = player2, player1
                logger.info("TESTING_MODE: forzando candidato %s @%.2f", player1, best_odd)

            if best_value and is_publishable_pick(best_analysis, best_value):
                ev = best_value["ev_percentage"]
                candidatos.append((ev, player1, player2, sport_m, tournament, best_analysis, best_value, best_odd))
                logger.info("Candidato aceptado: %s @%.2f | EV=%.2f%% | %s",
                            player1, best_odd, ev, best_analysis["confianza"])
            else:
                logger.info("❌ Descartado (sin value): %s vs %s", player1, player2)

        except Exception as e:
            logger.error("Error procesando %s vs %s: %s", player1, player2, e)

    # ── Fase 2: publicar solo el mejor candidato (mayor EV) ─────────────────
    if not candidatos:
        logger.info("Pipeline %s finalizado | Sin picks publicables", label)
        return

    candidatos.sort(key=lambda x: x[0], reverse=True)

    # Loguear los descartados por límite de slot
    for ev, p1, p2, *_ in candidatos[1:]:
        logger.info(
            "Descartado por límite de slot (mejor EV ya publicado): %s vs %s | EV=%.2f%%",
            p1, p2, ev,
        )

    ev, player1, player2, sport_m, tournament, best_analysis, best_value, best_odd = candidatos[0]
    logger.info("✅ PICK (mejor del slot): %s @%.2f | EV=%.2f%% | %s",
                player1, best_odd, ev, best_analysis["confianza"])

    telegram_ok = publish_telegram(
        player1=player1, player2=player2, sport=sport_m,
        analysis=best_analysis, value_data=best_value, bet365_odd=best_odd,
    )

    if telegram_ok:
        save_pick(
            sport=sport_m, player1=player1, player2=player2,
            pick_jugador=best_analysis.get("recommended_player", player1),
            cuota=best_odd, ev_porcentaje=best_value["ev_percentage"],
            confianza=best_analysis["confianza"],
            publicado_telegram=True, publicado_x=False,
        )

    if can_post_x():
        tweets = generate_x_tweets(
            player1=player1, player2=player2, sport=sport_m,
            analysis=best_analysis, odd=best_odd,
            tournament=tournament,
        )
        if tweets:
            image_path = None
            try:
                image_path = generate_bet365_card(
                    player=best_analysis.get("recommended_player", player1),
                    opponent=player2,
                    odd=best_odd,
                    tournament=tournament,
                )
            except Exception as e:
                logger.warning("No se pudo generar imagen del pick: %s", e)

            cupos = _X_LIMITE - _x_posts_hoy
            tweets = tweets[:cupos]
            publish_x_tweets(tweets, x_counter_callback=_mark_x, image_path=image_path)

    logger.info("Pipeline %s finalizado | Pick publicado: %s vs %s", label, player1, player2)


# ---------------------------------------------------------------------------
# 23:30 — Resumen diario
# ---------------------------------------------------------------------------

def resumen_diario():
    """Lee el historial del día y publica el resumen con tono canalla."""
    if ya_publicado_hoy("resumen"):
        logger.info("Resumen diario ya publicado hoy, skipping.")
        return

    logger.info("=== RESUMEN DIARIO ===")

    picks_hoy  = get_picks_today()
    stats_mes  = get_stats_month()
    racha      = get_racha_actual()

    picks_resueltos = [p for p in picks_hoy if p["resultado"]]
    profit_dia = round(sum(p["profit"] for p in picks_resueltos if p["profit"] is not None), 2)
    wins_dia   = sum(1 for p in picks_resueltos if p["resultado"] == "WIN")
    losses_dia = sum(1 for p in picks_resueltos if p["resultado"] == "LOSS")

    # Construir detalle de picks del día
    if picks_resueltos:
        detalle = []
        for p in picks_resueltos:
            icono = "✅" if p["resultado"] == "WIN" else "❌"
            profit_str = f"+{p['profit']}u" if p["profit"] > 0 else f"{p['profit']}u"
            detalle.append(f"{icono} {p['pick_jugador']} @{p['cuota']} → {profit_str}")
        datos_dia = "\n".join(detalle)
    elif picks_hoy:
        datos_dia = f"{len(picks_hoy)} pick(s) publicados, resultado pendiente de actualizar"
    else:
        datos_dia = "Sin picks publicados hoy"

    # Mensaje para mañana
    now = datetime.now()
    weekday_manana = (now.weekday() + 1) % 7
    if weekday_manana == 3:
        mensaje_manana = "Mañana hay PDC Premier League. Estad atentos 🎯"
    elif weekday_manana in (5, 6):
        mensaje_manana = "Mañana hay dardos PDC. Estad atentos 🎯"
    else:
        mensaje_manana = "Mañana volvemos con más balonmano y dardos ⏰"

    prompt = RESUMEN_PROMPT.format(
        datos_dia=datos_dia,
        profit_dia=profit_dia,
        profit_mes=stats_mes["profit_mes"],
        total_mes=stats_mes["total"],
        racha=racha,
        mensaje_manana=mensaje_manana,
    )

    try:
        response = _gemini.models.generate_content(model=_GEMINI_MODEL, contents=prompt)
        raw = response.text.strip()
        partes = raw.split("---TWEET---")
        msg_telegram = partes[0].strip()
        tweet = partes[1].strip() if len(partes) > 1 else msg_telegram[:280]

        publish_telegram_text(msg_telegram)

        if can_post_x():
            if publish_single_tweet(tweet):
                _mark_x(1)

        save_resumen_diario(
            picks_totales=len(picks_hoy),
            picks_win=wins_dia,
            picks_loss=losses_dia,
            profit_dia=profit_dia,
            profit_mes=stats_mes["profit_mes"],
            racha=racha,
            texto=msg_telegram,
        )
        marcar_publicado_hoy("resumen")
        logger.info("Resumen diario publicado y guardado")

    except Exception as e:
        logger.error("Error en resumen_diario: %s", e)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    setup_logging()
    init_db()
    logger.info("Tipster Bot arrancando... (TESTING_MODE=%s)", TESTING_MODE)

    # --now → ejecuta un pipeline inmediato y sale
    if "--now" in sys.argv:
        logger.info("--now: ejecutando pipeline darts/prime y saliendo...")
        run_pipeline(sport="darts", session="prime")
        logger.info("--now: pipeline finalizado.")
        return

    if TESTING_MODE:
        logger.info("TESTING_MODE: ejecutando pipeline de prueba...")
        run_pipeline()
        return

    # Catch-up: ejecutar slots perdidos en las últimas 2 horas
    now = datetime.now()
    SLOTS = [
        ("07:00", preview_diario, {}),
        ("11:00", run_pipeline, {"sport": "table-tennis", "session": "mañana"}),
        ("13:00", run_pipeline, {"sport": "table-tennis", "session": "tarde"}),
        ("17:00", run_pipeline, {"sport": "darts",        "session": "tarde"}),
        ("19:00", run_pipeline, {"sport": "darts",        "session": "prime"}),
        ("21:00", run_pipeline, {"sport": "table-tennis", "session": "noche"}),
        ("23:30", resumen_diario, {}),
    ]
    for slot_time, func, kwargs in SLOTS:
        h, m = map(int, slot_time.split(":"))
        slot_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        diff = (now - slot_dt).total_seconds()
        if 0 <= diff <= 7200:  # dentro de las últimas 2 horas
            logger.info("Catch-up: ejecutando slot %s perdido hace %.0f min", slot_time, diff / 60)
            func(**kwargs)

    # Slots diarios
    schedule.every().day.at("07:00").do(preview_diario)
    schedule.every().day.at("11:00").do(run_pipeline, sport="handball", session="mañana")
    schedule.every().day.at("13:00").do(run_pipeline, sport="handball", session="tarde")
    schedule.every().day.at("17:00").do(run_pipeline, sport="darts",        session="tarde")
    schedule.every().day.at("19:00").do(run_pipeline, sport="darts",        session="prime")
    schedule.every().day.at("21:00").do(run_pipeline, sport="handball", session="noche")
    schedule.every().day.at("23:30").do(resumen_diario)
    schedule.every().day.at("00:00").do(_reset_x_counter)

    logger.info("Scheduler activo — slots: 07:00 11:00 13:00 17:00 19:00 21:00 23:30")
    logger.info("Límite X: %d posts/día | Pulsa Ctrl+C para detener", _X_LIMITE)

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
