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

logger = logging.getLogger(__name__)

# Diagnóstico de credenciales X al arrancar
print(f"X_API_KEY: {X_API_KEY[:8]}...")
print(f"X_ACCESS_TOKEN: {X_ACCESS_TOKEN[:8]}...")

TESTING_MODE = os.getenv("TESTING_MODE", "false").lower() == "true"

_gemini_client = genai.Client(api_key=GEMINI_API_KEY)

_telegram_bot = None
_x_client     = None
_x_api_v1     = None

MODEL = "gemini-3-flash-preview"

SPORT_EMOJI = {
    "darts":    "🎯",
    "handball": "🤾",
}

# Delay entre tweets en producción (90 minutos)
TWEET_DELAY_SECONDS = 0 if TESTING_MODE else 180


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


def _get_x_api_v1() -> tweepy.API:
    """API v1.1 — necesaria solo para media_upload."""
    global _x_api_v1
    if _x_api_v1 is None:
        auth = tweepy.OAuth1UserHandler(
            X_API_KEY, X_API_SECRET,
            X_ACCESS_TOKEN, X_ACCESS_SECRET,
        )
        _x_api_v1 = tweepy.API(auth)
    return _x_api_v1


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
        sport_name = "Dardos PDC" if sport == "darts" else "Balonmano"

        recommended = analysis.get("recommended_player", player1)
        llm_prob = analysis["prob_player1"] if recommended == player1 else analysis["prob_player2"]

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


def publish_single_tweet(text: str, image_path: str = None, reply_to_id: str = None) -> str | None:
    """
    Publica un tweet. Devuelve el tweet_id si OK, None si falla.
    image_path: adjunta imagen (solo al primer tweet de un hilo).
    reply_to_id: si se indica, publica como respuesta a ese tweet_id.
    """
    try:
        media_ids = None
        if image_path:
            try:
                media = _get_x_api_v1().media_upload(filename=image_path)
                media_ids = [media.media_id]
                logger.info("Imagen subida a X: media_id=%s", media.media_id)
            except Exception as e:
                logger.warning("No se pudo subir imagen, publicando sin ella: %s", e)

        kwargs = {"text": text[:280]}
        if media_ids:
            kwargs["media_ids"] = media_ids
        if reply_to_id:
            kwargs["in_reply_to_tweet_id"] = reply_to_id

        response = _get_x_client().create_tweet(**kwargs)
        tweet_id = response.data["id"]
        logger.info("Tweet publicado (id=%s): %s...", tweet_id, text[:60])
        return str(tweet_id)
    except tweepy.TweepyException as e:
        logger.error("Error Tweepy: %s", e)
    except Exception as e:
        logger.error("Error publicando tweet: %s", e)
    return None


def publish_thread(tweets: list[str], image_path: str = None, x_counter_callback=None) -> int:
    """
    Publica una lista de tweets como hilo en X (cada uno responde al anterior).
    5 minutos de delay entre tweets del hilo.
    Corre en background (daemon=False). Devuelve inmediatamente el nº de tweets encolados.
    """
    if not tweets:
        return 0

    if TESTING_MODE:
        tweet_id = publish_single_tweet(tweets[0], image_path=image_path)
        if tweet_id and x_counter_callback:
            x_counter_callback(1)
        return 1 if tweet_id else 0

    def _worker(tweet_list, img):
        prev_id = None
        published = 0
        for i, text in enumerate(tweet_list):
            if i > 0:
                logger.info("Hilo tweet %d/%d: esperando 5 min...", i + 1, len(tweet_list))
                time.sleep(300)
            tweet_id = publish_single_tweet(
                text,
                image_path=img if i == 0 else None,
                reply_to_id=prev_id,
            )
            if tweet_id:
                prev_id = tweet_id
                published += 1
                if x_counter_callback:
                    x_counter_callback(1)
            else:
                logger.warning("Hilo interrumpido en tweet %d/%d", i + 1, len(tweet_list))
                break
        logger.info("Hilo terminado: %d/%d publicados", published, len(tweet_list))

    t = threading.Thread(target=_worker, args=(tweets, image_path), daemon=False)
    t.start()
    logger.info("%d tweets de hilo encolados (5 min entre cada uno)", len(tweets))
    return len(tweets)


def publish_x_tweets(tweets: list[str], x_counter_callback=None, image_path: str = None) -> int:
    """
    Publica tweets en X en un hilo de fondo con 90 min de delay entre ellos.
    image_path: si se proporciona, adjunta la imagen solo al primer tweet.
    x_counter_callback: función a llamar por cada tweet publicado (para el contador diario).
    En TESTING_MODE: solo publica el primero, sin delay, en el hilo principal.
    Devuelve inmediatamente el número de tweets encolados.
    """
    if not tweets:
        logger.warning("No hay tweets para publicar")
        return 0

    if TESTING_MODE:
        ok = publish_single_tweet(tweets[0], image_path=image_path)
        if ok and x_counter_callback:
            x_counter_callback(1)
        return 1 if ok else 0

    # Producción: hilo de fondo, 4 tweets con 90 min de delay
    def _worker(tweet_list, img):
        published = 0
        for i, tweet in enumerate(tweet_list):
            if i > 0:
                logger.info("Tweet %d/%d: esperando 90 min...", i + 1, len(tweet_list))
                time.sleep(TWEET_DELAY_SECONDS)
            ok = publish_single_tweet(tweet, image_path=img if i == 0 else None)
            if ok:
                published += 1
                if x_counter_callback:
                    x_counter_callback(1)
        logger.info("Hilo tweets terminado: %d/%d publicados", published, len(tweet_list))

    t = threading.Thread(target=_worker, args=(tweets, image_path), daemon=False)
    t.start()
    logger.info("%d tweets encolados en hilo de fondo (3 min entre cada uno)", len(tweets))
    return len(tweets)
