"""
Base de datos SQLite para historial de picks y resúmenes diarios.
Permite calcular profit, racha y estadísticas del mes.
"""
import sqlite3
import logging
from datetime import datetime, date
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "historial.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Crea las tablas si no existen."""
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS picks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha            TEXT NOT NULL,
                sport            TEXT NOT NULL,
                player1          TEXT NOT NULL,
                player2          TEXT NOT NULL,
                pick_jugador     TEXT NOT NULL,
                cuota            REAL NOT NULL,
                ev_porcentaje    REAL NOT NULL,
                confianza        TEXT NOT NULL,
                resultado        TEXT,
                profit           REAL,
                publicado_telegram INTEGER DEFAULT 0,
                publicado_x        INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS resumen_diario (
                fecha                TEXT PRIMARY KEY,
                picks_totales        INTEGER DEFAULT 0,
                picks_win            INTEGER DEFAULT 0,
                picks_loss           INTEGER DEFAULT 0,
                profit_dia           REAL DEFAULT 0,
                profit_mes_acumulado REAL DEFAULT 0,
                racha_actual         INTEGER DEFAULT 0,
                texto_resumen        TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eventos_diarios (
                fecha  TEXT NOT NULL,
                evento TEXT NOT NULL,
                PRIMARY KEY (fecha, evento)
            )
        """)
        conn.commit()
    logger.info("Base de datos historial.db inicializada en %s", DB_PATH)


def save_pick(
    sport: str,
    player1: str,
    player2: str,
    pick_jugador: str,
    cuota: float,
    ev_porcentaje: float,
    confianza: str,
    publicado_telegram: bool = False,
    publicado_x: bool = False,
) -> int:
    """
    Guarda un pick publicado. Devuelve el id asignado.
    El resultado y profit quedan NULL hasta actualizarse manualmente.
    """
    fecha = date.today().isoformat()
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO picks
               (fecha, sport, player1, player2, pick_jugador, cuota,
                ev_porcentaje, confianza, publicado_telegram, publicado_x)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (fecha, sport, player1, player2, pick_jugador, cuota,
             ev_porcentaje, confianza,
             int(publicado_telegram), int(publicado_x)),
        )
        conn.commit()
        pick_id = cur.lastrowid
    logger.info("Pick guardado en historial: id=%d %s @%.2f", pick_id, pick_jugador, cuota)
    return pick_id


def update_resultado(pick_id: int, resultado: str, stake: float = 1.0):
    """
    Actualiza el resultado (WIN/LOSS) y calcula el profit de un pick.
    resultado: 'WIN' o 'LOSS'
    stake: unidades apostadas (default 1u)
    """
    with _conn() as conn:
        row = conn.execute("SELECT cuota FROM picks WHERE id=?", (pick_id,)).fetchone()
        if not row:
            logger.error("Pick id=%d no encontrado en historial", pick_id)
            return
        cuota = row["cuota"]
        profit = round((cuota - 1) * stake if resultado == "WIN" else -stake, 2)
        conn.execute(
            "UPDATE picks SET resultado=?, profit=? WHERE id=?",
            (resultado, profit, pick_id),
        )
        conn.commit()
    logger.info("Pick id=%d actualizado: %s | profit=%.2fu", pick_id, resultado, profit)


def get_picks_today() -> list[dict]:
    """Devuelve todos los picks del día de hoy."""
    fecha = date.today().isoformat()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM picks WHERE fecha=? ORDER BY id", (fecha,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_stats_month() -> dict:
    """Estadísticas del mes en curso."""
    mes = date.today().strftime("%Y-%m")
    with _conn() as conn:
        rows = conn.execute(
            "SELECT resultado, profit FROM picks WHERE fecha LIKE ? AND resultado IS NOT NULL",
            (f"{mes}%",),
        ).fetchall()

    picks_win  = sum(1 for r in rows if r["resultado"] == "WIN")
    picks_loss = sum(1 for r in rows if r["resultado"] == "LOSS")
    profit_mes = round(sum(r["profit"] for r in rows if r["profit"] is not None), 2)
    total      = len(rows)

    return {
        "total": total,
        "wins": picks_win,
        "losses": picks_loss,
        "profit_mes": profit_mes,
    }


def get_racha_actual() -> int:
    """
    Calcula la racha actual: número de picks WIN consecutivos al final.
    Negativo si la racha es de LOSS.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT resultado FROM picks WHERE resultado IS NOT NULL ORDER BY id DESC LIMIT 20"
        ).fetchall()

    if not rows:
        return 0

    first = rows[0]["resultado"]
    racha = 0
    for r in rows:
        if r["resultado"] == first:
            racha += 1
        else:
            break

    return racha if first == "WIN" else -racha


def ya_publicado_hoy(evento: str) -> bool:
    """Devuelve True si el evento (ej. 'preview', 'resumen') ya se marcó hoy."""
    fecha = date.today().isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM eventos_diarios WHERE fecha=? AND evento=?",
            (fecha, evento),
        ).fetchone()
    return row is not None


def marcar_publicado_hoy(evento: str):
    """Registra que el evento ya se ejecutó hoy (idempotente)."""
    fecha = date.today().isoformat()
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO eventos_diarios (fecha, evento) VALUES (?,?)",
            (fecha, evento),
        )
        conn.commit()
    logger.debug("Evento '%s' marcado como publicado para %s", evento, fecha)


def save_resumen_diario(
    picks_totales: int,
    picks_win: int,
    picks_loss: int,
    profit_dia: float,
    profit_mes: float,
    racha: int,
    texto: str,
):
    fecha = date.today().isoformat()
    with _conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO resumen_diario
               (fecha, picks_totales, picks_win, picks_loss,
                profit_dia, profit_mes_acumulado, racha_actual, texto_resumen)
               VALUES (?,?,?,?,?,?,?,?)""",
            (fecha, picks_totales, picks_win, picks_loss,
             profit_dia, profit_mes, racha, texto),
        )
        conn.commit()
