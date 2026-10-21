"""
The installation's appearance (Documentation/adr/0019-appearance.md): the title in place of "GS1 Resolver Community
Edition", the logo and three colours, set by server administrators and shown on every page of the installation — the
portal, the home page, the resolver's pages. One setting, "appearance", in the portal's database (the resolver reads it
too, web_server/src/web_pages.py):

    {"title", "colour", "action", "accent", "logo": {"type", "data", "etag", "width", "height"} | None,
     "updated", "updatedBy"}

Absent: the original. Colours on which white text is hard to read are refused (contrast below MIN_CONTRAST).
"""
import re

import branding
import store
from users import UserError

SETTING = "appearance"
ORIGINAL = {"title": "GS1 Resolver Community Edition", "colour": "#002C6C", "action": "#CE3D0D", "accent": "#F26334"}
COLOURS = ("colour", "action", "accent")
COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
TITLE_MAX = 60
MIN_CONTRAST = 4.5            # white text on the main and the action colours (WCAG 2.1, AA)


def _luminance(colour: str) -> float:
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(colour: str) -> float:
    """The contrast ratio of white text on a colour."""
    return 1.05 / (_luminance(colour) + 0.05)


def darker(colour: str, share: float) -> str:
    """The colour mixed with black (share 0.3: 30 % black)."""
    channels = [round(int(colour[i:i + 2], 16) * (1 - share)) for i in (1, 3, 5)]
    return "#" + "".join(f"{c:02X}" for c in channels)


def current() -> dict:
    """The stored appearance (the logo with its bytes), or {} for the original."""
    return store.get_setting(SETTING) or {}


def public(doc: dict | None = None) -> dict:
    """What every page needs: the title, the colours, the logo's address and whether this is the original."""
    doc = current() if doc is None else doc
    logo = doc.get("logo") or None
    return {**{k: doc.get(k) or v for k, v in ORIGINAL.items()},
            "logo": f"appearance/logo?v={logo['etag']}" if logo else "logo.svg",
            "customLogo": bool(logo), "original": not doc, "defaults": ORIGINAL,
            "updated": doc.get("updated"), "updatedBy": doc.get("updatedBy")}


def save(data: dict, user: str) -> dict:
    """Title, colours and logo ("logo": base64 to replace it, "" for the original, absent to keep it)."""
    doc = current()
    title = " ".join(str(data.get("title", doc.get("title")) or ORIGINAL["title"]).split())
    if not title or len(title) > TITLE_MAX or not title.isprintable():
        raise UserError("appearance.titleInvalid", max=TITLE_MAX)
    change = {"title": title}
    for field in COLOURS:
        value = str(data.get(field, doc.get(field)) or ORIGINAL[field])
        if not COLOUR.match(value):
            raise UserError("appearance.colourInvalid")
        change[field] = value.upper()
    for field in ("colour", "action"):
        ratio = contrast(change[field])
        if ratio < MIN_CONTRAST:
            raise UserError(f"appearance.{field}Contrast", ratio=f"{ratio:.1f}", min=f"{MIN_CONTRAST:.1f}")
    if "logo" in data:
        change["logo"] = branding.read_logo(data["logo"]) if data["logo"] else None
    else:
        change["logo"] = doc.get("logo") or None
    change.update(updated=store.iso(store.now()), updatedBy=user)
    store.set_setting(SETTING, change)
    return change


def reset() -> None:
    """Back to the original title, logo and colours."""
    store.col("settings").delete_one({"_id": SETTING})


def css(doc: dict | None = None) -> str:
    """The colours as the design tokens of the portal's and the home page's style sheets (empty for the original)."""
    doc = current() if doc is None else doc
    if not doc:
        return "/* the original appearance (Documentation/adr/0019-appearance.md) */\n"
    colour, action, accent = (doc.get(k) or ORIGINAL[k] for k in COLOURS)
    return ("/* the installation's appearance (Documentation/adr/0019-appearance.md) */\n"
            f":root {{ --gs1-blue: {colour}; --gs1-blue-dark: {darker(colour, .33)}; --gs1-orange: {accent};\n"
            f"  --action: {action}; --action-dark: {darker(action, .18)}; }}\n")
