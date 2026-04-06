"""
Genera una imagen estilo Bet365 para cada pick publicado.
Tamaño: 600x200px. Guardado en /tmp/pick_card.png.
"""
import logging
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

OUTPUT_PATH = "/tmp/pick_card.png"

# Paleta exacta del original Bet365
DARK_GREEN  = "#1a6b3c"   # nombre jugador
NEON_GREEN  = "#00e676"   # texto bottom izquierda
DARK_BG     = "#1c1c1e"   # fondo bottom izquierda
GRAY_BG     = "#7a7a7a"   # fondo bottom derecha
TEXT_GRAY   = "#8a8a8a"   # partido (P1 vs P2)
X_COLOR     = "#555555"   # símbolo ×
DIVIDER     = "#e0e0e0"   # línea separadora
WHITE       = "#ffffff"
BLACK       = "#111111"

W, H   = 600, 200
RADIUS = 10
TOP_H  = 128   # altura sección blanca


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """
    Helvetica Neue index 1 = Bold, index 0 = Regular.
    Coincide con la tipografía del diseño Bet365 en iOS.
    """
    hv = "/System/Library/Fonts/HelveticaNeue.ttc"
    try:
        return ImageFont.truetype(hv, size, index=1 if bold else 0)
    except (IOError, OSError):
        pass
    # Fallback Linux / otros sistemas
    fallback_bold    = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
    fallback_regular = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    for path in (fallback_bold if bold else fallback_regular):
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


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

    # ── Símbolo × (gris oscuro, plano, sin círculo) ──────────────────────────
    font_x = _load_font(22, bold=False)
    draw.text((22, 28), "×", font=font_x, fill=X_COLOR)

    # ── Nombre del jugador (verde oscuro, negrita) ───────────────────────────
    font_name = _load_font(24, bold=True)
    name_display = player if len(player) <= 24 else player[:22] + "…"
    draw.text((52, 24), name_display, font=font_name, fill=DARK_GREEN)

    # ── Cuota a la derecha (negro, negrita grande) ───────────────────────────
    font_odd = _load_font(26, bold=True)
    odd_str  = f"{odd:.2f}"
    bbox_odd = draw.textbbox((0, 0), odd_str, font=font_odd)
    odd_w    = bbox_odd[2] - bbox_odd[0]
    draw.text((W - 28 - odd_w, 26), odd_str, font=font_odd, fill=BLACK)

    # ── "To Win Match" (negro, negrita) ──────────────────────────────────────
    font_sub = _load_font(15, bold=True)
    draw.text((52, 60), "To Win Match", font=font_sub, fill=BLACK)

    # ── "Jugador1 vs Jugador2" (gris, regular) ───────────────────────────────
    font_match = _load_font(14)
    vs_text    = f"{player} vs {opponent}"
    if len(vs_text) > 50:
        vs_text = vs_text[:47] + "…"
    draw.text((52, 86), vs_text, font=font_match, fill=TEXT_GRAY)

    # ── Línea separadora horizontal ──────────────────────────────────────────
    draw.line([(0, TOP_H), (W, TOP_H)], fill=DIVIDER, width=1)

    # ── Bottom izquierda (negro oscuro) ──────────────────────────────────────
    draw.rectangle([0, TOP_H, W // 2 - 1, H], fill=DARK_BG)
    font_btn  = _load_font(22, bold=True)
    btn_label = "Set Stake"
    bbox_btn  = draw.textbbox((0, 0), btn_label, font=font_btn)
    btn_w = bbox_btn[2] - bbox_btn[0]
    btn_h = bbox_btn[3] - bbox_btn[1]
    bx = (W // 2 - btn_w) // 2
    by = TOP_H + ((H - TOP_H) - btn_h) // 2
    draw.text((bx, by), btn_label, font=font_btn, fill=NEON_GREEN)

    # ── Bottom derecha (gris) ─────────────────────────────────────────────────
    draw.rectangle([W // 2, TOP_H, W, H], fill=GRAY_BG)
    font_url  = _load_font(22, bold=True)
    url_label = "Place Bet"
    bbox_url  = draw.textbbox((0, 0), url_label, font=font_url)
    url_w = bbox_url[2] - bbox_url[0]
    url_h = bbox_url[3] - bbox_url[1]
    ux = W // 2 + (W // 2 - url_w) // 2
    uy = TOP_H + ((H - TOP_H) - url_h) // 2
    draw.text((ux, uy), url_label, font=font_url, fill=WHITE)

    # ── Máscara de esquinas redondeadas ──────────────────────────────────────
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=RADIUS, fill=255)
    img.putalpha(mask)

    # Componer sobre fondo blanco
    bg = Image.new("RGB", (W, H), WHITE)
    bg.paste(img, mask=img.split()[3])
    bg.save(OUTPUT_PATH, "PNG")

    logger.info("Imagen generada: %s @%.2f (%s) → %s", player, odd, tournament, OUTPUT_PATH)
    return OUTPUT_PATH
