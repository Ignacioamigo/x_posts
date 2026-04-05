"""
Obtención de cuotas via Gemini Search y lógica de detección de value bets.
El LLM solo estima probabilidad; detect_value() toma la decisión matemática.
En TESTING_MODE devuelve cuotas simuladas sin llamar a ninguna API.
"""
import os
import json
import logging
from google import genai
from google.genai import types

from config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=GEMINI_API_KEY)

TESTING_MODE = os.getenv("TESTING_MODE", "false").lower() == "true"

_SEARCH_MODEL = "gemini-3-flash-preview"

_SEARCH_CONFIG = types.GenerateContentConfig(
    tools=[types.Tool(google_search=types.GoogleSearch())]
)

# Cuotas simuladas para TESTING_MODE
_TEST_ODDS = {
    ("luke littler", "michael van gerwen"): {"player1": 2.10, "player2": 1.75},
    ("fan zhendong", "ma long"):            {"player1": 1.80, "player2": 2.05},
}


def _get_test_odds(player1: str, player2: str) -> dict:
    """Devuelve cuotas ficticias para pruebas."""
    key = (player1.lower(), player2.lower())
    odds_raw = _TEST_ODDS.get(key) or _TEST_ODDS.get((key[1], key[0]))
    if odds_raw:
        if (key[1], key[0]) in _TEST_ODDS and key not in _TEST_ODDS:
            odds_raw = {"player1": odds_raw["player2"], "player2": odds_raw["player1"]}
    else:
        odds_raw = {"player1": 1.90, "player2": 1.90}

    logger.info("TEST odds: %s @%.2f | %s @%.2f",
                player1, odds_raw["player1"], player2, odds_raw["player2"])
    return {
        "bet365": odds_raw,
        "market_avg": {
            "player1": round(odds_raw["player1"] - 0.05, 2),
            "player2": round(odds_raw["player2"] - 0.05, 2),
        },
        "all_bookmakers": [{"bookmaker": "Bet365", **odds_raw}],
        "error": None,
    }


def get_odds_from_oddsportal(player1: str, player2: str) -> dict:
    """
    Obtiene las cuotas del partido usando Gemini con Google Search.
    Busca cuotas de Bet365 y media de mercado en tiempo real.
    En TESTING_MODE devuelve cuotas simuladas.
    """
    if TESTING_MODE:
        return _get_test_odds(player1, player2)

    prompt = (
        f"Busca las cuotas actuales de apuestas para el partido {player1} vs {player2}. "
        f"Necesito las cuotas decimales europeas de Bet365 y la media del mercado. "
        f"Responde ÚNICAMENTE con JSON válido sin markdown:\n"
        f'{{"bet365_player1": 0.0, "bet365_player2": 0.0, '
        f'"avg_player1": 0.0, "avg_player2": 0.0}}\n'
        f"Si no encuentras cuotas de Bet365 específicamente, usa la media del mercado "
        f"para ambos campos. Si no hay cuotas disponibles devuelve exactamente: null"
    )

    try:
        logger.info("Gemini Search: cuotas para %s vs %s...", player1, player2)
        response = _client.models.generate_content(
            model=_SEARCH_MODEL,
            contents=prompt,
            config=_SEARCH_CONFIG,
        )
        raw = response.text.strip()
        logger.debug("Respuesta cuotas Gemini: %s", raw[:200])
        return _parse_odds_response(raw, player1, player2)

    except Exception as e:
        logger.error("Error obteniendo cuotas con Gemini Search: %s", e)
        return {"bet365": {"player1": None, "player2": None},
                "market_avg": {"player1": None, "player2": None},
                "all_bookmakers": [], "error": str(e)}


def _parse_odds_response(raw: str, player1: str, player2: str) -> dict:
    """Parsea el JSON de cuotas devuelto por Gemini."""
    result = {
        "bet365": {"player1": None, "player2": None},
        "market_avg": {"player1": None, "player2": None},
        "all_bookmakers": [],
        "error": None,
    }

    # Eliminar markdown si lo hay
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        end = next((i for i in range(len(lines)-1, 0, -1) if lines[i].strip() == "```"), len(lines))
        clean = "\n".join(lines[1:end])

    if clean.lower() == "null" or clean == "[]":
        logger.warning("Gemini no encontró cuotas para %s vs %s", player1, player2)
        result["error"] = "Cuotas no disponibles"
        return result

    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        try:
            start = clean.index("{")
            end = clean.rindex("}") + 1
            data = json.loads(clean[start:end])
        except (ValueError, json.JSONDecodeError) as e:
            logger.error("No se pudo parsear JSON de cuotas: %s | raw: %s", e, raw[:200])
            result["error"] = "Error parseando cuotas"
            return result

    # Extraer y validar cuotas
    b365_p1 = _validate_odd(data.get("bet365_player1"))
    b365_p2 = _validate_odd(data.get("bet365_player2"))
    avg_p1  = _validate_odd(data.get("avg_player1") or data.get("bet365_player1"))
    avg_p2  = _validate_odd(data.get("avg_player2") or data.get("bet365_player2"))

    result["bet365"]     = {"player1": b365_p1, "player2": b365_p2}
    result["market_avg"] = {"player1": avg_p1,  "player2": avg_p2}

    if b365_p1 and b365_p2:
        result["all_bookmakers"] = [
            {"bookmaker": "Bet365", "player1": b365_p1, "player2": b365_p2}
        ]
        logger.info("Cuotas OK → %s @%.2f | %s @%.2f", player1, b365_p1, player2, b365_p2)
    else:
        result["error"] = "Cuotas incompletas"
        logger.warning("Cuotas incompletas para %s vs %s: %s", player1, player2, data)

    return result


def _validate_odd(val) -> float | None:
    """Valida que una cuota esté en rango razonable (1.01 - 100)."""
    try:
        v = float(val)
        if 1.01 <= v <= 100:
            return round(v, 3)
    except (TypeError, ValueError):
        pass
    return None


def calculate_implied_probability(odd: float) -> float:
    """Probabilidad implícita = 1 / cuota."""
    if not odd or odd <= 0:
        return 0.0
    return round(1 / odd, 4)


def detect_value(
    llm_probability: float,
    bet365_odd: float,
    threshold: float = 0.04,
) -> dict:
    """
    Detecta value bet: EV = (prob_LLM × cuota_Bet365) - 1
    El LLM solo aporta probabilidad. Esta función toma la decisión.
    """
    implied_prob = calculate_implied_probability(bet365_odd)
    ev = (llm_probability * bet365_odd) - 1
    ev_percentage = round(ev * 100, 2)
    has_value = ev_percentage > (threshold * 100)

    logger.info(
        "Value check → LLM prob: %.2f%% | Impl prob: %.2f%% | EV: %.2f%% | Value: %s",
        llm_probability * 100, implied_prob * 100, ev_percentage, has_value,
    )

    return {
        "has_value": has_value,
        "ev_percentage": ev_percentage,
        "llm_probability": llm_probability,
        "implied_probability": implied_prob,
        "bet365_odd": bet365_odd,
    }
