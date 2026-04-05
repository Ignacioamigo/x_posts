"""
Publicación de picks en Telegram y X (Twitter).
- Telegram: mensaje formateado con emojis, cuota, stake y EV%.
- X: 4 tweets generados por Gemini, publicados en background con 90 min de delay.
- Límite diario de 7 posts en X (gestionado desde scheduler.py via can_post_x()).
"""
import os
import time
import logging
import threading
from google import genai
import telebot
import tweepy

from config import (
    GEMINI_API_KEY,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHANNEL_ID,
    X_API_KEY,
    X_API_SECRET,
    X_ACCESS_TOKEN,
    X_ACCESS_SECRET,
    STAKE_UNITS,
)
from prompts import TWEETS_PROMPT

logger = logging.getLogger(__name__)

# Diagnóstico de credenciales X al arrancar
print(f"X_API_KEY: {X_API_KEY[:8]}...")
print(f"X_ACCESS_TOKEN: {X_ACCESS_TOKEN[:8]}...")

TESTING_MODE = os.getenv("TESTING_MODE", "false").lower() == "true"

_gemini_client = genai.Client(api_key=GEMINI_API_KEY)

_telegram_bot = None
_x_client = None

MODEL = "gemini-3-flash-preview"

SPORT_EMOJI = {
    "darts": "🎯",
    "table-tennis": "🏓",
}

# Delay entre tweets en producción (90 minutos)
TWEET_DELAY_SECONDS = 0 if TESTING_MODE else 5400


def _get_telegram_bot() -> telebot.TeleBot:
    global _telegram_bot
    if _telegram_bot is None:
        _telegram_bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
    return _telegram_bot


def _get_x_client() -> tweepy.Client:
    global _x_client
    if _x_client is None:
        _x_client = tweepy.Client(
            consumer_key=X_API_KEY,
            consumer_secret=X_API_SECRET,
            access_token=X_ACCESS_TOKEN,
            access_token_secret=X_ACCESS_SECRET,
        )
    return _x_client


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def publish_telegram(
    player1: str,
    player2: str,
    sport: str,
    analysis: dict,
    value_data: dict,
    bet365_odd: float,
) -> bool:
    """Publica el pick en el canal de Telegram. Devuelve True si OK."""
    try:
        emoji = SPORT_EMOJI.get(sport, "⚽")
        sport_name = "Dardos PDC" if sport == "darts" else "Tenis de Mesa"

        if analysis["prob_player1"] >= analysis["prob_player2"]:
            recommended = player1
            llm_prob = analysis["prob_player1"]
        else:
            recommended = player2
            llm_prob = analysis["prob_player2"]

        confianza_emoji = {"alta": "🟢", "media": "🟡", "baja": "🔴"}.get(
            analysis["confianza"], "⚪"
        )
        factores = "\n".join(f"  • {f}" for f in analysis.get("factores_clave", []))

        mensaje = (
            f"{emoji} *PICK DEL DÍA* {emoji}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆 *{sport_name}*\n"
            f"⚔️ {player1} vs {player2}\n\n"
            f"✅ *APOYO: {recommended}*\n\n"
            f"📊 *Análisis:*\n"
            f"{analysis.get('razon', 'Sin razon disponible')}\n\n"
            f"🔑 *Factores clave:*\n"
            f"{factores}\n\n"
            f"💰 *Cuota Bet365:* `{bet365_odd}`\n"
            f"📈 *EV estimado:* `{value_data['ev_percentage']:.2f}%`\n"
            f"🎯 *Prob. estimada:* `{llm_prob*100:.1f}%`\n"
            f"{confianza_emoji} *Confianza:* {analysis['confianza'].upper()}\n"
            f"🏦 *Stake:* {STAKE_UNITS}u\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ _Solo apuesta lo que puedas permitirte perder._\n"
            f"👇 t.me/frikipickss"
        )

        _get_telegram_bot().send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=mensaje,
            parse_mode="Markdown",
        )
        logger.info("Pick publicado en Telegram: %s vs %s → %s", player1, player2, recommended)
        return True

    except telebot.apihelper.ApiException as e:
        logger.error("Error API Telegram: %s", e)
    except Exception as e:
        logger.error("Error publicando en Telegram: %s", e)
    return False


def publish_telegram_text(text: str) -> bool:
    """Publica texto libre en Telegram (para preview y resumen)."""
    try:
        _get_telegram_bot().send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=text,
            parse_mode="Markdown",
        )
        logger.info("Mensaje Telegram publicado (%d chars)", len(text))
        return True
    except Exception as e:
        logger.error("Error publicando texto en Telegram: %s", e)
    return False


# ---------------------------------------------------------------------------
# X (Twitter)
# ---------------------------------------------------------------------------

def generate_x_tweets(
    player1: str,
    player2: str,
    sport: str,
    analysis: dict,
    odd: float,
) -> list[str]:
    """Genera 4 tweets con Gemini. Devuelve lista vacía si falla."""
    try:
        sport_name = "Dardos PDC" if sport == "darts" else "Tenis de Mesa"
        emoji = SPORT_EMOJI.get(sport, "⚽")

        if analysis["prob_player1"] >= analysis["prob_player2"]:
            recommended = player1
            llm_prob = analysis["prob_player1"]
        else:
            recommended = player2
            llm_prob = analysis["prob_player2"]

        prompt = TWEETS_PROMPT.format(
            sport=f"{sport_name} {emoji}",
            player1=player1,
            player2=player2,
            recommended_player=recommended,
            odd=odd,
            ev_percentage=round((llm_prob * odd - 1) * 100, 2),
            razon=analysis.get("razon", "Sin razon"),
            factores_clave=", ".join(analysis.get("factores_clave", [])),
        )

        logger.info("Generando tweets para %s vs %s...", player1, player2)
        response = _gemini_client.models.generate_content(model=MODEL, contents=prompt)

        raw = response.text
        tweets = [t.strip() for t in raw.split("---TWEET---") if t.strip()]
        valid = []
        for tweet in tweets[:4]:
            if len(tweet) > 280:
                tweet = tweet[:277] + "..."
            valid.append(tweet)

        logger.info("Tweets generados: %d", len(valid))
        return valid

    except Exception as e:
        logger.error("Error generando tweets: %s", e)
    return []


def publish_single_tweet(text: str) -> bool:
    """Publica un tweet suelto (para preview y resumen). Devuelve True si OK."""
    try:
        _get_x_client().create_tweet(text=text[:280])
        logger.info("Tweet publicado: %s...", text[:60])
        return True
    except tweepy.TweepyException as e:
        logger.error("Error Tweepy: %s", e)
    except Exception as e:
        logger.error("Error publicando tweet: %s", e)
    return False


def publish_x_tweets(tweets: list[str], x_counter_callback=None) -> int:
    """
    Publica tweets en X en un hilo de fondo con 90 min de delay entre ellos.
    x_counter_callback: función a llamar por cada tweet publicado (para el contador diario).
    En TESTING_MODE: solo publica el primero, sin delay, en el hilo principal.
    Devuelve inmediatamente el número de tweets encolados.
    """
    if not tweets:
        logger.warning("No hay tweets para publicar")
        return 0

    if TESTING_MODE:
        # En test: 1 tweet, sin hilo, sin delay
        ok = publish_single_tweet(tweets[0])
        if ok and x_counter_callback:
            x_counter_callback(1)
        return 1 if ok else 0

    # Producción: hilo de fondo, 4 tweets con 90 min de delay
    def _worker(tweet_list):
        published = 0
        for i, tweet in enumerate(tweet_list):
            if i > 0:
                logger.info("Tweet %d/%d: esperando 90 min...", i + 1, len(tweet_list))
                time.sleep(TWEET_DELAY_SECONDS)
            ok = publish_single_tweet(tweet)
            if ok:
                published += 1
                if x_counter_callback:
                    x_counter_callback(1)
        logger.info("Hilo tweets terminado: %d/%d publicados", published, len(tweet_list))

    t = threading.Thread(target=_worker, args=(tweets,), daemon=True)
    t.start()
    logger.info("%d tweets encolados en hilo de fondo (90 min entre cada uno)", len(tweets))
    return len(tweets)
