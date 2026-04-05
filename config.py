"""
Configuración central: carga variables de entorno y las expone como constantes.
"""
import os
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

# Cargar siempre el .env del directorio donde está config.py,
# independientemente del directorio de trabajo actual
_ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=True)
print(f"[config] .env cargado desde: {_ENV_PATH} (existe: {_ENV_PATH.exists()})")

# --- Google Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")

# --- X (Twitter) ---
X_API_KEY = os.getenv("X_API_KEY", "")
X_API_SECRET = os.getenv("X_API_SECRET", "")
X_ACCESS_TOKEN = os.getenv("X_ACCESS_TOKEN", "")
X_ACCESS_SECRET = os.getenv("X_ACCESS_SECRET", "")

# --- Umbrales de negocio ---
VALUE_THRESHOLD = 0.04          # EV mínimo para considerar value bet (4%)
MIN_ODD = 1.50                  # Cuota mínima a jugar
MAX_ODD = 5.00                  # Cuota máxima a jugar
STAKE_UNITS = 1                 # Unidades de stake por defecto

# --- Validación rápida al importar ---
def _warn_missing():
    required = {
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHANNEL_ID": TELEGRAM_CHANNEL_ID,
    }
    import logging
    for name, val in required.items():
        if not val:
            logging.warning("Variable de entorno no configurada: %s", name)

_warn_missing()
