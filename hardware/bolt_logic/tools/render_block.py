"""Close-up render of the 5 V buck block (F.Cu, B.Cu, vias, pads, silkscreen) for review.

    python3 tools/render_block.py [board.kicad_pcb] [out.png]
"""
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import buck_block  # noqa: E402


def main():
    from PIL import Image, ImageDraw, ImageFont
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(PROJ, "bolt_logic.kicad_pcb")
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(PROJ, "..", "..", "docs", "buck_block.png")
    board = pcbnew.LoadBoard(src)
    mm = pcbnew.ToMM
    u1 = board.FindFootprintByReference("U1")
    ux, uy = mm(u1.GetPosition().x), mm(u1.GetPosition().y)
    x0, y0, x1, y1 = ux - 7, uy - 6, ux + 15, uy + 13          # window, board mm (y down)
    S = 40                                                    # px per mm
    W, H = int((x1 - x0) * S), int((y1 - y0) * S)
    img = Image.new("RGB", (W, H + 40), (16, 20, 24))
    d = ImageDraw.Draw(img, "RGBA")
    tx = lambda x, y: ((x - x0) * S, (y - y0) * S + 40)
    F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    FB = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    colors = {pcbnew.B_Cu: (60, 110, 220, 170), pcbnew.F_Cu: (210, 70, 60, 200)}

    for z in board.Zones():                                   # pours, faint
        if z.GetLayer() not in colors or not z.IsFilled():
            continue
        poly = z.GetFilledPolysList(z.GetLayer())
        for i in range(poly.OutlineCount()):
            o = poly.Outline(i)
            pts = [tx(mm(o.CPoint(k).x), mm(o.CPoint(k).y)) for k in range(o.PointCount())]
            if len(pts) > 2:
                r, g, b, _ = colors[z.GetLayer()]
                d.polygon(pts, fill=(r, g, b, 45))
    for lay in (pcbnew.B_Cu, pcbnew.F_Cu):
        for t in board.GetTracks():
            if t.GetClass() == "PCB_TRACK" and t.GetLayer() == lay:
                w = mm(t.GetWidth()) * S
                a, b = tx(mm(t.GetStart().x), mm(t.GetStart().y)), tx(mm(t.GetEnd().x), mm(t.GetEnd().y))
                d.line([a, b], fill=colors[lay], width=max(1, int(w)))
                for c in (a, b):
                    d.ellipse([c[0] - w / 2, c[1] - w / 2, c[0] + w / 2, c[1] + w / 2], fill=colors[lay])
    for fp in board.GetFootprints():
        for p in fp.Pads():
            bb = p.GetBoundingBox()
            a, b = tx(mm(bb.GetLeft()), mm(bb.GetTop())), tx(mm(bb.GetRight()), mm(bb.GetBottom()))
            col = (200, 170, 60, 230) if p.IsOnLayer(pcbnew.F_Cu) else (120, 150, 220, 160)
            d.rectangle([a, b], fill=col)
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            c = tx(mm(t.GetPosition().x), mm(t.GetPosition().y)); r = mm(t.GetWidth()) / 2 * S
            d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=(230, 230, 230))
            r = mm(t.GetDrill()) / 2 * S
            d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=(16, 20, 24))
    for ref in buck_block.REFS:
        t = board.FindFootprintByReference(ref).Reference()
        c = tx(mm(t.GetPosition().x), mm(t.GetPosition().y))
        d.text((c[0] - 9 * len(ref) / 2, c[1] - 9), ref, fill=(255, 255, 255), font=FB)
    for net, xy in (("SW", (3.6, 1.6)), ("VIN", (-1.7, 8.0)), ("GND", (0.7, 8.0)), ("+5V", (9.4, 11.8))):
        c = tx(ux + xy[0], uy + xy[1]); d.text(c, net, fill=(150, 230, 150), font=F)
    d.text((10, 10), "5 V buck block - F.Cu red, B.Cu blue, pads gold, 1 mm = %d px" % S,
           fill=(255, 255, 255), font=FB)
    img.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
