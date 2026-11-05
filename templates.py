"""Page size presets and starter designs."""
from pubmodel import Document, Page, Item, Para, Run

IN = 72.0

SIZES = [
    # (category, name, width_pt, height_pt, unit)
    ("Print", "Letter (8.5 × 11 in)", 8.5 * IN, 11 * IN, "in"),
    ("Print", "Letter landscape (11 × 8.5 in)", 11 * IN, 8.5 * IN, "in"),
    ("Print", "Legal (8.5 × 14 in)", 8.5 * IN, 14 * IN, "in"),
    ("Print", "Tabloid poster (11 × 17 in)", 11 * IN, 17 * IN, "in"),
    ("Print", "Poster (18 × 24 in)", 18 * IN, 24 * IN, "in"),
    ("Print", "Poster (24 × 36 in)", 24 * IN, 36 * IN, "in"),
    ("Print", "Half letter (5.5 × 8.5 in)", 5.5 * IN, 8.5 * IN, "in"),
    ("Print", "Postcard (6 × 4 in)", 6 * IN, 4 * IN, "in"),
    ("Print", "Business card (3.5 × 2 in)", 3.5 * IN, 2 * IN, "in"),
    ("Print", "A4 (210 × 297 mm)", 595.28, 841.89, "mm"),
    ("Print", "A5 (148 × 210 mm)", 419.53, 595.28, "mm"),
    ("Social", "Instagram post (1080 × 1080 px)", 1080, 1080, "px"),
    ("Social", "Instagram portrait (1080 × 1350 px)", 1080, 1350, "px"),
    ("Social", "Story / Reel / TikTok (1080 × 1920 px)", 1080, 1920, "px"),
    ("Social", "Facebook / LinkedIn post (1200 × 630 px)", 1200, 630, "px"),
    ("Social", "X post (1600 × 900 px)", 1600, 900, "px"),
    ("Social", "YouTube thumbnail (1280 × 720 px)", 1280, 720, "px"),
    ("Social", "Discord / Twitch banner (1920 × 480 px)", 1920, 480, "px"),
]

NAVY = (28, 43, 74)
GOLD = (232, 176, 52)
CORAL = (239, 99, 81)
CREAM = (250, 246, 238)
INK = (33, 33, 33)
GREY = (110, 110, 110)
WHITE = (255, 255, 255)


def T(text, size=12, font="Calibri", bold=False, italic=False, color=INK, align="left"):
    paras = []
    for line in text.split("\n"):
        paras.append(Para([Run(line, font=font, size=size, bold=bold, italic=italic, color=color)], align))
    return paras


def text(x, y, w, h, *paras_lists, valign="top", fill=None):
    paras = []
    for pl in paras_lists:
        paras += pl
    return Item(kind="text", x=x, y=y, w=w, h=h, paras=paras, valign=valign, fill=fill)


def blank(w, h, unit="in"):
    d = Document(width=w, height=h, pages=[Page()])
    d.unit = unit
    return d


def flyer():
    W, H = 8.5 * IN, 11 * IN
    p = Page(items=[
        Item(kind="rect", x=0, y=0, w=W, h=H * 0.42, fill=NAVY),
        Item(kind="ellipse", x=W - 150, y=-120, w=290, h=290, fill=GOLD),
        text(48, 70, W - 96, 70, T("YOU'RE INVITED", 16, "Arial", True, color=GOLD)),
        text(48, 105, W - 200, 160, T("Community\nOpen House", 54, "Georgia", True, color=WHITE)),
        text(48, H * 0.42 + 36, W - 96, 60, T("Saturday, May 16  •  10 AM – 4 PM", 22, "Arial", True, color=NAVY)),
        text(48, H * 0.42 + 90, W - 96, 40, T("123 Main Street, Your Town", 16, "Arial", color=GREY)),
        Item(kind="line", x=48, y=H * 0.42 + 140, w=W - 96, h=0, stroke=GOLD, stroke_width=3),
        text(48, H * 0.42 + 160, (W - 120) / 2, 220,
             T("What to expect", 18, "Georgia", True, color=NAVY),
             T("• Live music and food trucks\n• Kids' activities all day\n• Meet local makers and artists\n• Free raffle at 3 PM", 14, "Calibri")),
        Item(kind="rect", x=W / 2 + 12, y=H * 0.42 + 160, w=(W - 120) / 2, h=220, fill=CREAM, stroke=GOLD, stroke_width=1.5),
        text(W / 2 + 28, H * 0.42 + 180, (W - 120) / 2 - 32, 180,
             T("Free admission", 22, "Georgia", True, color=CORAL, align="center"),
             T("Bring a friend!\nRSVP at example.com", 14, "Calibri", align="center"), valign="middle"),
        text(48, H - 70, W - 96, 30, T("Questions? Call (555) 012-3456", 12, "Arial", color=GREY, align="center")),
    ])
    return Document(width=W, height=H, pages=[p])


def poster():
    W, H = 11 * IN, 17 * IN
    p = Page(items=[
        Item(kind="rect", x=0, y=0, w=W, h=H, fill=(20, 20, 28)),
        Item(kind="ellipse", x=W * 0.15, y=H * 0.12, w=W * 0.7, h=W * 0.7, fill=CORAL),
        Item(kind="ellipse", x=W * 0.28, y=H * 0.2, w=W * 0.44, h=W * 0.44, fill=GOLD),
        text(54, H * 0.555, W - 108, 250, T("SUMMER\nNIGHTS", 96, "Impact", color=WHITE, align="center"), valign="middle"),
        text(54, H * 0.80, W - 108, 50, T("LIVE MUSIC  •  FOOD  •  FIREWORKS", 24, "Arial", True, color=GOLD, align="center")),
        text(54, H * 0.86, W - 108, 80, T("July 4  •  Riverside Park  •  6 PM", 22, "Arial", color=WHITE, align="center")),
    ])
    return Document(width=W, height=H, pages=[p])


def newsletter():
    W, H = 8.5 * IN, 11 * IN
    m = 48
    colw = (W - 2 * m - 24) / 2
    p1 = Page(items=[
        Item(kind="rect", x=0, y=0, w=W, h=120, fill=NAVY),
        text(m, 28, W - 2 * m, 60, T("The Monthly Update", 38, "Georgia", True, color=WHITE)),
        text(m, 82, W - 2 * m, 24, T("Issue 12  •  November", 12, "Arial", color=GOLD)),
        text(m, 150, W - 2 * m, 50, T("Headline goes here", 28, "Georgia", True, color=NAVY)),
        Item(kind="line", x=m, y=202, w=W - 2 * m, h=0, stroke=GOLD, stroke_width=2),
        text(m, 220, colw, 420, T(LOREM, 11, "Calibri", align="justify")),
        Item(kind="rect", x=m + colw + 24, y=220, w=colw, h=200, fill=(225, 230, 240)),
        text(m + colw + 24, 220, colw, 200, T("Drop a photo here\n(Insert ▸ Picture)", 12, "Calibri", color=GREY, align="center"), valign="middle"),
        text(m + colw + 24, 440, colw, 200, T(LOREM[:420], 11, "Calibri", align="justify")),
        Item(kind="rect", x=m, y=670, w=W - 2 * m, h=70, fill=CREAM),
        text(m + 16, 680, W - 2 * m - 32, 50, T("In this issue: Feature story • Events • Member spotlight", 12, "Arial", True, color=NAVY), valign="middle"),
    ])
    p2 = Page(items=[
        text(m, 48, W - 2 * m, 40, T("Upcoming events", 24, "Georgia", True, color=NAVY)),
        Item(kind="line", x=m, y=90, w=W - 2 * m, h=0, stroke=GOLD, stroke_width=2),
        text(m, 106, colw, 560, T(LOREM, 11, "Calibri", align="justify")),
        text(m + colw + 24, 106, colw, 260,
             T("Member spotlight", 16, "Georgia", True, color=CORAL),
             T(LOREM[:380], 11, "Calibri", align="justify")),
        Item(kind="rect", x=m + colw + 24, y=390, w=colw, h=180, fill=NAVY),
        text(m + colw + 40, 400, colw - 32, 160,
             T("Save the date", 18, "Georgia", True, color=GOLD, align="center"),
             T("Annual dinner\nDecember 12, 6 PM", 14, "Arial", color=WHITE, align="center"), valign="middle"),
        text(m, H - 60, W - 2 * m, 24, T("example.com  •  hello@example.com", 10, "Arial", color=GREY, align="center")),
    ])
    return Document(width=W, height=H, pages=[p1, p2])


def business_card():
    W, H = 3.5 * IN, 2 * IN
    front = Page(items=[
        Item(kind="rect", x=0, y=0, w=W, h=H, fill=NAVY),
        Item(kind="rect", x=0, y=H - 10, w=W, h=10, fill=GOLD),
        text(16, 34, W - 32, 34, T("Your Name", 18, "Georgia", True, color=WHITE)),
        text(16, 62, W - 32, 20, T("Job Title", 10, "Arial", color=GOLD)),
        text(16, 92, W - 32, 44, T("(555) 012-3456\nyou@example.com\nexample.com", 8, "Arial", color=WHITE)),
    ])
    back = Page(items=[
        Item(kind="rect", x=0, y=0, w=W, h=H, fill=CREAM),
        text(16, 40, W - 32, 64, T("COMPANY", 24, "Georgia", True, color=NAVY, align="center"),
             T("Tagline goes here", 9, "Arial", color=GREY, align="center"), valign="middle"),
    ])
    return Document(width=W, height=H, pages=[front, back])


def certificate():
    W, H = 11 * IN, 8.5 * IN
    p = Page(items=[
        Item(kind="rect", x=24, y=24, w=W - 48, h=H - 48, stroke=GOLD, stroke_width=6),
        Item(kind="rect", x=40, y=40, w=W - 80, h=H - 80, stroke=NAVY, stroke_width=1.5),
        text(80, 90, W - 160, 50, T("CERTIFICATE OF ACHIEVEMENT", 30, "Georgia", True, color=NAVY, align="center")),
        text(80, 160, W - 160, 30, T("This certificate is proudly presented to", 14, "Georgia", italic=True, color=GREY, align="center")),
        text(80, 200, W - 160, 70, T("Recipient Name", 44, "Georgia", True, color=INK, align="center")),
        Item(kind="line", x=W / 2 - 200, y=275, w=400, h=0, stroke=GOLD, stroke_width=2),
        text(120, 295, W - 240, 60, T("in recognition of outstanding dedication, effort and accomplishment.", 14, "Georgia", color=GREY, align="center")),
        Item(kind="line", x=150, y=H - 130, w=200, h=0, stroke=INK, stroke_width=1),
        Item(kind="line", x=W - 350, y=H - 130, w=200, h=0, stroke=INK, stroke_width=1),
        text(150, H - 125, 200, 24, T("Signature", 11, "Arial", color=GREY, align="center")),
        text(W - 350, H - 125, 200, 24, T("Date", 11, "Arial", color=GREY, align="center")),
        Item(kind="ellipse", x=W / 2 - 45, y=H - 175, w=90, h=90, fill=GOLD),
        text(W / 2 - 45, H - 175, 90, 90, T("★", 36, "Arial", color=WHITE, align="center"), valign="middle"),
    ])
    return Document(width=W, height=H, pages=[p])


def labels():
    """Avery 5160 / 8160 compatible: 30 labels, 2.625 × 1 in."""
    W, H = 8.5 * IN, 11 * IN
    items = []
    lw, lh = 2.625 * IN, 1 * IN
    left, top, gap = 0.1875 * IN, 0.5 * IN, 0.125 * IN
    for r in range(10):
        for c in range(3):
            x = left + c * (lw + gap)
            y = top + r * lh
            items.append(text(x + 8, y + 6, lw - 16, lh - 12,
                              T("Full Name\n123 Street Address\nCity, ST 00000", 10, "Arial"), valign="middle"))
    d = Document(width=W, height=H, pages=[Page(items=items)])
    return d


def social_post():
    W = H = 1080
    p = Page(items=[
        Item(kind="rect", x=0, y=0, w=W, h=H, fill=(24, 24, 36)),
        Item(kind="ellipse", x=620, y=-160, w=620, h=620, fill=CORAL),
        Item(kind="ellipse", x=-180, y=700, w=520, h=520, fill=(90, 70, 200)),
        text(90, 300, 900, 120, T("NEW UPDATE", 48, "Arial", True, color=GOLD)),
        text(90, 380, 900, 320, T("Patch notes\nare live", 110, "Impact", color=WHITE)),
        text(90, 900, 900, 60, T("Link in bio  •  @yourhandle", 34, "Arial", color=(200, 200, 220))),
    ])
    d = Document(width=W, height=H, pages=[p])
    d.unit = "px"
    return d


def youtube_thumb():
    W, H = 1280, 720
    p = Page(items=[
        Item(kind="rect", x=0, y=0, w=W, h=H, fill=(250, 220, 40)),
        Item(kind="rect", x=0, y=H - 160, w=W, h=160, fill=(20, 20, 20)),
        text(60, 40, 1160, 500, T("YOU WON'T\nBELIEVE THIS", 120, "Impact", color=(20, 20, 20)), valign="middle"),
        text(60, H - 140, 1160, 120, T("Episode 12", 64, "Arial", True, color=WHITE), valign="middle"),
    ])
    d = Document(width=W, height=H, pages=[p])
    d.unit = "px"
    return d


LOREM = ("Start typing your story here. Double-click any text box to edit it, then use the Home tab to change "
         "the font, size, color and alignment. Drag the handles to resize boxes, and use the Insert tab to add "
         "more text, shapes and pictures. Press Ctrl+S to save as a Publisher (.pub) file, or use File > Export "
         "to create a PDF for printing.")

STARTERS = [
    ("Event flyer", "Letter flyer with header band", flyer),
    ("Poster", "11 × 17 in bold poster", poster),
    ("Newsletter", "Two-page Letter newsletter", newsletter),
    ("Business card", "3.5 × 2 in, front and back", business_card),
    ("Certificate", "Letter landscape award", certificate),
    ("Address labels", "30 per sheet (Avery 5160 size)", labels),
    ("Social post", "Instagram 1080 × 1080", social_post),
    ("YouTube thumbnail", "1280 × 720", youtube_thumb),
]
