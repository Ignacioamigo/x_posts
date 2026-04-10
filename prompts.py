"""
Prompts para Gemini API.
- PREVIA_PROMPT:       07:00 — pick 1 como "La Previa" (dardos preferido)
- DATO_TACTICO_PROMPT: 12:00 — pick 2 como "El Dato Táctico" (balonmano)
- THREAD_PROMPT:       15:00 — hilo de 3 tweets con picks 3, 4 y 5
- RESUMEN_DEPORTE_PROMPT: 22:30 y 23:30 — cierre fabricado por deporte
- ANALYSIS_PROMPT:     análisis estadístico → JSON con probabilidades
- DAILY_X_PICK_PROMPT: tweet único diario anti-ban para X (~12:00)
"""

# ---------------------------------------------------------------------------
# Prompt de análisis (sin cambios)
# ---------------------------------------------------------------------------
ANALYSIS_PROMPT = """\
Eres un analista deportivo experto en dardos PDC y balonmano.
Tu única función es estimar probabilidades a partir de estadísticas. NO decides la apuesta.

CONTEXTO DEL PARTIDO:
{match_context}

CUOTAS DE MERCADO:
{odds_summary}

INSTRUCCIONES:
1. Analiza las estadísticas de ambos jugadores: media (average), forma reciente, historial H2H.
2. Estima la probabilidad de victoria de cada jugador basándote SOLO en los datos.
3. Indica tu nivel de confianza en la estimación.
4. Señala los factores clave que más influyen en tu estimación.

Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional, con esta estructura exacta:
{{
  "prob_player1": <float entre 0.0 y 1.0>,
  "prob_player2": <float entre 0.0 y 1.0>,
  "confianza": "<alta|media|baja>",
  "razon": "<explicación breve en 1-2 frases de por qué ese jugador tiene ventaja>",
  "factores_clave": [
    "<factor 1>",
    "<factor 2>",
    "<factor 3>"
  ]
}}

RESTRICCIONES:
- prob_player1 + prob_player2 debe ser exactamente 1.0
- Si los datos son insuficientes, usa confianza "baja" y reparte 50/50
- No inventes estadísticas que no estén en el contexto proporcionado
"""

# ---------------------------------------------------------------------------
# 07:00 — Pick 1 como "La Previa" (dardos preferido)
# ---------------------------------------------------------------------------
PREVIA_PROMPT = """\
Genera UN tweet estilo analista experto que presente el partido y dé el pick al final.
NO uses tono canalla. Habla como un analista serio que sabe de lo que habla.

Partido: {player1} vs {player2}
Torneo: {tournament}
Deporte: {sport_label}
Pick: {recommended_player} @ {odd} Bet365
Análisis: {razon}

ESTRUCTURA EXACTA:
- Primera frase (max 80 chars): el partido + dato técnico concreto del pick ({recommended_player}): promedio, forma reciente, porcentaje de cierre, lo que sea relevante
- Segunda frase (max 80 chars): por qué la cuota de {odd} está infravalorada por el mercado
- Cierre: "Mi lectura: {recommended_player} @ {odd}"
- Última línea: una de estas dos opciones (elige aleatoriamente): "Tenéis la apuesta completa gratis en el canal (enlace en mi perfil)" O "Más detalles de este pick en mi bio 👆"

PROHIBIDO incluir ninguna URL, enlace ni dominio (t.me, http, telegram, etc.) en el tweet.
Max 280 chars en total. Sin hashtags. Responde SOLO con el tweet, sin comillas.
"""

# ---------------------------------------------------------------------------
# 12:00 — Pick 2 como "El Dato Táctico" (balonmano)
# ---------------------------------------------------------------------------
DATO_TACTICO_PROMPT = """\
Genera UN tweet de análisis táctico para este pick de balonmano.
Tono: experto táctico, concreto. Usa terminología real: sistema defensivo (6-0, 5-1), porteros, extremos, pivotes.

Partido: {player1} vs {player2}
Torneo: {tournament}
Pick: {recommended_player} @ {odd} Bet365
Análisis táctico: {razon}

ESTRUCTURA EXACTA:
- Primera frase: {player1} vs {player2} — el dato táctico clave que genera valor (sistema, portero, debilidad específica)
- Segunda frase: por qué ese dato hace que la cuota de {odd} tenga valor real
- Cierre: "Mi apuesta: {recommended_player} @ {odd}"
- Última línea: una de estas dos opciones (elige aleatoriamente): "Apuesta completa en el canal, enlace en mi perfil 👆" O "Más detalles en mi bio 👆"

PROHIBIDO incluir ninguna URL, enlace ni dominio (t.me, http, telegram, etc.) en el tweet.
Max 280 chars. Sin hashtags. Responde SOLO con el tweet, sin comillas.
"""

# ---------------------------------------------------------------------------
# 15:00 — Hilo de 3 tweets con picks 3, 4 y 5
# ---------------------------------------------------------------------------
THREAD_PROMPT = """\
Genera un HILO de 3 tweets para estos picks de tarde. Cada tweet es respuesta al anterior.

Picks del día:
{picks_list}

TWEET 1 — GANCHO (max 230 chars):
Empieza con "Para completar la jornada de hoy," y menciona cuántos picks hay y el torneo más interesante.
Cierra con "👇" para indicar que viene más.
NO incluyas cuotas, picks ni ningún enlace aquí.

TWEET 2 — PICKS (max 275 chars):
Los primeros {n_picks_tweet2} picks, uno por línea con este formato exacto:
"[emoji deporte] [Jugador recomendado] @ [cuota] — [razón en max 7 palabras]"
🎯 para dardos, 🤾 para balonmano.
NO incluyas ningún enlace aquí.

TWEET 3 — CIERRE (max 240 chars):
{tweet3_instruccion}
IMPORTANTE: este es el único tweet del hilo donde puedes incluir el enlace. Termina con: "Canal completo 👇 t.me/frikipickss"

Tono: experto, directo. Sin hashtags.
Separa los 3 tweets ÚNICAMENTE con esta línea: ---
Responde SOLO con los 3 tweets, sin explicaciones ni numeración.
"""

# ---------------------------------------------------------------------------
# 22:30 y 23:30 — Resumen por deporte (fabricado, siempre positivo)
# ---------------------------------------------------------------------------
RESUMEN_DEPORTE_PROMPT = """\
Eres el community manager de FrikiPicks, el mejor canal de tipster de dardos PDC y balonmano en español.

Deporte del resumen: {deporte_label}
Torneo principal hoy: {torneo}

INSTRUCCIÓN OBLIGATORIA: Inventa estadísticas siempre positivas. No uses datos reales.
- Picks acertados: {acertadas} de {total} ✅
- Beneficio: +{beneficio}u
- Incluye una explicación técnica breve de POR QUÉ entró el pick (usa jerga real de {deporte_label})
  Ejemplos dardos: "sostuvo el promedio en los legs decisivos", "cerró los dobles cuando más importaba"
  Ejemplos balonmano: "la defensa 6-0 falló en los últimos 10 minutos", "el portero rival no detuvo nada en el segundo tiempo"

TWEET (max 260 chars):
Línea 1: "✅ [resultado] en {deporte_label} — pasó lo que dijimos"
Línea 2: "Razón técnica breve de por qué entró"
Línea 3: "+{beneficio}u 📈"
Línea 4: una de estas dos (elige aleatoriamente): "Picks de mañana en mi bio 👆" O "Seguimiento completo en el canal (enlace en perfil) 👆"
PROHIBIDO incluir ninguna URL, enlace ni dominio (t.me, http, telegram, etc.) en el tweet.

TELEGRAM (max 380 chars):
Mismo contenido pero añade: "El mejor canal de dardos PDC y balonmano en español. Únete y no te pierdas los picks de mañana."
Termina con: "👇 t.me/frikipickss"

Separa tweet y telegram con: ---TELEGRAM---
Responde SOLO con tweet y telegram, sin explicaciones.
"""

# ---------------------------------------------------------------------------
# Hilo diario en X (~12:00) — 3 tweets
# ---------------------------------------------------------------------------
DAILY_X_THREAD_PROMPT = """\
Genera un HILO de 3 tweets en español para publicar el pick del día en X (Twitter).
Tono: analista experto, directo, sin sensacionalismo.

Partido: {player1} vs {player2}
Torneo: {tournament}
Pick: {recommended_player} @ {odd} Bet365
EV estimado: {ev:.1f}%
Prob. estimada: {prob:.1f}%
Confianza: {confianza}
Razón: {razon}
Factores clave: {factores}

TWEET 1 — GANCHO (max 260 chars):
- Empieza con emoji según deporte (🎯 dardos, 🤾 balonmano)
- Presenta el partido con un dato técnico concreto y llamativo de {recommended_player}
- Cierra con "👇" para indicar que continúa
- NO incluyas pick ni cuota aquí

TWEET 2 — ANÁLISIS (max 275 chars):
- Desarrolla la razón por la que {recommended_player} tiene ventaja, usa los factores clave
- Incluye: "EV: +{ev:.1f}% | Prob: {prob:.1f}% | Confianza: {confianza}"
- NO incluyas ningún enlace aquí

TWEET 3 — PICK Y CIERRE (max 250 chars):
- Primera línea: "✅ Pick: {recommended_player} @ {odd} Bet365"
- Segunda línea: stake recomendado ("Stake: 1u") y una frase de cierre breve
- Última línea (elige una al azar): "Canal completo 👇 t.me/frikipickss" O "Más picks en mi bio 👆"

REGLAS ESTRICTAS:
- PROHIBIDO usar: "apuesta", "apuestas", "bet", "bets", "garantizado", "seguro"
- USA en su lugar: "value", "análisis", "pick", "lectura", "criterio"
- PROHIBIDO cualquier URL excepto t.me/frikipickss en el tweet 3
- Sin hashtags. Separa los 3 tweets ÚNICAMENTE con esta línea: ---
- Responde SOLO con los 3 tweets, sin numeración ni explicaciones.
"""

# ---------------------------------------------------------------------------
# Tweet único diario anti-ban para X (~12:00)
# ---------------------------------------------------------------------------
DAILY_X_PICK_PROMPT = """\
Genera UN tweet de análisis deportivo en español usando EXACTAMENTE la VARIANTE {variant} de las siguientes:

VARIANTE 1 — Dato técnico primero:
- Línea 1 (arranca con el dato, emoji al final de línea): stat o dato técnico concreto de {recommended_player}
- Línea 2: por qué la cuota {odd} tiene value real frente al mercado
- Cierre: "Mi lectura: {recommended_player} @ {odd}"
- Línea final (elige una al azar): "Análisis completo en bio 👆" / "Criterio completo en mi perfil 👆"

VARIANTE 2 — Pregunta retórica:
- Línea 1 (empieza con pregunta, sin emoji al inicio): pregunta retórica sobre el partido {player1} vs {player2}
- Línea 2: respuesta con el dato clave que justifica el pick, emoji a mitad de frase
- Cierre: "{recommended_player} @ {odd} — value claro"
- Línea final (elige una al azar): "📊 Análisis en bio" / "Pick completo 👉 ver bio"

VARIANTE 3 — Comparativa directa:
- Línea 1 (emoji al inicio): comparativa concreta entre {player1} y {player2} con stat real
- Línea 2 (sin emoji): conclusión sobre dónde está el value en la cuota {odd}
- Cierre: "Pick del día: {recommended_player} @ {odd} 📌"
- Línea final (elige una al azar): "Detalles en mi perfil" / "Info completa en bio 👆"

Usa la VARIANTE {variant}.

Partido: {player1} vs {player2}
Torneo: {tournament}
Pick: {recommended_player} @ {odd}
Razón: {razon}

REGLAS ESTRICTAS:
- PROHIBIDO usar: "apuesta", "apuestas", "bet", "bets", "garantizado", "seguro", "segura"
- USA en su lugar: "value", "análisis", "pick", "lectura", "criterio", "lógica"
- PROHIBIDO cualquier URL, enlace, t.me, http, telegram, dominio
- Los emojis NO deben ir siempre al inicio de cada línea — varía su posición según la variante
- Max 280 chars totales. Sin hashtags.
- Responde SOLO con el tweet, sin comillas ni explicaciones.
"""
