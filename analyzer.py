"""
Análisis de partidos usando Google Gemini API.
El LLM estima probabilidades; la lógica de negocio decide si publicar.
"""
import os
import json
import logging
from google import genai

from config import GEMINI_API_KEY, VALUE_THRESHOLD
from prompts import ANALYSIS_PROMPT

TESTING_MODE = os.getenv("TESTING_MODE", "false").lower() == "true"

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=GEMINI_API_KEY)

# Modelo a usar
MODEL = "gemini-3-flash-preview"


def analyze_match(match_context: str, odds_data: dict) -> dict | None:
    """
    Llama a Gemini para analizar el partido y obtener probabilidades estimadas.

    Args:
        match_context: String con estadísticas de los jugadores (de scraper.py)
        odds_data: Dict con cuotas (de odds_scraper.py)

    Returns:
        Dict con el análisis o None si falla:
        {
            prob_player1, prob_player2, confianza,
            razon, factores_clave, raw_response
        }
    """
    # Construir resumen de cuotas legible para el LLM
    odds_summary = _format_odds_for_prompt(odds_data)

    prompt = ANALYSIS_PROMPT.format(
        match_context=match_context,
        odds_summary=odds_summary,
    )

    try:
        logger.info("Enviando análisis a Gemini (%s)...", MODEL)
        response = _client.models.generate_content(
            model=MODEL,
            contents=prompt,
        )

        raw_response = response.text
        logger.debug("Respuesta cruda de Gemini: %s", raw_response[:200])

        analysis = _parse_analysis_response(raw_response)
        if analysis:
            analysis["raw_response"] = raw_response
            logger.info(
                "Análisis completado → prob_p1=%.2f%% | prob_p2=%.2f%% | confianza=%s",
                analysis["prob_player1"] * 100,
                analysis["prob_player2"] * 100,
                analysis["confianza"],
            )
        return analysis

    except Exception as e:
        logger.error("Error inesperado en analyze_match: %s", e)

    return None


def _parse_analysis_response(raw: str) -> dict | None:
    """
    Extrae y valida el JSON de la respuesta del LLM.
    Maneja casos donde el LLM añade texto antes/después del JSON,
    o envuelve la respuesta en bloques ```json ... ```.
    """
    # Eliminar bloques de código markdown si los hay
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        # Intentar parseo directo
        data = json.loads(clean)
    except json.JSONDecodeError:
        # Intentar extraer el JSON embebido en texto
        try:
            start = clean.index("{")
            end = clean.rindex("}") + 1
            data = json.loads(clean[start:end])
        except (ValueError, json.JSONDecodeError) as e:
            logger.error("No se pudo parsear JSON de la respuesta del LLM: %s", e)
            logger.error("Respuesta recibida: %s", raw[:500])
            return None

    # Validar campos requeridos
    required_fields = ["prob_player1", "prob_player2", "confianza", "razon", "factores_clave"]
    for field in required_fields:
        if field not in data:
            logger.error("Campo faltante en respuesta del LLM: %s", field)
            return None

    # Validar que las probabilidades sumen ~1.0
    total = data["prob_player1"] + data["prob_player2"]
    if not (0.98 <= total <= 1.02):
        logger.warning(
            "Probabilidades no suman 1.0 (suma=%.3f), normalizando...", total
        )
        data["prob_player1"] = round(data["prob_player1"] / total, 4)
        data["prob_player2"] = round(data["prob_player2"] / total, 4)

    # Validar confianza
    if data["confianza"] not in ("alta", "media", "baja"):
        logger.warning("Nivel de confianza inválido: %s, usando 'baja'", data["confianza"])
        data["confianza"] = "baja"

    return data


def _format_odds_for_prompt(odds_data: dict) -> str:
    """Formatea las cuotas en texto legible para incluir en el prompt."""
    lines = []

    bet365 = odds_data.get("bet365", {})
    if bet365.get("player1") and bet365.get("player2"):
        lines.append(f"Bet365: Jugador1={bet365['player1']} | Jugador2={bet365['player2']}")

    market_avg = odds_data.get("market_avg", {})
    if market_avg.get("player1") and market_avg.get("player2"):
        lines.append(
            f"Media de mercado: Jugador1={market_avg['player1']} | Jugador2={market_avg['player2']}"
        )

    if odds_data.get("error"):
        lines.append(f"Nota: {odds_data['error']}")

    return "\n".join(lines) if lines else "Cuotas no disponibles"


def is_publishable_pick(analysis: dict, value_data: dict) -> bool:
    """
    Decide si el pick es publicable según criterios de calidad.

    Criterios (ambos deben cumplirse):
    1. EV > 4% (value_data['ev_percentage'] > 4)
    2. Confianza del LLM alta o media

    El LLM no decide: solo aporta probabilidad y confianza como inputs.

    Returns:
        True si el pick merece ser publicado
    """
    if not analysis or not value_data:
        return False

    # En TESTING_MODE saltamos los filtros para forzar publicación
    if TESTING_MODE:
        logger.info(
            "TESTING_MODE activo → publicación forzada (EV=%.2f%%, confianza=%s)",
            value_data.get("ev_percentage", 0),
            analysis.get("confianza"),
        )
        return True

    ev_ok = value_data.get("ev_percentage", 0) > (VALUE_THRESHOLD * 100)
    confianza_ok = analysis.get("confianza") in ("alta", "media")

    logger.info(
        "Filtro publicación → EV=%.2f%% (min %.0f%%) | Confianza=%s | Publicable=%s",
        value_data.get("ev_percentage", 0),
        VALUE_THRESHOLD * 100,
        analysis.get("confianza"),
        ev_ok and confianza_ok,
    )

    return ev_ok and confianza_ok
