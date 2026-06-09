from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AI_CONSENT_FIELDS = (
    "ai_content_service_enabled_yn",
    "ai_external_promotion_yn",
)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_product_ai_consent_fields_are_threaded_through_backend_contract():
    schema = _read("app/schemas/product.py")
    model = _read("app/models/product.py")
    service = _read("app/services/product/product_service.py")

    for field in AI_CONSENT_FIELDS:
        assert schema.count(f"{field}: Optional[str] = Field(") >= 2
        assert f"{field}: Mapped[str]" in model
        assert f"a.{field}" in service
        assert f":{field}" in service
        assert f"req_body.{field}" in service

    assert '"aiContentServiceEnabledYn": db_rst[0].get("ai_content_service_enabled_yn")' in service
    assert '"aiExternalPromotionYn": db_rst[0].get("ai_external_promotion_yn")' in service


def test_product_ai_consent_migration_adds_default_no_columns():
    migration = _read("dist/init/104-add-product-ai-consent-fields.sql")

    for field in AI_CONSENT_FIELDS:
        assert f"ADD COLUMN {field} VARCHAR(1) NOT NULL DEFAULT 'N'" in migration


def test_product_ai_consent_migration_backfills_existing_products_opted_in_except_1152():
    migration = _read("dist/init/104-add-product-ai-consent-fields.sql")

    assert """UPDATE tb_product
   SET ai_content_service_enabled_yn = 'Y',
       ai_external_promotion_yn = 'Y';""" in migration
    assert """UPDATE tb_product
   SET ai_content_service_enabled_yn = 'Y',
       ai_external_promotion_yn = 'N'
 WHERE product_id = 1152;""" in migration


def test_product_ai_consent_schema_defaults_do_not_force_opt_in():
    schema = _read("app/schemas/product.py")

    for field in AI_CONSENT_FIELDS:
        assert f'{field}: Optional[str] = Field(\n        default="N"' in schema


def test_product_ai_consent_cms_admin_contract_exposes_all_products():
    router = _read("app/routers/admin/admin_query.py")
    service = _read("app/services/admin/admin_product_ai_consent_service.py")

    assert "admin_product_ai_consent_service" in router
    assert '"/product-ai-consents"' in router
    assert '"/product-ai-consents/all"' in router
    assert 'role="admin"' in router

    assert "FROM tb_product p" in service
    assert 'where_clauses = ["p.open_yn = ' not in service
    assert "WHERE p.open_yn = 'Y'" not in service
    assert "p.author_name AS nickname" in service
    assert "COALESCE(u.email, '') AS author_email" in service
    assert "LEFT JOIN tb_user u" in service
    assert "u.user_id = p.user_id" in service
    assert "tb_product_episode e" in service
    assert "e.use_yn = 'Y'" in service
    assert "CASE WHEN p.open_yn = 'Y' THEN 'Y' ELSE 'N' END AS open_yn" in service
    assert "END AS ai_promotion_yn" in service
    assert "p.ai_external_promotion_yn = 'Y'" in service
    assert "tb_story_agent_context_product sacp" in service
    assert "context_status" in service
    assert "END AS websochat_enabled_yn" in service
    assert 'search_target == "product-id"' in service
    assert "download_all = page == -1 or count_per_page == -1" in service


def test_bulk_upload_products_default_ai_consents_to_yes():
    service = _read("app/services/admin/admin_bulk_upload_service.py")

    for field in AI_CONSENT_FIELDS:
        assert field in service

    assert ":ai_content_service_enabled_yn" in service
    assert ":ai_external_promotion_yn" in service
    assert '"ai_content_service_enabled_yn": "Y"' in service
    assert '"ai_external_promotion_yn": "Y"' in service
