from app.utils.rich_text_sanitizer import sanitize_rich_text_html


def test_sanitize_rich_text_preserves_editor_shape_and_image():
    html = (
        '<p>첫줄</p><p><br/></p><p style="text-align:center">둘째줄</p>'
        '<img src="https://cdn.likenovel.net/a.webp" alt="표지"/>'
        "<ul><li><strong>굵게</strong><em>기울임</em><u>밑줄</u></li></ul>"
    )

    sanitized = sanitize_rich_text_html(html)

    assert "<p>첫줄</p>" in sanitized
    assert "<p><br/></p>" in sanitized
    assert '<p style="text-align: center">둘째줄</p>' in sanitized
    assert '<img alt="표지" src="https://cdn.likenovel.net/a.webp"/>' in sanitized
    assert "<strong>굵게</strong>" in sanitized
    assert "<em>기울임</em>" in sanitized
    assert "<u>밑줄</u>" in sanitized


def test_sanitize_rich_text_removes_executable_markup_only():
    html = (
        '<script>alert(1)</script>'
        '<iframe src="https://evil.example"></iframe>'
        '<p onclick="alert(1)" style="background:url(javascript:alert(1)); text-align:right">본문</p>'
        '<img src="x" onerror="alert(1)" onclick="alert(1)"/>'
        '<img src="javascript:alert(1)" alt="bad"/>'
        '<a href="javascript:alert(1)">링크텍스트</a>'
    )

    sanitized = sanitize_rich_text_html(html)

    assert "script" not in sanitized
    assert "iframe" not in sanitized
    assert "onclick" not in sanitized
    assert "onerror" not in sanitized
    assert "javascript:" not in sanitized.lower()
    assert '<p style="text-align: right">본문</p>' in sanitized
    assert '<img src="x"/>' in sanitized
    assert "링크텍스트" in sanitized


def test_sanitize_rich_text_allows_only_safe_data_images():
    png = "data:image/png;base64,iVBORw0KGgo="
    svg = "data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+"

    sanitized = sanitize_rich_text_html(
        f'<img src="{png}"/><img src="{svg}"/><img src="//cdn.likenovel.net/a.webp"/>'
    )

    assert png in sanitized
    assert svg not in sanitized
    assert 'src="//cdn.likenovel.net/a.webp"' in sanitized


def test_sanitize_rich_text_preserves_div_and_span_structure_without_attrs():
    sanitized = sanitize_rich_text_html(
        '<div style="text-align:left" onclick="alert(1)">첫줄</div>'
        '<div><span style="color:red">둘째줄</span></div>'
    )

    assert '<div style="text-align: left">첫줄</div>' in sanitized
    assert "<div><span>둘째줄</span></div>" in sanitized
    assert "onclick" not in sanitized
    assert "color:red" not in sanitized
