import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment


_ALLOWED_TAGS = {
    "blockquote",
    "br",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "s",
    "strike",
    "strong",
    "span",
    "u",
    "ul",
}
_DROP_TAGS = {
    "base",
    "button",
    "embed",
    "form",
    "iframe",
    "input",
    "link",
    "math",
    "meta",
    "noscript",
    "object",
    "script",
    "style",
    "svg",
    "textarea",
}
_TEXT_ALIGN_TAGS = {"blockquote", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p"}
_TEXT_ALIGN_VALUES = {"left", "center", "right", "justify"}
_DATA_IMAGE_RE = re.compile(
    r"^data:image/(png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$",
    re.IGNORECASE,
)
_CONTROL_OR_SPACE_RE = re.compile(r"[\x00-\x20]+")


def sanitize_rich_text_html(html: str | None) -> str:
    """Preserve editor HTML shape while removing executable markup."""
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()

    for tag in list(soup.find_all(True)):
        tag_name = tag.name.lower()
        if tag_name in _DROP_TAGS:
            tag.decompose()
            continue
        if tag_name not in _ALLOWED_TAGS:
            tag.unwrap()
            continue

        allowed_attrs: dict[str, str] = {}
        if tag_name == "img":
            src = _sanitize_url_attr(str(tag.get("src") or ""))
            if src:
                allowed_attrs["src"] = src
            for attr_name in ("alt", "title", "width", "height"):
                attr_value = tag.get(attr_name)
                if attr_value is not None:
                    allowed_attrs[attr_name] = str(attr_value)

        if tag_name in _TEXT_ALIGN_TAGS:
            text_align = _extract_safe_text_align(str(tag.get("style") or ""))
            if text_align:
                allowed_attrs["style"] = f"text-align: {text_align}"

        tag.attrs = allowed_attrs

    return str(soup)


def _sanitize_url_attr(value: str) -> str | None:
    value = value.strip()
    normalized_for_scheme = _CONTROL_OR_SPACE_RE.sub("", value).lower()
    if not normalized_for_scheme:
        return None
    if normalized_for_scheme.startswith("javascript:"):
        return None
    if _DATA_IMAGE_RE.match(normalized_for_scheme):
        return value

    parse_target = f"https:{value}" if value.startswith("//") else value
    parsed = urlparse(parse_target)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if not parsed.scheme and value.startswith("/"):
        return value
    if not parsed.scheme and not value.startswith(("#", "//")):
        return value
    return None


def _extract_safe_text_align(style: str) -> str | None:
    for declaration in style.split(";"):
        if ":" not in declaration:
            continue
        property_name, property_value = declaration.split(":", 1)
        if property_name.strip().lower() != "text-align":
            continue
        value = property_value.strip().lower()
        if value in _TEXT_ALIGN_VALUES:
            return value
    return None
