"""Génère icon.icns (icône de l'application) avec Pillow + iconutil."""
import os, subprocess, shutil
from PIL import Image, ImageDraw, ImageFilter

S = 2048  # dessiné en grand puis réduit (anti-crénelage)
here = os.path.dirname(os.path.abspath(__file__))


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return m


c1, c2 = (88, 60, 230), (214, 158, 46)  # violet -> or (couleur de la puce)

bg = Image.new("RGB", (S, S))
px = bg.load()
for y in range(S):
    for x in range(S):
        px[x, y] = lerp(c1, c2, (x * .42 + y * .78) / (S * 1.2))
mask = rounded_mask((S, S), int(S * .225))
icon = Image.new("RGBA", (S, S), (0, 0, 0, 0)); icon.paste(bg, (0, 0), mask)

gloss = Image.new("L", (S, S), 0)
gd = ImageDraw.Draw(gloss)
gd.ellipse((int(S * -.25), int(S * -.45), int(S * .95), int(S * .55)), fill=70)
gloss = gloss.filter(ImageFilter.GaussianBlur(S * .09))
gloss_rgba = Image.new("RGBA", (S, S), (255, 255, 255, 0))
gloss_rgba.putalpha(Image.composite(gloss, Image.new("L", (S, S), 0), mask))
icon = Image.alpha_composite(icon, gloss_rgba)

edge = Image.new("L", (S, S), 0)
ed = ImageDraw.Draw(edge)
ed.ellipse((int(S * .35), int(S * .45), int(S * 1.35), int(S * 1.45)), fill=60)
edge = edge.filter(ImageFilter.GaussianBlur(S * .12))
edge_rgba = Image.new("RGBA", (S, S), (0, 0, 0, 0))
edge_rgba.putalpha(Image.composite(edge, Image.new("L", (S, S), 0), mask))
icon = Image.alpha_composite(icon, edge_rgba)

cw, ch = int(S * .66), int(S * .42)
thick = int(ch * .05)
card = Image.new("RGBA", (cw, ch + thick), (0, 0, 0, 0))
d = ImageDraw.Draw(card)
r = int(ch * .12)
d.rounded_rectangle((0, thick, cw - 1, ch - 1 + thick), radius=r, fill=(214, 217, 230, 255))
d.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=r, fill=(250, 251, 255, 255))

chip_w, chip_h = int(cw * .40), int(ch * .56)
cx, cy = int(cw * .30), int(ch * .22)
gold1, gold2 = (247, 206, 120), (197, 146, 46)
chip_img = Image.new("RGBA", (chip_w, chip_h), (0, 0, 0, 0))
cpx = chip_img.load()
for yy in range(chip_h):
    for xx in range(chip_w):
        cpx[xx, yy] = lerp(gold1, gold2, (xx + yy) / (chip_w + chip_h)) + (255,)
chip_mask = rounded_mask((chip_w, chip_h), int(ch * .07))
card.paste(chip_img, (cx, cy), Image.composite(chip_mask, Image.new("L", (chip_w, chip_h), 0), chip_mask))
cd = ImageDraw.Draw(card)
cd.rounded_rectangle((cx, cy, cx + chip_w, cy + chip_h), radius=int(ch * .07), outline=(255, 232, 180, 160), width=max(2, int(ch * .01)))
pad = int(chip_w * .14)
for col in range(2):
    x = cx + pad + col * (chip_w - 2 * pad)
    cd.line((x, cy + int(chip_h * .18), x, cy + int(chip_h * .82)), fill=(150, 108, 30, 200), width=max(2, int(ch * .008)))
for row in range(3):
    y = cy + int(chip_h * (.18 + row * .32))
    cd.line((cx + pad, y, cx + chip_w - pad, y), fill=(150, 108, 30, 200), width=max(2, int(ch * .008)))
for i in range(3):
    y = cy + int(chip_h * (.2 + i * .3))
    d.line((cx - int(cw * .06), y, cx, y), fill=(214, 158, 46, 255), width=int(ch * .035))
    d.line((cx + chip_w, y, cx + chip_w + int(cw * .06), y), fill=(214, 158, 46, 255), width=int(ch * .035))
y = int(ch * .82)
d.rounded_rectangle((int(cw * .08), y, int(cw * .38), y + int(ch * .055)), radius=int(ch * .03), fill=(210, 214, 232, 255))

card = card.rotate(14, expand=True, resample=Image.BICUBIC)

shadow = Image.new("RGBA", icon.size, (0, 0, 0, 0))
sh = Image.new("RGBA", card.size, (0, 0, 0, 0)); sh.putalpha(card.split()[3].point(lambda v: int(v * .45)))
pos = ((S - card.width) // 2, (S - card.height) // 2 + int(S * .01))
shadow.paste(sh, (pos[0], pos[1] + int(S * .035)), sh)
shadow = shadow.filter(ImageFilter.GaussianBlur(S * .028))
icon = Image.alpha_composite(icon, shadow)
icon.alpha_composite(card, pos)

base = icon.resize((1024, 1024), Image.LANCZOS)
base.save(os.path.join(here, "icon_1024.png"))

iconset = os.path.join(here, "icon.iconset")
shutil.rmtree(iconset, ignore_errors=True); os.makedirs(iconset)
for size in (16, 32, 128, 256, 512):
    base.resize((size, size), Image.LANCZOS).save(f"{iconset}/icon_{size}x{size}.png")
    base.resize((size * 2, size * 2), Image.LANCZOS).save(f"{iconset}/icon_{size}x{size}@2x.png")
subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(here, "icon.icns")], check=True)
shutil.rmtree(iconset)
print("icon.icns OK")
