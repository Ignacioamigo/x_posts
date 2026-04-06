"""
Genera una imagen estilo Bet365 para cada pick publicado.
Tamaño: 600x200px. Guardado en /tmp/pick_card.png.
"""
import logging
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

OUTPUT_PATH = "/tmp/pick_card.png"

# Paleta de colores
BET365_GREEN = "#00a651"
DARK_GREEN   = "#1a6b3c"
NEON_GREEN   = "#00ff87"
DARK_BG      = "#1a1a2e"
GRAY_BG      = "#555555"
TEXT_GRAY    = "#888888"
DIVIDER      = "#dddddd"
WHITE        = "#ffffff"
BLACK        = "#111111"

W, H   = 600, 200
RADIUS = 15
TOP_H  = 135   # altura de la sección blanca superior


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Carga fuente del sistema con fallback a la fuente por defecto de PIL."""
    candidates_bold = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    candidates_regular = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in (candidates_bold if bold else candidates_regular):
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _draw_checkmark(draw: ImageDraw.ImageDraw, cx: int, cy: int):
    """Dibuja un ✓ manual dentro del círculo verde."""
    x0, y0 = cx - 9, cy + 1
    points = [
        (x0,      y0),
        (x0 + 6,  y0 + 7),
        (x0 + 16, y0 - 8),
    ]
    draw.line([points[0], points[1]], fill=WHITE, width=3)
    draw.line([points[1], points[2]], fill=WHITE, width=3)


def generate_bet365_card(
    player: str,
    opponent: str,
    odd: float,
    tournament: str = "",
) -> str:
    """
    Genera la tarjeta de pick estilo Bet365.
    Devuelve la ruta del PNG generado.
    """
    img  = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # ── Fondo blanco redondeado ──────────────────────────────────────────────
    draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=RADIUS, fill=WHITE)

    # ── Borde superior verde ─────────────────────────────────────────────────
    draw.rounded_rectangle([0, 0, W - 1, 5], radius=2, fill=BET365_GREEN)

    # ── Círculo verde con checkmark ──────────────────────────────────────────
    cx, cy = 47, TOP_H // 2
    r = 22
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BET365_GREEN)
    _draw_checkmark(draw, cx, cy)

    # ── Nombre del jugador ───────────────────────────────────────────────────
    font_name = _load_font(22, bold=True)
    # Truncar si es demasiado largo para que no se solape con la cuota
    name_display = player if len(player) <= 22 else player[:20] + "…"
    draw.text((82, 28), name_display, font=font_name, fill=DARK_GREEN)

    # ── "To Win Match" ───────────────────────────────────────────────────────
    font_sub = _load_font(13)
    draw.text((82, 58), "To Win Match", font=font_sub, fill=BLACK)

    # ── "Torneo · Jugador1 vs Jugador2" en gris ──────────────────────────────
    font_match = _load_font(12)
    vs_text = f"{player} vs {opponent}"
    match_line = f"{tournament}  ·  {vs_text}" if tournament else vs_text
    # Truncar si no cabe
    if len(match_line) > 55:
        match_line = match_line[:52] + "…"
    draw.text((82, 78), match_line, font=font_match, fill=TEXT_GRAY)

    # ── Cuota a la derecha ───────────────────────────────────────────────────
    font_odd = _load_font(34, bold=True)
    odd_str  = f"{odd:.2f}"
    bbox     = draw.textbbox((0, 0), odd_str, font=font_odd)
    odd_w    = bbox[2] - bbox[0]
    draw.text((W - 28 - odd_w, TOP_H // 2 - 22), odd_str, font=font_odd, fill=BLACK)

    # ── Línea separadora horizontal ──────────────────────────────────────────
    draw.line([(0, TOP_H), (W, TOP_H)], fill=DIVIDER, width=1)

    # ── Franja inferior izquierda (negro oscuro) ─────────────────────────────
    draw.rectangle([0, TOP_H, W // 2, H], fill=DARK_BG)
    font_btn = _load_font(14, bold=True)
    lbl_x = W // 4
    lbl_y = TOP_H + (H - TOP_H) // 2
    bbox_btn = draw.textbbox((0, 0), "Ver pick completo", font=font_btn)
    btn_w = bbox_btn[2] - bbox_btn[0]
    btn_h = bbox_btn[3] - bbox_btn[1]
    draw.text((lbl_x - btn_w // 2, lbl_y - btn_h // 2), "Ver pick completo",
              font=font_btn, fill=NEON_GREEN)

    # ── Franja inferior derecha (gris) ───────────────────────────────────────
    draw.rectangle([W // 2, TOP_H, W, H], fill=GRAY_BG)
    font_url = _load_font(13)
    url_text = "t.me/frikipickss"
    bbox_url = draw.textbbox((0, 0), url_text, font=font_url)
    url_w = bbox_url[2] - bbox_url[0]
    url_h = bbox_url[3] - bbox_url[1]
    url_x = W // 2 + (W // 4) - url_w // 2
    url_y = TOP_H + (H - TOP_H) // 2 - url_h // 2
    draw.text((url_x, url_y), url_text, font=font_url, fill=WHITE)

    # ── Separador vertical inferior ──────────────────────────────────────────
    draw.line([(W // 2, TOP_H), (W // 2, H)], fill="#333333", width=1)

    # ── Máscara de esquinas redondeadas ──────────────────────────────────────
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=RADIUS, fill=255)
    img.putalpha(mask)

    # Componer sobre fondo blanco y guardar
    bg = Image.new("RGB", (W, H), WHITE)
    bg.paste(img, mask=img.split()[3])
    bg.save(OUTPUT_PATH, "PNG")

    logger.info("Imagen generada: %s @%.2f (%s) → %s", player, odd, tournament, OUTPUT_PATH)
    return OUTPUT_PATH
