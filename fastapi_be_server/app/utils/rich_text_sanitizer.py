import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Comment, NavigableString, Tag


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
_INVISIBLE_TEXT_RE = re.compile(r"[\s\u00a0\u200b\ufeff]+")


def normalize_episode_body_html(html: str | None) -> str:
    """Normalize storage-only editor/import breaks without changing paragraph intent."""
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    _normalize_episode_body_soup(soup)
    return str(soup)


def sanitize_rich_text_html(html: str | None) -> str:
    """Preserve editor HTML shape while removing executable markup."""
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()

    _remove_storage_only_breaks(soup)

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

    _normalize_episode_body_soup(soup)

    return str(soup)


def _remove_storage_only_breaks(soup: BeautifulSoup) -> None:
    for tag in list(soup.find_all("br")):
        class_value = tag.get("class")
        classes = class_value if isinstance(class_value, list) else [class_value]
        if any(str(item) == "ProseMirror-trailingBreak" for item in classes if item):
            tag.decompose()


def _has_visible_or_non_break_content(paragraph: Tag) -> bool:
    for child in paragraph.contents:
        if isinstance(child, NavigableString):
            if _INVISIBLE_TEXT_RE.sub("", str(child)):
                return True
            continue
        if isinstance(child, Tag) and child.name != "br":
            return True
    return False


def _split_leading_breaks(paragraph: Tag, soup: BeautifulSoup) -> None:
    leading_break_count = 0

    while paragraph.contents:
        first_child = paragraph.contents[0]
        if isinstance(first_child, NavigableString):
            if _INVISIBLE_TEXT_RE.sub("", str(first_child)):
                break
            first_child.extract()
            continue
        if isinstance(first_child, Tag) and first_child.name == "br":
            first_child.extract()
            leading_break_count += 1
            continue
        break

    if leading_break_count == 0:
        return

    if not _has_visible_or_non_break_content(paragraph):
        paragraph.clear()
        paragraph.append(soup.new_tag("br"))
        return

    for _ in range(leading_break_count):
        blank_paragraph = soup.new_tag("p")
        blank_paragraph.attrs = dict(paragraph.attrs)
        blank_paragraph.append(soup.new_tag("br"))
        paragraph.insert_before(blank_paragraph)


def _normalize_episode_body_soup(soup: BeautifulSoup) -> None:
    _remove_storage_only_breaks(soup)

    for paragraph in list(soup.find_all("p")):
        if not _has_visible_or_non_break_content(paragraph):
            paragraph.clear()
            paragraph.append(soup.new_tag("br"))
            continue

        while paragraph.contents:
            last_child = paragraph.contents[-1]
            if isinstance(last_child, NavigableString):
                if _INVISIBLE_TEXT_RE.sub("", str(last_child)):
                    break
                last_child.extract()
                continue
            if isinstance(last_child, Tag) and last_child.name == "br":
                last_child.extract()
                continue
            break

        if not _has_visible_or_non_break_content(paragraph):
            paragraph.clear()
            paragraph.append(soup.new_tag("br"))
            continue

        _split_leading_breaks(paragraph, soup)


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
