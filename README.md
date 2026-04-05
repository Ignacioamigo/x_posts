# Tipster Bot 🎯🏓

Sistema automatizado de tipster deportivo especializado en **Dardos PDC** y **Tenis de Mesa**.

Analiza estadísticas con Gemini (Google), detecta value bets comparando la probabilidad
estimada por el LLM contra la cuota implícita de Bet365, y publica automáticamente en
**Telegram** y **X (Twitter)**.

---

## Arquitectura del sistema

```
flashscore.com          dartsdata.co.uk
      │                 tabletennis.guide
      │                        │
      ▼                        ▼
 scraper.py            scraper.py
 (partidos)            (estadísticas)
      │                        │
      └──────────┬─────────────┘
                 │
           analyzer.py ◄── Gemini API (estimación de probabilidad)
                 │
           odds_scraper.py ◄── oddsportal.com (cuotas Bet365)
                 │
           detect_value() ◄── decisión matemática (EV > 4%)
                 │
           publisher.py
           ├── Telegram (mensaje formateado)
           └── X/Twitter (4 tweets con delay de 1h)
```

**Principio de diseño clave:** El LLM solo estima probabilidades. La decisión de apostar
la toma siempre `detect_value()` con criterios matemáticos transparentes.

---

## Requisitos previos

- Python 3.11+
- Cuenta en [Google AI Studio](https://aistudio.google.com/) (Gemini API)
- Bot de Telegram (ver setup abajo)
- Cuenta de desarrollador en X/Twitter (ver setup abajo)

---

## Instalación

```bash
# 1. Clonar / descargar el proyecto
cd tipster_bot/

# 2. Crear entorno virtual
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Edita .env con tus credenciales reales
```

---

## Setup: Bot de Telegram

1. Abre Telegram y busca **@BotFather**
2. Envía `/newbot` y sigue las instrucciones
3. Copia el **token** que te proporciona → `TELEGRAM_BOT_TOKEN`
4. Crea un canal de Telegram (público o privado)
5. Añade tu bot como **administrador** del canal con permiso para publicar mensajes
6. Para obtener el **Channel ID**:
   - Envía cualquier mensaje al canal
   - Visita: `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
   - Busca `"chat":{"id": -100XXXXXXXXXX}` → ese número es tu `TELEGRAM_CHANNEL_ID`

---

## Setup: X (Twitter) Developer Account

1. Ve a [developer.twitter.com](https://developer.twitter.com/en/portal/dashboard)
2. Crea un proyecto y una app
3. En la app, ve a **Settings** → cambia los permisos a **Read and Write**
4. Ve a **Keys and Tokens** y genera/copia:
   - `API Key` → `X_API_KEY`
   - `API Key Secret` → `X_API_SECRET`
   - `Access Token` → `X_ACCESS_TOKEN`
   - `Access Token Secret` → `X_ACCESS_SECRET`
5. Asegúrate de que los tokens tienen permisos de **escritura**

---

## Ejecución

```bash
# Activar entorno virtual (si no lo está)
source venv/bin/activate

# Ejecutar el bot
python scheduler.py
```

El bot:
1. Ejecuta el pipeline **una vez al arrancar** (prueba inmediata)
2. Repite automáticamente a las **11:00** y **20:00** cada día
3. Guarda logs en `tipster.log` y en consola

---

## Lógica de decisión (value bets)

```
EV = (prob_LLM × cuota_Bet365) - 1

Pick publicable si:
  ✅ EV > 4%  (umbral configurable en config.py → VALUE_THRESHOLD)
  ✅ Confianza del LLM: "alta" o "media"
```

Ejemplo:
- Gemini estima 60% de probabilidad de victoria para el Jugador A
- Bet365 ofrece cuota 2.00 (probabilidad implícita: 50%)
- EV = (0.60 × 2.00) - 1 = **+20%** → ✅ Value bet

---

## Estructura de archivos

```
tipster_bot/
├── config.py          # Variables de entorno y umbrales
├── scraper.py         # Partidos y estadísticas (flashscore, dartsdata, tt.guide)
├── odds_scraper.py    # Cuotas de oddsportal + lógica de value
├── prompts.py         # Prompts para Gemini (análisis y tweets)
├── analyzer.py        # Integración con Gemini API
├── publisher.py       # Publicación en Telegram y X
├── scheduler.py       # Punto de entrada + scheduler
├── requirements.txt
├── .env.example
├── .env               # ⚠️ NO subir a git
└── tipster.log        # Generado en ejecución
```

---

## Configuración avanzada

Edita `config.py` para ajustar:

| Variable | Default | Descripción |
|----------|---------|-------------|
| `VALUE_THRESHOLD` | `0.04` | EV mínimo para publicar (4%) |
| `MIN_ODD` | `1.50` | Cuota mínima aceptable |
| `MAX_ODD` | `5.00` | Cuota máxima aceptable |
| `STAKE_UNITS` | `1` | Unidades de stake en los mensajes |

---

## Notas sobre el scraping

- Se usan **delays aleatorios** de 2-5 segundos entre requests para no ser bloqueado
- Flashscore carga datos principalmente vía JavaScript; en entornos con bloqueo severo
  puede ser necesario usar Selenium/Playwright en lugar de requests+BeautifulSoup
- Si ves muchos warnings de "No se encontraron partidos", considera añadir cookies
  de sesión reales en los headers de `scraper.py`

---

## Aviso legal

Este bot es una herramienta de análisis estadístico. Las apuestas deportivas conllevan
riesgo de pérdida económica. Apuesta solo lo que puedas permitirte perder.
