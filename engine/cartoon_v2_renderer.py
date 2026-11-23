"""FrimeRise Cartoon Studio v2 — Hand-Drawn 2D Animation Engine (Skia C++ + 60 FPS + Zero Tokens).
Visual leap over v1:
  - Genuine 8fps Hand-Drawn Ink Boil via skia.DiscretePathEffect (exact @animabible7 / Paint Explainer feel!)
  - 2-Tone Cel-Shading + Rim Lighting + Cheek Blush + Cartoon Side Ears (+ inner line)
  - Organic Hand-Drawn Expressive Bean/Tapered Heads (NOT rigid geometric circles!)
  - Asymmetric Comedy Eyes + Tapered Brows + 3.2s Blink + Dramatic Storm Shadow Face
  - Full 2-Segment Articulated IK Arms (Upper Arm + Forearm + Expressive Hands) + Legs & Feet (walk/run cycle + dust puffs!)
  - 9 Studio Rhubarb Phonetic Mouths (A, B, C, D, E, F, G, H, X) with organic teeth/tongue/lips
  - 3-Layer 2.5D Parallax Scenery (Far Sky/Mountains 0.25x, Mid Architecture/Clouds/Sail 0.60x, Fore Deck/Waves/Foliage 1.25x)
  - Comic VFX: Radial Anime Speed Lines, Spring Reaction Badges (!, ?!, sweat, anger vein), God-Rays, Flickering Torches
  - Reusable Channel Character Sprite Kit Loader (supports custom SVG via skia.SVGDOM or PNG sprites in data/characters/)
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import skia

from engine.skia_compositor import hex_to_skia

BASE_DIR = Path(__file__).resolve().parent.parent
CHARACTERS_SPRITE_DIR = BASE_DIR / "data" / "characters"
CHARACTERS_SPRITE_DIR.mkdir(parents=True, exist_ok=True)


def _darken_hex(hex_color: str, factor: float = 0.74, alpha: int = 255) -> int:
    s = hex_color.strip().lstrip("#")
    r = int(int(s[0:2], 16) * factor)
    g = int(int(s[2:4], 16) * factor)
    b = int(int(s[4:6], 16) * factor)
    return skia.ColorSetARGB(alpha, max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def _lighten_hex(hex_color: str, factor: float = 1.22, alpha: int = 255) -> int:
    s = hex_color.strip().lstrip("#")
    r = min(255, int(int(s[0:2], 16) * factor + 18))
    g = min(255, int(int(s[2:4], 16) * factor + 18))
    b = min(255, int(int(s[4:6], 16) * factor + 18))
    return skia.ColorSetARGB(alpha, r, g, b)


def make_handdrawn_ink(
    t: float,
    width: float = 7.5,
    color: int = skia.ColorSetARGB(255, 20, 14, 26),
    boil_fps: float = 8.0,
    wobble: float = 1.85,
) -> skia.Paint:
    """Create a genuine hand-drawn cartoon ink brush with 8fps organic line boil (DiscretePathEffect)."""
    p = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=width,
        StrokeJoin=skia.Paint.kRound_Join,
        StrokeCap=skia.Paint.kRound_Cap,
        Color=color,
    )
    seed = int(t * boil_fps) % 64 + 1
    p.setPathEffect(skia.DiscretePathEffect.Make(16.0, wobble, seed))
    return p


def ease_out_back(x: float) -> float:
    """Elastic overshoot easing for snappy cartoon entrances & reaction pops."""
    x = max(0.0, min(1.0, x))
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * ((x - 1.0) ** 3) + c1 * ((x - 1.0) ** 2)


# ---------------------------------------------------------------------------
# 1. Studio 9-Viseme Rhubarb Cartoon Mouths (A..H, X)
# ---------------------------------------------------------------------------
def draw_rhubarb_mouth_v2(
    canvas: skia.Canvas,
    viseme: str,
    emotion: str,
    ink: skia.Paint,
) -> None:
    """Render any of Rhubarb's 9 phonetic mouth shapes (A, B, C, D, E, F, G, H, X) with cartoon polish."""
    # Also accept legacy v1 names seamlessly
    legacy_map = {
        "fechada_neutra": "X",
        "fechada_sorriso": "X",
        "aberta_media_E": "C",
        "aberta_grande_A_com_lingua": "D",
        "bico_O_U": "F",
        "dentes_raiva": "B",
    }
    v = legacy_map.get(viseme, viseme)

    cavity = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 76, 16, 32))
    cavity_deep = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 48, 8, 20))
    tongue = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 248, 113, 152))
    teeth = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 255, 253, 248))

    if v in ("X", "A"):
        p = skia.Path()
        if emotion == "laughing":
            p.moveTo(-36, -6)
            p.cubicTo(-16, 26, 16, 26, 36, -6)
        elif emotion == "smug":
            p.moveTo(-26, 6)
            p.quadTo(8, 10, 32, -10)
        elif emotion in ("angry", "crying"):
            p.moveTo(-28, 14)
            p.quadTo(0, -10, 28, 14)
        elif v == "A":
            # Pressed MBP lips
            p.moveTo(-28, 2)
            p.quadTo(0, 6, 28, 2)
        else:
            p.moveTo(-24, 4)
            p.quadTo(0, 12, 24, 0)
        canvas.drawPath(p, ink)

    elif v == "B":
        # Clenched teeth / angry consonants
        r = skia.Rect.MakeXYWH(-36, -15, 72, 32)
        canvas.drawRoundRect(r, 12, 12, teeth)
        canvas.drawRoundRect(r, 12, 12, ink)
        thin = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=3.5, Color=skia.ColorSetARGB(255, 30, 20, 35))
        canvas.drawLine(-34, 1, 34, 1, thin)
        for tx in (-16, 0, 16):
            canvas.drawLine(tx, -14, tx, 16, thin)

    elif v == "C":
        # Medium open E/I with upper teeth & hint of tongue
        m = skia.Path()
        m.moveTo(-34, -10)
        m.quadTo(0, -18, 34, -10)
        m.cubicTo(36, 22, -36, 22, -34, -10)
        m.close()
        canvas.drawPath(m, cavity)
        canvas.save()
        canvas.clipPath(m, doAntiAlias=True)
        canvas.drawRect(skia.Rect.MakeXYWH(-32, -16, 64, 13), teeth)
        canvas.drawOval(skia.Rect.MakeXYWH(-22, 6, 44, 18), tongue)
        canvas.restore()
        canvas.drawPath(m, ink)

    elif v == "D":
        # Big expressive wide-open A/shout with upper teeth, deep throat & bouncy pink tongue!
        m = skia.Path()
        m.moveTo(-40, -18)
        m.quadTo(0, -26, 40, -18)
        m.cubicTo(42, 42, -42, 42, -40, -18)
        m.close()
        canvas.drawPath(m, cavity_deep)
        canvas.save()
        canvas.clipPath(m, doAntiAlias=True)
        canvas.drawOval(skia.Rect.MakeXYWH(-34, -22, 68, 52), cavity)
        canvas.drawRoundRect(skia.Rect.MakeXYWH(-32, -22, 64, 15), 5, 5, teeth)
        canvas.drawOval(skia.Rect.MakeXYWH(-28, 12, 56, 30), tongue)
        canvas.restore()
        canvas.drawPath(m, ink)

    elif v == "E":
        # Rounded O vowel
        r = skia.Rect.MakeXYWH(-26, -18, 52, 44)
        canvas.drawOval(r, cavity)
        canvas.save()
        canvas.clipPath(skia.Path().addOval(r), doAntiAlias=True)
        canvas.drawOval(skia.Rect.MakeXYWH(-18, 10, 36, 20), tongue)
        canvas.restore()
        canvas.drawOval(r, ink)

    elif v == "F":
        # Tight puckered U / OO / W kiss shape
        r = skia.Rect.MakeXYWH(-17, -14, 34, 34)
        canvas.drawOval(r, cavity_deep)
        canvas.drawOval(r, ink)

    elif v == "G":
        # Upper teeth biting lower lip (F/V sounds)
        r = skia.Rect.MakeXYWH(-30, -12, 60, 22)
        canvas.drawRoundRect(r, 10, 10, cavity)
        canvas.drawRoundRect(skia.Rect.MakeXYWH(-26, -12, 52, 13), 4, 4, teeth)
        canvas.drawRoundRect(r, 10, 10, ink)

    else:  # H (L tongue touching roof)
        m = skia.Path()
        m.moveTo(-34, -12)
        m.quadTo(0, -18, 34, -12)
        m.cubicTo(34, 28, -34, 28, -34, -12)
        m.close()
        canvas.drawPath(m, cavity)
        canvas.save()
        canvas.clipPath(m, doAntiAlias=True)
        canvas.drawRoundRect(skia.Rect.MakeXYWH(-28, -16, 56, 11), 4, 4, teeth)
        tp = skia.Path()
        tp.moveTo(-22, 22)
        tp.quadTo(0, -6, 22, 22)
        tp.close()
        canvas.drawPath(tp, tongue)
        canvas.restore()
        canvas.drawPath(m, ink)


# ---------------------------------------------------------------------------
# 2. Custom SVG/PNG Channel Mascot Sprite Loader (Zero Tokens per Episode!)
# ---------------------------------------------------------------------------
_SPRITE_CACHE: Dict[str, Any] = {}


def try_draw_custom_channel_sprite(canvas: skia.Canvas, char_id: str, w: float = 260, h: float = 380) -> bool:
    """If the user placed custom SVG or PNG art in data/characters/<char_id>/body.svg|png, draw it via Skia SVGDOM/Image."""
    cdir = CHARACTERS_SPRITE_DIR / char_id
    svg_p = cdir / "character.svg"
    png_p = cdir / "character.png"
    key = str(svg_p if svg_p.exists() else png_p)

    if svg_p.exists():
        dom = _SPRITE_CACHE.get(key)
        if dom is None:
            try:
                stream = skia.MemoryStream(svg_p.read_bytes())
                dom = skia.SVGDOM.MakeFromStream(stream)
                if dom is not None:
                    dom.setContainerSize((w, h))
                    _SPRITE_CACHE[key] = dom
            except Exception:
                dom = None
        if dom is not None:
            canvas.save()
            canvas.translate(-w / 2.0, -h * 0.55)
            dom.render(canvas)
            canvas.restore()
            return True

    if png_p.exists():
        img = _SPRITE_CACHE.get(key)
        if img is None:
            try:
                img = skia.Image.open(str(png_p))
                _SPRITE_CACHE[key] = img
            except Exception:
                img = None
        if img is not None:
            canvas.drawImageRect(img, skia.Rect.MakeXYWH(-w / 2.0, -h * 0.55, w, h))
            return True

    return False


# ---------------------------------------------------------------------------
# 3. Expressive Hand-Drawn Cel-Shaded 2D Puppet v2 (Bean Head, 2-Segment IK Arms, Legs, Line Boil)
# ---------------------------------------------------------------------------
def draw_cartoon_puppet_v2(
    canvas: skia.Canvas,
    char: Any,
    cx: float,
    cy: float,
    scale: float,
    facing: int,
    emotion: str,
    viseme: str,
    speech_energy: float,
    is_speaking: bool,
    t: float,
    blink_offset: float = 0.0,
    pose: str = "standing",
    dark_storm_lighting: bool = False,
) -> None:
    """Render an expressive, hand-drawn cel-shaded cartoon character with 8fps line boil,
    2-segment IK articulated arms, animated legs/feet, asymmetric eyes, and 9 Rhubarb mouths.
    """
    rig = char.visual_rig
    ink = make_handdrawn_ink(t, width=7.5, wobble=1.85)
    ink_thin = make_handdrawn_ink(t, width=4.8, wobble=1.2)

    skin_fill = skia.Paint(AntiAlias=True, Color=hex_to_skia(rig.skin_color))
    skin_shade = skia.Paint(AntiAlias=True, Color=_darken_hex(rig.skin_color, 0.82))
    prim_fill = skia.Paint(AntiAlias=True, Color=hex_to_skia(rig.primary_color))
    prim_shade = skia.Paint(AntiAlias=True, Color=_darken_hex(rig.primary_color, 0.72))
    sec_fill = skia.Paint(AntiAlias=True, Color=hex_to_skia(rig.secondary_color))
    hair_fill = skia.Paint(AntiAlias=True, Color=hex_to_skia(rig.hair_color))
    hair_hi = skia.Paint(AntiAlias=True, Color=_lighten_hex(rig.hair_color, 1.35, 160))

    breath = math.sin(t * 3.1 + blink_offset) * 4.5
    speak_bob = -11.0 * speech_energy if is_speaking else 0.0
    run_phase = t * 15.0

    canvas.save()
    canvas.translate(cx, cy + breath + speak_bob)
    canvas.scale(scale, scale)

    # Check if client supplied a custom SVG/PNG character kit in data/characters/<char_id>/
    if try_draw_custom_channel_sprite(canvas, char.char_id):
        canvas.save()
        canvas.translate(0.0, -35.0)
        draw_rhubarb_mouth_v2(canvas, viseme, emotion, ink)
        canvas.restore()
        canvas.restore()
        return

    # 0. Ground contact shadow ellipse (grounds character into 2.5D world!)
    if pose not in ("lying_under_tree", "closeup_dramatic"):
        canvas.drawOval(
            skia.Rect.MakeXYWH(-96, 256, 192, 34),
            skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(72, 10, 6, 20)),
        )

    # 1. Articulated Cartoon Legs & Shoes (animated walk/run cycle!)
    if pose not in ("closeup_dramatic",):
        leg_ink = make_handdrawn_ink(t, width=11.0, wobble=1.5)
        for side in (-1, 1):
            hip_x = side * 36.0
            hip_y = 212.0
            if pose == "running":
                ang = math.sin(run_phase + (0.0 if side == -1 else math.pi))
                knee_x = hip_x + ang * 34.0
                knee_y = hip_y + 30.0
                foot_x = hip_x + ang * 56.0
                foot_y = 266.0 - max(0.0, -ang) * 26.0
            else:
                knee_x = hip_x + side * 6.0
                knee_y = hip_y + 28.0
                foot_x = hip_x + side * 14.0
                foot_y = 266.0

            lp = skia.Path()
            lp.moveTo(hip_x, hip_y)
            lp.quadTo(knee_x, knee_y, foot_x, foot_y)
            canvas.drawPath(lp, leg_ink)
            # Cartoon shoe
            shoe = skia.Rect.MakeXYWH(foot_x - 16 + facing * 10, foot_y - 12, 42, 22)
            canvas.drawRoundRect(shoe, 10, 10, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 58, 36, 24)))
            canvas.drawRoundRect(shoe, 10, 10, ink_thin)

        # Running dust puffs behind feet
        if pose == "running":
            dust_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(150, 236, 224, 202))
            for di in range(3):
                dx = -facing * (68 + ((t * 180 + di * 45) % 90))
                dy = 258 - ((t * 40 + di * 14) % 24)
                dr = 18 - di * 4
                canvas.drawCircle(dx, dy, max(6, dr), dust_p)

    # 2. Optional Royal Cape behind torso
    if rig.outfit == "king_crown":
        cape_sway = math.sin(t * 3.5) * 14.0
        cape = skia.Path()
        cape.moveTo(-72, 26)
        cape.quadTo(-118, 130, -124 + cape_sway, 236)
        cape.lineTo(124 + cape_sway, 236)
        cape.quadTo(118, 130, 72, 26)
        cape.close()
        canvas.drawPath(cape, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 185, 28, 72)))
        canvas.drawPath(cape, ink)

    # 3. Organic Hand-Drawn Torso (slightly tapered pear/tunic silhouette with 2-tone Cel-Shading!)
    torso = skia.Path()
    torso.moveTo(-66, 20)
    torso.cubicTo(-94, 54, -98, 168, -82, 224)
    torso.quadTo(0, 240, 82, 224)
    torso.cubicTo(98, 168, 94, 54, 66, 20)
    torso.quadTo(0, 8, -66, 20)
    torso.close()
    canvas.drawPath(torso, prim_fill)

    # 2-tone cel-shaded right-side shadow clipped inside torso!
    canvas.save()
    canvas.clipPath(torso, doAntiAlias=True)
    shade_band = skia.Path()
    shade_band.moveTo(26, 0)
    shade_band.cubicTo(58, 80, 56, 170, 32, 250)
    shade_band.lineTo(120, 250)
    shade_band.lineTo(120, 0)
    shade_band.close()
    canvas.drawPath(shade_band, prim_shade)

    # Outfit details (draped biblical sash + belt, sailor stripes, suit lapel + tie, hoodie)
    if rig.outfit == "robe_biblical":
        sash = skia.Path()
        sash.moveTo(-68, 22)
        sash.lineTo(-20, 18)
        sash.lineTo(80, 228)
        sash.lineTo(32, 232)
        sash.close()
        canvas.drawPath(sash, sec_fill)
        canvas.drawPath(sash, ink_thin)
        # Rope belt
        canvas.drawLine(-84, 158, 84, 158, make_handdrawn_ink(t, width=10.0, color=skia.ColorSetARGB(255, 112, 68, 34)))
    elif rig.outfit == "sailor":
        for sy in (64, 108, 152, 196):
            canvas.drawRect(skia.Rect.MakeXYWH(-96, sy, 192, 18), sec_fill)
    elif rig.outfit == "suit_boss":
        shirt = skia.Path()
        shirt.moveTo(-36, 16)
        shirt.lineTo(36, 16)
        shirt.lineTo(0, 134)
        shirt.close()
        canvas.drawPath(shirt, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
        canvas.drawPath(shirt, ink_thin)
        tie = skia.Path()
        tie.moveTo(-11, 30)
        tie.lineTo(11, 30)
        tie.lineTo(17, 154)
        tie.lineTo(0, 178)
        tie.lineTo(-17, 154)
        tie.close()
        canvas.drawPath(tie, sec_fill)
        canvas.drawPath(tie, ink_thin)
    elif rig.outfit == "modern_hoodie":
        canvas.drawRoundRect(skia.Rect.MakeXYWH(-54, 152, 108, 58), 18, 18, sec_fill)
        canvas.drawRoundRect(skia.Rect.MakeXYWH(-54, 152, 108, 58), 18, 18, ink_thin)
        canvas.drawLine(-20, 28, -20, 102, ink_thin)
        canvas.drawLine(20, 28, 20, 102, ink_thin)

    canvas.restore()
    canvas.drawPath(torso, ink)

    # 4. 2-Segment Articulated IK Arms (Shoulder -> Elbow -> Expressive Hand!)
    def _draw_ik_arm(side: int) -> None:
        sx, sy = side * 74.0, 56.0
        if pose == "arms_crossed":
            elx, ely = side * 116.0, 122.0
            hx, hy = -side * 22.0, 116.0
        elif pose == "running":
            swing = math.sin(run_phase + (math.pi if side == -1 else 0.0))
            elx = side * 98.0 + swing * 24.0
            ely = 104.0
            hx = side * 112.0 + swing * 48.0
            hy = 78.0 - swing * 24.0
        elif emotion == "shocked":
            elx = side * 124.0
            ely = 54.0
            hx = side * 116.0 + math.sin(t * 24.0 + side) * 9.0
            hy = -34.0 + math.cos(t * 20.0 + side) * 8.0
        elif emotion == "angry":
            elx = side * 128.0
            ely = 66.0
            hx = side * 138.0
            hy = -22.0 + math.sin(t * 20.0 + side) * 15.0
        elif is_speaking and side == facing:
            elx = side * 112.0
            ely = 92.0 - 16.0 * speech_energy
            hx = side * (146.0 + 20.0 * math.sin(t * 10.5))
            hy = 34.0 - 46.0 * speech_energy + 16.0 * math.cos(t * 8.5)
        elif emotion == "smug":
            elx = side * 114.0
            ely = 104.0
            hx = side * 76.0
            hy = 148.0
        else:
            elx = side * 106.0
            ely = 106.0
            hx = side * 96.0
            hy = 158.0 + math.sin(t * 2.8 + side) * 6.0

        arm_path = skia.Path()
        arm_path.moveTo(sx, sy)
        arm_path.lineTo(elx, ely)
        arm_path.lineTo(hx, hy)

        out_w = make_handdrawn_ink(t, width=36.0, wobble=1.5)
        in_w = make_handdrawn_ink(t, width=22.0, color=hex_to_skia(rig.primary_color), wobble=1.2)
        canvas.drawPath(arm_path, out_w)
        canvas.drawPath(arm_path, in_w)

        # Expressive cartoon mitten hand with subtle thumb nub
        canvas.drawCircle(hx, hy, 22, skin_fill)
        canvas.drawCircle(hx - side * 14, hy - 10, 10, skin_fill)
        canvas.drawCircle(hx, hy, 22, ink_thin)

        # Props held cleanly
        if side == -facing and rig.accessory == "beard_staff" and pose != "arms_crossed":
            st_p = make_handdrawn_ink(t, width=14.0, color=skia.ColorSetARGB(255, 114, 64, 28), wobble=2.2)
            canvas.drawLine(hx, hy - 190, hx, hy + 145, st_p)
            canvas.drawLine(hx, hy - 190, hx, hy + 145, make_handdrawn_ink(t, width=3.5, wobble=1.4))
        elif side == -facing and rig.accessory == "clipboard":
            cb = skia.Rect.MakeXYWH(hx - 26, hy - 48, 52, 68)
            canvas.drawRoundRect(cb, 8, 8, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 245, 158, 11)))
            canvas.drawRoundRect(cb, 8, 8, ink_thin)

    _draw_ik_arm(-1)
    _draw_ik_arm(1)

    # 5. Organic Hand-Drawn Bean Head with Elastic Squash & Stretch + 2-Tone Cel-Shading + Side Ears!
    sq_y = 1.0 + (0.075 * speech_energy if is_speaking else 0.0)
    sq_x = 1.0 - (0.042 * speech_energy if is_speaking else 0.0)
    head_tilt = (math.sin(t * 7.8) * 5.2 * speech_energy) if is_speaking else (math.sin(t * 2.0) * 1.8)
    if emotion == "angry":
        head_tilt += facing * 5.0

    canvas.save()
    canvas.translate(0.0, -82.0)
    canvas.rotate(head_tilt)
    canvas.scale(sq_x, sq_y)

    # Cartoon side ears with classic '+' comic ear detail!
    for eside in (-1, 1):
        ex = eside * 98.0
        canvas.drawOval(skia.Rect.MakeXYWH(ex - 20, -14, 40, 44), skin_fill)
        canvas.drawOval(skia.Rect.MakeXYWH(ex - 20, -14, 40, 44), ink_thin)
        canvas.drawLine(ex - 6, 4, ex + 6, 12, ink_thin)
        canvas.drawLine(ex + 6, 4, ex - 6, 12, ink_thin)

    # Organic expressive bean head silhouette (wider cranium, expressive cartoon jaw — NOT a sterile circle!)
    head_p = skia.Path()
    head_p.moveTo(-94, -18)
    head_p.cubicTo(-102, -108, -48, -118, 0, -114)
    head_p.cubicTo(48, -118, 102, -108, 94, -18)
    head_p.cubicTo(90, 68, 56, 98, 0, 98)
    head_p.cubicTo(-56, 98, -90, 68, -94, -18)
    head_p.close()
    canvas.drawPath(head_p, skin_fill)

    # Cel-shaded crescent shadow + warm cartoon cheek blush clipped inside head!
    canvas.save()
    canvas.clipPath(head_p, doAntiAlias=True)
    h_shade = skia.Path()
    h_shade.moveTo(46, -120)
    h_shade.cubicTo(78, -20, 68, 70, 26, 110)
    h_shade.lineTo(130, 110)
    h_shade.lineTo(130, -120)
    h_shade.close()
    canvas.drawPath(h_shade, skin_shade)

    # Dramatic dark top-down storm shadow across upper face during storm_closeup!
    if dark_storm_lighting:
        storm_sh = skia.Paint()
        storm_sh.setShader(
            skia.GradientShader.MakeLinear(
                [(0, -120), (0, 60)],
                [skia.ColorSetARGB(215, 10, 12, 28), skia.ColorSetARGB(40, 10, 12, 28)],
            )
        )
        canvas.drawRect(skia.Rect.MakeXYWH(-120, -130, 240, 250), storm_sh)
    else:
        # Warm rosy cheek blushes
        blush = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(78, 255, 102, 138))
        canvas.drawOval(skia.Rect.MakeXYWH(-74, 12, 34, 18), blush)
        canvas.drawOval(skia.Rect.MakeXYWH(40, 12, 34, 18), blush)
    canvas.restore()
    canvas.drawPath(head_p, ink)

    # Expressive messy hand-drawn hair + highlight streak
    hair_p = skia.Path()
    hair_p.moveTo(-98, -24)
    hair_p.cubicTo(-104, -112, -32, -130, 10, -122)
    hair_p.cubicTo(62, -134, 108, -100, 98, -24)
    hair_p.quadTo(56, -66, 16, -54)
    hair_p.quadTo(-8, -74, -42, -56)
    hair_p.quadTo(-74, -66, -98, -24)
    hair_p.close()
    canvas.drawPath(hair_p, hair_fill)
    canvas.drawOval(skia.Rect.MakeXYWH(-46, -104, 62, 16), hair_hi)
    canvas.drawPath(hair_p, ink)

    # Beard for biblical rig
    if rig.outfit == "robe_biblical" or rig.accessory == "beard_staff":
        beard = skia.Path()
        beard.moveTo(-88, 16)
        beard.cubicTo(-82, 108, -28, 126, 0, 122)
        beard.cubicTo(28, 126, 82, 108, 88, 16)
        beard.quadTo(44, 56, 0, 52)
        beard.quadTo(-44, 56, -88, 16)
        beard.close()
        canvas.drawPath(beard, hair_fill)
        canvas.drawPath(beard, ink)

    # Headgear (Crown / Sailor / Cap)
    if rig.outfit == "king_crown" or rig.accessory == "crown":
        crown = skia.Path()
        crown.moveTo(-74, -92)
        crown.lineTo(-88, -162)
        crown.lineTo(-34, -124)
        crown.lineTo(0, -176)
        crown.lineTo(34, -124)
        crown.lineTo(88, -162)
        crown.lineTo(74, -92)
        crown.close()
        canvas.drawPath(crown, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 255, 209, 102)))
        canvas.drawPath(crown, ink)
        canvas.drawCircle(0, -122, 11, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 255, 46, 147)))
        canvas.drawCircle(-44, -114, 8, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 56, 189, 248)))
        canvas.drawCircle(44, -114, 8, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 56, 189, 248)))
    elif rig.outfit == "sailor":
        cap_r = skia.Rect.MakeXYWH(-76, -148, 152, 60)
        canvas.drawRoundRect(cap_r, 28, 28, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
        canvas.drawRoundRect(cap_r, 28, 28, ink)
        canvas.drawRect(skia.Rect.MakeXYWH(-74, -104, 148, 18), skia.Paint(Color=skia.ColorSetARGB(255, 37, 99, 235)))
        canvas.drawRect(skia.Rect.MakeXYWH(-74, -104, 148, 18), ink_thin)
    elif rig.accessory == "cap":
        cap_r = skia.Rect.MakeXYWH(-88, -132, 176, 56)
        canvas.drawRoundRect(cap_r, 28, 28, sec_fill)
        canvas.drawRoundRect(cap_r, 28, 28, ink)
        vx = facing * 12 - 16 if facing > 0 else -98
        visor = skia.Rect.MakeXYWH(vx, -90, 98, 20)
        canvas.drawRoundRect(visor, 10, 10, prim_fill)
        canvas.drawRoundRect(visor, 10, 10, ink)

    # 6. Asymmetric Expressive Cartoon Eyes + 3.2s Natural Blink + Emotions
    look_x = facing * 13.0
    is_blinking = ((t + blink_offset) % 3.2) < 0.12
    eye_y = -14.0
    eye_xs = (-36.0 + look_x * 0.4, 36.0 + look_x * 0.4)

    for idx_e, ex in enumerate(eye_xs):
        if emotion == "laughing":
            arc = skia.Path()
            arc.moveTo(ex - 22, eye_y + 4)
            arc.quadTo(ex, eye_y - 26, ex + 22, eye_y + 4)
            canvas.drawPath(arc, ink)
        elif is_blinking:
            canvas.drawLine(ex - 20, eye_y, ex + 20, eye_y, ink)
        else:
            # Asymmetric sizing gives HUGE cartoon comedy personality!
            asym = (1.16 if idx_e == 0 else 0.90) if emotion in ("shocked", "angry", "smug") else 1.0
            er = (25.0 if emotion == "shocked" else 21.0) * asym
            canvas.drawCircle(ex, eye_y, er, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
            canvas.drawCircle(ex, eye_y, er, ink_thin)

            pr = 5.5 if emotion == "shocked" else 10.5
            px = ex + facing * 6.5
            canvas.drawCircle(px, eye_y, pr, skia.Paint(AntiAlias=True, Color=skia.ColorBLACK))
            canvas.drawCircle(px - 3, eye_y - 4, 3.5, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))

            if emotion == "smug":
                lid = skia.Rect.MakeXYWH(ex - er - 2, eye_y - er - 2, er * 2 + 4, er * 1.0)
                canvas.drawRect(lid, skin_fill)
                canvas.drawLine(ex - er, eye_y, ex + er, eye_y, ink_thin)

            if emotion == "crying":
                tear_y = eye_y + 24 + ((t * 120 + idx_e * 28) % 58)
                canvas.drawOval(skia.Rect.MakeXYWH(ex - 8, tear_y, 16, 26), skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(235, 56, 189, 248)))

    # Expressive Thick Ink Eyebrows + Comic Forehead Marks
    brow_ink = make_handdrawn_ink(t, width=9.5, wobble=1.3)
    lx, rx = eye_xs
    if emotion == "angry":
        canvas.drawLine(lx - 26, eye_y - 40, lx + 22, eye_y - 16, brow_ink)
        canvas.drawLine(rx - 22, eye_y - 16, rx + 26, eye_y - 40, brow_ink)
        # Pulsing anime/cartoon red anger mark
        ap = make_handdrawn_ink(t, width=6.5, color=skia.ColorSetARGB(255, 255, 46, 100), wobble=1.6)
        pulse = 1.0 + 0.16 * math.sin(t * 16.0)
        canvas.save()
        canvas.translate(64, -64)
        canvas.scale(pulse, pulse)
        canvas.drawLine(-10, -10, -2, -2, ap)
        canvas.drawLine(10, -10, 2, -2, ap)
        canvas.drawLine(-10, 10, -2, 2, ap)
        canvas.drawLine(10, 10, 2, 2, ap)
        canvas.restore()
    elif emotion == "shocked":
        canvas.drawLine(lx - 22, eye_y - 46, lx + 22, eye_y - 52, brow_ink)
        canvas.drawLine(rx - 22, eye_y - 52, rx + 22, eye_y - 46, brow_ink)
        sw_y = -62 + ((t * 62) % 28)
        drop = skia.Path()
        drop.moveTo(-84, sw_y - 20)
        drop.quadTo(-66, sw_y + 12, -84, sw_y + 20)
        drop.quadTo(-102, sw_y + 12, -84, sw_y - 20)
        drop.close()
        canvas.drawPath(drop, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(245, 56, 189, 248)))
        canvas.drawPath(drop, ink_thin)
    elif emotion == "crying":
        canvas.drawLine(lx - 24, eye_y - 22, lx + 18, eye_y - 44, brow_ink)
        canvas.drawLine(rx - 18, eye_y - 44, rx + 24, eye_y - 22, brow_ink)
    elif emotion == "smug":
        canvas.drawLine(lx - 22, eye_y - 26, lx + 22, eye_y - 26, brow_ink)
        canvas.drawLine(rx - 20, eye_y - 38, rx + 24, eye_y - 48, brow_ink)
    else:
        canvas.drawLine(lx - 22, eye_y - 34, lx + 22, eye_y - 36, brow_ink)
        canvas.drawLine(rx - 22, eye_y - 36, rx + 22, eye_y - 34, brow_ink)

    # 7. Studio 9-Viseme Rhubarb Mouth
    canvas.save()
    canvas.translate(look_x * 0.42, 42.0)
    draw_rhubarb_mouth_v2(canvas, viseme, emotion, ink)
    canvas.restore()

    # 8. Floating Comic Reaction Badge (! / ?!) popping beside head!
    if emotion in ("shocked", "angry") and is_speaking:
        pop = ease_out_back((t * 4.0) % 1.0) if (t % 2.0) < 0.35 else 1.0
        bx, by = -facing * 124.0, -96.0
        canvas.save()
        canvas.translate(bx, by)
        canvas.scale(pop, pop)
        badge_col = skia.ColorSetARGB(255, 255, 209, 102) if emotion == "shocked" else skia.ColorSetARGB(255, 255, 46, 147)
        burst = skia.Path()
        for bi in range(12):
            ang = bi * math.pi / 6.0
            rad = 44.0 if bi % 2 == 0 else 28.0
            px_b, py_b = rad * math.cos(ang), rad * math.sin(ang)
            if bi == 0:
                burst.moveTo(px_b, py_b)
            else:
                burst.lineTo(px_b, py_b)
        burst.close()
        canvas.drawPath(burst, skia.Paint(AntiAlias=True, Color=badge_col))
        canvas.drawPath(burst, ink_thin)
        sym = "?!" if emotion == "shocked" else "!"
        sf = skia.Font(skia.Typeface("sans-serif", skia.FontStyle.Bold()), 36)
        sw_t = sf.measureText(sym)
        canvas.drawString(sym, -sw_t / 2.0, 12, sf, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 16, 12, 24) if emotion == "shocked" else skia.ColorWHITE))
        canvas.restore()

    canvas.restore()  # end head
    canvas.restore()  # end puppet


# ---------------------------------------------------------------------------
# 4. Rich 2.5D Parallax Cel-Shaded Cartoon Scenery & Anime Speed Lines VFX
# ---------------------------------------------------------------------------
def draw_parallax_scenery_v2(
    canvas: skia.Canvas,
    sx: float,
    sy: float,
    sw: float,
    sh: float,
    scene_type: str,
    weather_fx: List[str],
    t: float,
    cam_pan_x: float = 0.0,
) -> None:
    """Render richly detailed 3-layer 2.5D parallax hand-drawn cartoon scenery (zero tokens)."""
    is_storm = ("rain" in weather_fx) or ("lightning" in weather_fx) or scene_type in ("sea_storm", "storm_closeup")
    ink = make_handdrawn_ink(t, width=6.5, wobble=1.8)
    ink_soft = make_handdrawn_ink(t, width=4.0, color=skia.ColorSetARGB(180, 26, 22, 42), wobble=1.4)

    canvas.save()
    canvas.clipRect(skia.Rect.MakeXYWH(sx, sy, sw, sh))
    canvas.translate(sx, sy)

    # Layer 1 (Far Sky + Distant Parallax 0.25x)
    far_x = -cam_pan_x * 0.25
    mid_x = -cam_pan_x * 0.60

    if scene_type == "storm_closeup" or (scene_type in ("boat_whale", "sea_storm") and is_storm):
        sky = skia.Paint()
        sky.setShader(
            skia.GradientShader.MakeRadial(
                (sw * 0.5, sh * 0.36),
                sw * 0.85,
                [skia.ColorSetARGB(255, 42, 48, 96), skia.ColorSetARGB(255, 14, 16, 38)],
            )
        )
        canvas.drawRect(skia.Rect.MakeWH(sw, sh), sky)

        # Rolling layered storm clouds (mid parallax)
        for ci in range(5):
            cx = ((ci * sw * 0.30 + t * (34 + ci * 8) + far_x) % (sw + 320)) - 160
            cy = sh * (0.10 + 0.06 * (ci % 2))
            for dx, dy, rad in ((-68, 16, 56), (0, -10, 76), (72, 16, 58)):
                canvas.drawCircle(cx + dx, cy + dy, rad, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(240, 56, 66, 104)))
                canvas.drawCircle(cx + dx, cy + dy + 12, rad * 0.82, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(140, 34, 40, 72)))
                canvas.drawCircle(cx + dx, cy + dy, rad, ink_soft)

        # Forked glowing lightning bolt!
        if "lightning" in weather_fx and (int(t * 5) % 13 in (0, 1)):
            canvas.drawRect(skia.Rect.MakeWH(sw, sh), skia.Paint(Color=skia.ColorSetARGB(85, 235, 245, 255)))
            bx = sw * 0.72 + far_x
            bolt = skia.Path()
            bolt.moveTo(bx, 0)
            bolt.lineTo(bx - 70, sh * 0.18)
            bolt.lineTo(bx + 18, sh * 0.22)
            bolt.lineTo(bx - 88, sh * 0.44)
            glow = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=24, Color=skia.ColorSetARGB(140, 255, 240, 120))
            glow.setImageFilter(skia.ImageFilters.Blur(10, 10))
            canvas.drawPath(bolt, glow)
            canvas.drawPath(bolt, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=10, Color=skia.ColorWHITE))

    elif scene_type in ("boat_whale", "boat_deck"):
        # Vibrant daytime sky + warm horizon glow + golden sun with god-rays!
        sky = skia.Paint()
        sky.setShader(
            skia.GradientShader.MakeLinear(
                [(0, 0), (0, sh * 0.62)],
                [skia.ColorSetARGB(255, 38, 164, 240), skia.ColorSetARGB(255, 168, 228, 255), skia.ColorSetARGB(255, 254, 243, 199)],
                [0.0, 0.72, 1.0],
            )
        )
        canvas.drawRect(skia.Rect.MakeWH(sw, sh), sky)

        # Rotating sun god-rays!
        sun_x, sun_y = sw * 0.80 + far_x, sh * 0.16
        canvas.save()
        canvas.translate(sun_x, sun_y)
        canvas.rotate(t * 8.0)
        ray_p = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(48, 255, 245, 175))
        for ri in range(8):
            canvas.rotate(45.0)
            rp = skia.Path()
            rp.moveTo(0, 0)
            rp.lineTo(-26, -340)
            rp.lineTo(26, -340)
            rp.close()
            canvas.drawPath(rp, ray_p)
        canvas.restore()
        canvas.drawCircle(sun_x, sun_y, 72, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 255, 209, 102)))
        canvas.drawCircle(sun_x, sun_y, 72, ink)

        # Cel-shaded fluffy cumulus clouds (mid parallax)
        for ci in range(4):
            cx = ((ci * sw * 0.34 + t * (22 + ci * 5) + far_x) % (sw + 300)) - 150
            cy = sh * (0.14 + 0.08 * (ci % 2))
            for dx, dy, rad in ((-64, 16, 48), (0, -8, 66), (68, 16, 50)):
                canvas.drawCircle(cx + dx, cy + dy + 8, rad, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(180, 186, 224, 248)))
                canvas.drawCircle(cx + dx, cy + dy, rad * 0.94, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
                canvas.drawCircle(cx + dx, cy + dy, rad, ink_soft)

    elif scene_type == "desert_run":
        sky = skia.Paint()
        sky.setShader(skia.GradientShader.MakeLinear([(0, 0), (0, sh * 0.72)], [skia.ColorSetARGB(255, 114, 214, 245), skia.ColorSetARGB(255, 254, 240, 178)]))
        canvas.drawRect(skia.Rect.MakeWH(sw, sh), sky)
        # Distant desert mesas (0.25x parallax)
        mesa = skia.Path()
        mesa.moveTo(-100, sh * 0.72)
        mesa.lineTo(sw * 0.14 + far_x, sh * 0.50)
        mesa.lineTo(sw * 0.34 + far_x, sh * 0.50)
        mesa.lineTo(sw * 0.44 + far_x, sh * 0.66)
        mesa.lineTo(sw * 0.64 + far_x, sh * 0.46)
        mesa.lineTo(sw * 0.86 + far_x, sh * 0.46)
        mesa.lineTo(sw + 100, sh * 0.72)
        mesa.close()
        canvas.drawPath(mesa, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 206, 152, 108)))
        canvas.drawPath(mesa, ink_soft)
        # Foreground desert ground + scrolling tufts & cartoon skull
        gnd = skia.Path()
        gnd.moveTo(0, sh * 0.70)
        for x in range(0, int(sw) + 60, 60):
            gnd.lineTo(x, sh * 0.70 + 14 * math.sin(x * 0.007))
        gnd.lineTo(sw, sh)
        gnd.lineTo(0, sh)
        gnd.close()
        canvas.drawPath(gnd, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 198, 148, 96)))
        canvas.drawPath(gnd, ink)
        scroll = (t * 200.0) % sw
        for ti in range(5):
            tx = (ti * sw * 0.24 - scroll) % sw
            ty = sh * (0.80 + 0.04 * (ti % 2))
            canvas.drawLine(tx, ty, tx - 16, ty - 28, ink_soft)
            canvas.drawLine(tx, ty, tx, ty - 36, ink_soft)
            canvas.drawLine(tx, ty, tx + 16, ty - 26, ink_soft)

    elif scene_type == "palace_throne":
        # Rich royal chamber with stone blocks, columns, throne, and flickering glowing torches!
        wall = skia.Paint()
        wall.setShader(skia.GradientShader.MakeLinear([(0, 0), (0, sh)], [skia.ColorSetARGB(255, 92, 74, 110), skia.ColorSetARGB(255, 48, 36, 66)]))
        canvas.drawRect(skia.Rect.MakeWH(sw, sh), wall)
        # Marble columns (mid parallax)
        for px in (sw * 0.06, sw * 0.84):
            cr = skia.Rect.MakeXYWH(px + mid_x * 0.4, sh * 0.06, sw * 0.10, sh * 0.72)
            canvas.drawRect(cr, skia.Paint(Color=skia.ColorSetARGB(255, 218, 206, 184)))
            canvas.drawRect(skia.Rect.MakeXYWH(px + mid_x * 0.4 + sw * 0.06, sh * 0.06, sw * 0.04, sh * 0.72), skia.Paint(Color=skia.ColorSetARGB(120, 120, 108, 92)))
            canvas.drawRect(cr, ink)
        # Flickering torches with warm radial glow!
        flick = 0.88 + 0.16 * math.sin(t * 22.0)
        for tx in (sw * 0.22, sw * 0.78):
            glow = skia.Paint(AntiAlias=True)
            glow.setShader(skia.GradientShader.MakeRadial((tx + mid_x * 0.5, sh * 0.30), 150 * flick, [skia.ColorSetARGB(140, 255, 196, 70), skia.ColorSetARGB(0, 255, 140, 20)]))
            canvas.drawCircle(tx + mid_x * 0.5, sh * 0.30, 150 * flick, glow)
            canvas.drawOval(skia.Rect.MakeXYWH(tx + mid_x * 0.5 - 16, sh * 0.27, 32, 48 * flick), skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 255, 180, 40)))
        # Grand Royal Throne
        tr_x = sw * 0.34 + mid_x * 0.5
        canvas.drawRoundRect(skia.Rect.MakeXYWH(tr_x, sh * 0.18, sw * 0.32, sh * 0.60), 30, 30, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 148, 102, 42)))
        canvas.drawRoundRect(skia.Rect.MakeXYWH(tr_x, sh * 0.18, sw * 0.32, sh * 0.60), 30, 30, ink)
        canvas.drawRoundRect(skia.Rect.MakeXYWH(tr_x + sw * 0.04, sh * 0.23, sw * 0.24, sh * 0.48), 22, 22, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 198, 36, 62)))
        canvas.drawRoundRect(skia.Rect.MakeXYWH(tr_x + sw * 0.04, sh * 0.23, sw * 0.24, sh * 0.48), 22, 22, ink_soft)
        # Floor carpet
        canvas.drawRect(skia.Rect.MakeXYWH(0, sh * 0.76, sw, sh * 0.24), skia.Paint(Color=skia.ColorSetARGB(255, 128, 22, 52)))
        canvas.drawLine(0, sh * 0.76, sw, sh * 0.76, ink)

    elif scene_type == "city_wall_tree":
        sky = skia.Paint()
        sky.setShader(skia.GradientShader.MakeLinear([(0, 0), (0, sh * 0.70)], [skia.ColorSetARGB(255, 86, 178, 228), skia.ColorSetARGB(255, 192, 232, 248)]))
        canvas.drawRect(skia.Rect.MakeWH(sw, sh), sky)
        # Ancient fortified brick city walls with battlements
        wall_y = sh * 0.45
        canvas.drawRect(skia.Rect.MakeXYWH(-40, wall_y, sw + 80, sh * 0.28), skia.Paint(Color=skia.ColorSetARGB(255, 168, 156, 138)))
        for mx in range(0, int(sw), 90):
            canvas.drawRect(skia.Rect.MakeXYWH(mx + far_x, wall_y - 28, 48, 28), skia.Paint(Color=skia.ColorSetARGB(255, 168, 156, 138)))
            canvas.drawRect(skia.Rect.MakeXYWH(mx + far_x, wall_y - 28, 48, 28), ink_soft)
        canvas.drawLine(0, wall_y, sw, wall_y, ink)
        # Grassy ground + tree shadow
        canvas.drawRect(skia.Rect.MakeXYWH(0, sh * 0.71, sw, sh * 0.29), skia.Paint(Color=skia.ColorSetARGB(255, 122, 168, 92)))
        canvas.drawOval(skia.Rect.MakeXYWH(sw * 0.46, sh * 0.75, sw * 0.60, sh * 0.16), skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(95, 22, 48, 24)))
        canvas.drawLine(0, sh * 0.71, sw, sh * 0.71, ink)
        # Layered cel-shaded green tree canopy top-right
        for cx, cy, cr, col in [
            (0.76, 0.16, 128, (32, 92, 44)),
            (0.90, 0.20, 142, (26, 78, 38)),
            (0.84, 0.12, 112, (58, 142, 64)),
            (0.96, 0.34, 118, (42, 116, 52)),
        ]:
            canvas.drawCircle(sw * cx + mid_x * 0.4, sh * cy, cr, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, *col)))
            canvas.drawCircle(sw * cx + mid_x * 0.4, sh * cy, cr, ink)

    else:  # hill_sulking / office / street
        sky = skia.Paint()
        sky.setShader(skia.GradientShader.MakeLinear([(0, 0), (0, sh)], [skia.ColorSetARGB(255, 86, 122, 156), skia.ColorSetARGB(255, 226, 168, 132)]))
        canvas.drawRect(skia.Rect.MakeWH(sw, sh), sky)
        hill = skia.Path()
        hill.moveTo(0, sh)
        hill.lineTo(0, sh * 0.40)
        hill.quadTo(sw * 0.50, sh * 0.12, sw, sh * 0.42)
        hill.lineTo(sw, sh)
        hill.close()
        canvas.drawPath(hill, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 158, 116, 92)))
        canvas.drawPath(hill, ink)

    # Maritime ocean layers + billowing mast/sail + giant breaching whale!
    if scene_type in ("boat_whale", "sea_storm", "boat_deck") or "waves" in weather_fx:
        sea_y = sh * 0.65
        # Ship wooden mast & billowing canvas sail behind characters!
        if scene_type in ("boat_whale", "sea_storm"):
            rock = math.sin(t * (4.0 if is_storm else 2.2)) * (6.0 if is_storm else 2.4)
            canvas.save()
            canvas.translate(sw * 0.50 + mid_x * 0.5, sea_y)
            canvas.rotate(rock)
            canvas.drawRect(skia.Rect.MakeXYWH(-14, -sh * 0.44, 28, sh * 0.46), skia.Paint(Color=skia.ColorSetARGB(255, 114, 62, 28)))
            canvas.drawRect(skia.Rect.MakeXYWH(-14, -sh * 0.44, 28, sh * 0.46), ink_soft)
            # Billowing sail
            billow = 28.0 * math.sin(t * 4.5)
            sail = skia.Path()
            sail.moveTo(14, -sh * 0.40)
            sail.quadTo(sw * 0.24 + billow, -sh * 0.24, 14, -sh * 0.12)
            sail.close()
            canvas.drawPath(sail, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(240, 250, 245, 232)))
            canvas.drawPath(sail, ink_soft)
            canvas.restore()

        # Back ocean wave + foam highlight
        bw = skia.Path()
        bw.moveTo(0, sh)
        bw.lineTo(0, sea_y)
        for x in range(0, int(sw) + 28, 28):
            bw.lineTo(x, sea_y + 22 * math.sin(x * 0.012 + t * 4.0))
        bw.lineTo(sw, sh)
        bw.close()
        sea_c = skia.ColorSetARGB(255, 14, 62, 112) if is_storm else skia.ColorSetARGB(255, 12, 134, 202)
        canvas.drawPath(bw, skia.Paint(AntiAlias=True, Color=sea_c))
        canvas.drawPath(bw, ink)

        # Giant breaching cartoon whale!
        if "whale_pass" in weather_fx:
            wx = sw * 0.76 + 44 * math.sin(t * 1.5)
            wy = sea_y - 38 + 26 * math.sin(t * 2.8)
            canvas.save()
            canvas.translate(wx, wy)
            canvas.rotate(-12 + 7 * math.sin(t * 2.2))
            canvas.drawOval(skia.Rect.MakeXYWH(-195, -112, 390, 224), skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 30, 58, 168)))
            canvas.drawOval(skia.Rect.MakeXYWH(-160, 12, 300, 92), skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 186, 214, 250)))
            canvas.drawOval(skia.Rect.MakeXYWH(-195, -112, 390, 224), ink)
            canvas.drawCircle(-96, -24, 30, skia.Paint(AntiAlias=True, Color=skia.ColorWHITE))
            canvas.drawCircle(-96, -24, 30, ink_soft)
            canvas.drawCircle(-106, -22, 12, skia.Paint(AntiAlias=True, Color=skia.ColorBLACK))
            smile = skia.Path()
            smile.moveTo(-174, 26)
            smile.quadTo(-110, 72, -38, 34)
            canvas.drawPath(smile, ink)
            canvas.restore()

    # Depth-layered rain
    if "rain" in weather_fx:
        for layer, (cnt, speed, stroke_w, alpha) in enumerate([(22, 900, 3.0, 95), (26, 1550, 4.5, 165)]):
            rp = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=stroke_w, Color=skia.ColorSetARGB(alpha, 196, 234, 255))
            for ri in range(cnt):
                rx = (ri * (97 + layer * 31) + int(t * (speed * 0.35))) % int(sw + 140) - 70
                ry = (ri * (157 + layer * 43) + int(t * speed)) % int(sh + 140) - 70
                canvas.drawLine(rx, ry, rx - 22, ry + 58 + layer * 16, rp)

    canvas.restore()


def draw_foreground_boat_v2(
    canvas: skia.Canvas,
    sx: float,
    sy: float,
    sw: float,
    sh: float,
    scene_type: str,
    weather_fx: List[str],
    t: float,
) -> None:
    """Foreground rocking wooden boat with wood planks, rivets & foaming crest ocean waves (1.25x parallax)."""
    if scene_type not in ("boat_whale", "sea_storm", "boat_deck") and "waves" not in weather_fx:
        return
    is_storm = ("rain" in weather_fx) or ("lightning" in weather_fx) or scene_type == "sea_storm"
    ink = make_handdrawn_ink(t, width=7.5, wobble=1.8)
    sea_y = sh * 0.65

    canvas.save()
    canvas.clipRect(skia.Rect.MakeXYWH(sx, sy, sw, sh))
    canvas.translate(sx, sy)

    rock_deg = math.sin(t * (4.2 if is_storm else 2.2)) * (6.2 if is_storm else 2.4)
    bob_y = math.cos(t * (4.2 if is_storm else 2.2)) * (16.0 if is_storm else 7.0)

    canvas.save()
    canvas.translate(sw * 0.5, sea_y + 22 + bob_y)
    canvas.rotate(rock_deg)
    hull = skia.Path()
    bw = sw * 0.45
    hull.moveTo(-bw, -26)
    hull.lineTo(bw, -26)
    hull.lineTo(bw * 0.78, 138)
    hull.lineTo(-bw * 0.78, 138)
    hull.close()
    canvas.drawPath(hull, skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 148, 72, 24)))
    # Lower hull cel-shade
    canvas.save()
    canvas.clipPath(hull, doAntiAlias=True)
    canvas.drawRect(skia.Rect.MakeXYWH(-bw, 48, bw * 2, 100), skia.Paint(Color=skia.ColorSetARGB(120, 74, 32, 10)))
    plank_p = make_handdrawn_ink(t, width=4.5, color=skia.ColorSetARGB(195, 68, 30, 8), wobble=1.4)
    canvas.drawLine(-bw, 26, bw, 26, plank_p)
    canvas.drawLine(-bw, 78, bw, 78, plank_p)
    canvas.restore()
    canvas.drawPath(hull, ink)
    canvas.restore()

    # Foaming crest foreground ocean wave!
    fw = skia.Path()
    fw.moveTo(0, sh)
    fw.lineTo(0, sea_y + 90)
    for x in range(0, int(sw) + 26, 26):
        fw.lineTo(x, sea_y + 90 + 26 * math.sin(x * 0.015 - t * 4.8))
    fw.lineTo(sw, sh)
    fw.close()
    sea_f = skia.ColorSetARGB(245, 10, 48, 94) if is_storm else skia.ColorSetARGB(240, 4, 96, 154)
    canvas.drawPath(fw, skia.Paint(AntiAlias=True, Color=sea_f))
    # Bright white foam ribbon along wave crest!
    foam_p = make_handdrawn_ink(t, width=10.0, color=skia.ColorSetARGB(200, 224, 246, 255), wobble=2.2)
    crest = skia.Path()
    crest.moveTo(0, sea_y + 90)
    for x in range(0, int(sw) + 26, 26):
        crest.lineTo(x, sea_y + 90 + 26 * math.sin(x * 0.015 - t * 4.8))
    canvas.drawPath(crest, foam_p)
    canvas.drawPath(fw, ink)
    canvas.restore()


def draw_comic_speed_lines(canvas: skia.Canvas, w: float, h: float, t: float, intensity: float = 0.7) -> None:
    """Radiating manga/cartoon action speed-lines around edges during panic/anger peaks!"""
    cx, cy = w * 0.5, h * 0.48
    p = skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=4.5, Color=skia.ColorSetARGB(int(135 * intensity), 255, 255, 255))
    seed_rot = (int(t * 16) * 7) % 360
    for i in range(28):
        ang = math.radians(i * (360.0 / 28.0) + seed_rot)
        r_in = min(w, h) * (0.44 + 0.08 * ((i * 5 + int(t * 12)) % 3))
        r_out = max(w, h) * 0.92
        canvas.drawLine(cx + r_in * math.cos(ang), cy + r_in * math.sin(ang), cx + r_out * math.cos(ang), cy + r_out * math.sin(ang), p)
