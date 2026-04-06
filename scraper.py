"""
Obtención de partidos del día y contexto estadístico de jugadores.
Ambas funciones usan Gemini con Google Search grounding: sin scrapers frágiles,
sin Selenium, sin dependencias externas más allá del SDK de Google.
TESTING_MODE=true activa partidos ficticios sin llamar a ninguna API.
"""
import os
import json
import logging
from datetime import datetime
from google import genai
from google.genai import types

from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=GEMINI_API_KEY)

TESTING_MODE = os.getenv("TESTING_MODE", "false").lower() == "true"

# Modelo con capacidad de búsqueda en tiempo real
_SEARCH_MODEL = "gemini-3-flash-preview"

# Config reutilizable con Google Search grounding
_SEARCH_CONFIG = types.GenerateContentConfig(
    tools=[types.Tool(google_search=types.GoogleSearch())]
)


# ---------------------------------------------------------------------------
# Partidos del día
# ---------------------------------------------------------------------------

def get_todays_matches() -> list[dict]:
    """
    Obtiene los partidos de dardos PDC y tenis de mesa profesional del día.

    Estrategia:
    - TESTING_MODE=true → devuelve partidos ficticios del circuito PDC/ITTF.
    - Caso normal → Gemini con Google Search busca los partidos reales de hoy
      y devuelve la lista parseada desde JSON.

    Formato de salida: [{player1, player2, sport, time, tournament}, ...]
    """
    if TESTING_MODE:
        return _get_test_matches()

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    dia_semana = now.strftime("%A")  # Monday, Tuesday...
    weekday = now.weekday()          # 0=lun, 3=jue, 6=dom

    logger.info("=== Obteniendo partidos (%s %s %s) con Gemini Search ===", dia_semana, today, current_time)

    darts_context = "PRIORITARIO hoy (jueves): PDC Premier League. " if weekday == 3 else ""

    prompt = (
        f"Busca partidos que se jueguen HOY {today} ({dia_semana}) "
        f"a partir de las {current_time} hora española.\n\n"
        f"LIGAS DE TENIS DE MESA (solo estas, que están en Bet365):\n"
        f"- Setka Cup (la más importante, muchos partidos diarios)\n"
        f"- Setka Cup Women\n"
        f"- Challenger Series TT\n"
        f"- TT Cup\n"
        f"- TT Elite Series\n"
        f"- Czech Liga Pro\n\n"
        f"LIGAS DE DARDOS (solo estas):\n"
        f"- PDC Premier League (solo jueves)\n"
        f"- PDC Players Championship\n"
        f"- PDC European Tour\n"
        f"- PDC World Series\n"
        f"{darts_context}\n"
        f"NO busques otras ligas. Solo las listadas.\n\n"
        f"REGLAS ESTRICTAS:\n"
        f"- Solo partidos que AUN NO HAN EMPEZADO\n"
        f"- La hora de inicio debe ser posterior a {current_time}\n"
        f"- Si no estás seguro de si un partido ya se jugó, NO lo incluyas\n"
        f"- NO incluyas partidos de madrugada que ya terminaron\n\n"
        f"Responde SOLO con JSON válido, sin texto adicional ni markdown:\n"
        f'[{{"player1":"nombre","player2":"nombre",'
        f'"sport":"darts o table-tennis","time":"HH:MM","tournament":"nombre"}}]\n\n'
        f"Si no hay partidos futuros, responde: []"
    )

    # Reintentar hasta 3 veces si el JSON está malformado
    for intento in range(1, 4):
        try:
            response = _client.models.generate_content(
                model=_SEARCH_MODEL,
                contents=prompt,
                config=_SEARCH_CONFIG,
            )
            raw = response.text.strip()
            logger.debug("Respuesta Gemini (intento %d): %s", intento, raw[:300])

            matches = _parse_matches_json(raw)
            if matches is not None:  # None indica fallo de parseo, [] es válido
                matches = _filter_upcoming(matches, now)
                logger.info("Gemini Search → %d partidos pendientes", len(matches))
                return matches
            logger.warning("JSON malformado en intento %d, reintentando...", intento)

        except Exception as e:
            logger.error("Error Gemini Search intento %d: %s", intento, e)

    logger.error("Todos los intentos fallaron. Sin partidos.")
    return []


def _parse_matches_json(raw: str) -> list[dict] | None:
    """Devuelve lista (puede ser []) si el JSON es válido, None si está malformado."""
    """
    Extrae y valida la lista de partidos del JSON devuelto por Gemini.
    Maneja bloques ```json ... ``` y texto extra antes/después del array.
    """
    # Eliminar bloque markdown si lo hay
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        end = next((i for i in range(len(lines) - 1, 0, -1) if lines[i].strip() == "```"), len(lines))
        clean = "\n".join(lines[1:end])

    # Extraer el array JSON aunque haya texto alrededor
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        try:
            start = clean.index("[")
            end = clean.rindex("]") + 1
            data = json.loads(clean[start:end])
        except (ValueError, json.JSONDecodeError) as e:
            logger.error("No se pudo parsear JSON de partidos: %s | Raw: %s", e, raw[:300])
            return None

    if not isinstance(data, list):
        logger.error("Gemini devolvió JSON pero no es una lista: %s", type(data))
        return None

    # Nombres que indican jugador sin confirmar
    _PLACEHOLDERS = {"tba", "tbd", "?", "-", "unknown", "player 1", "player 2", "jugador 1", "jugador 2"}

    # Validar y normalizar cada partido
    valid = []
    for item in data:
        if not isinstance(item, dict):
            continue
        player1 = item.get("player1", "").strip()
        player2 = item.get("player2", "").strip()
        sport = item.get("sport", "").strip().lower()
        if not player1 or not player2 or sport not in ("darts", "table-tennis"):
            logger.warning("Partido inválido descartado: %s", item)
            continue
        if player1.lower() in _PLACEHOLDERS or player2.lower() in _PLACEHOLDERS:
            logger.warning("Partido con jugador sin confirmar descartado: %s vs %s", player1, player2)
            continue
        valid.append({
            "player1": player1,
            "player2": player2,
            "sport": sport,
            "time": item.get("time", "?"),
            "tournament": item.get("tournament", ""),
        })

    return valid


def _filter_upcoming(matches: list[dict], now: datetime) -> list[dict]:
    """
    Descarta partidos cuya hora ya ha pasado.
    Si el partido no tiene hora válida lo deja pasar (mejor publicar que perder).
    """
    upcoming = []
    for match in matches:
        time_str = match.get("time", "?")
        try:
            match_dt = datetime.strptime(
                f"{now.strftime('%Y-%m-%d')} {time_str}", "%Y-%m-%d %H:%M"
            )
            if match_dt > now:
                upcoming.append(match)
            else:
                logger.info(
                    "Partido descartado (ya jugado): %s vs %s a las %s",
                    match["player1"], match["player2"], time_str,
                )
        except ValueError:
            # Hora no parseable → incluir por precaución
            upcoming.append(match)
    return upcoming


def _get_test_matches() -> list[dict]:
    """Partidos reales del circuito PDC/ITTF para pruebas sin consumir API."""
    logger.info("TESTING_MODE activo: usando partidos de prueba del circuito PDC.")
    return [
        {
            "player1": "Luke Littler",
            "player2": "Michael van Gerwen",
            "sport": "darts",
            "time": "19:00",
            "tournament": "PDC Premier League",
        },
        {
            "player1": "Fan Zhendong",
            "player2": "Ma Long",
            "sport": "table-tennis",
            "time": "14:00",
            "tournament": "ITTF World Tour",
        },
    ]


# ---------------------------------------------------------------------------
# Contexto estadístico de jugadores
# ---------------------------------------------------------------------------

def get_match_context(player1: str, player2: str, sport: str) -> str:
    """
    Obtiene estadísticas recientes, head to head y contexto relevante
    del partido usando Gemini con Google Search grounding.

    Más robusto que cualquier scraping: busca en tiempo real.
    Devuelve string listo para incluir en el prompt de análisis.
    """
    sport_name = "dardos PDC" if sport == "darts" else "tenis de mesa"

    prompt = (
        f"Busca estadísticas recientes de {player1} y {player2} en {sport_name}. "
        f"Incluye: forma reciente (últimos 5 partidos de cada uno), "
        f"head to head histórico entre ellos, ranking actual de ambos, "
        f"average o nivel de juego actual, y cualquier dato relevante "
        f"para predecir el resultado. "
        f"Responde en español, máximo 200 palabras, sin markdown."
    )

    try:
        logger.info("Gemini Search: contexto para %s vs %s (%s)...", player1, player2, sport)
        response = _client.models.generate_content(
            model=_SEARCH_MODEL,
            contents=prompt,
            config=_SEARCH_CONFIG,
        )
        context = response.text.strip()
        logger.info("Contexto obtenido: %d caracteres", len(context))
        return f"=== Estadísticas en tiempo real ===\n{context}"

    except Exception as e:
        logger.error("Error en Gemini Search (contexto %s vs %s): %s", player1, player2, e)
        return f"Contexto no disponible para {player1} vs {player2}"
