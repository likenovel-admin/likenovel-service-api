import ast
from pathlib import Path

from app.schemas.product import PostProductsReqBody, PutProductsProductIdReqBody

ROOT = Path(__file__).resolve().parents[1]
AI_CONSENT_FIELDS = (
    "ai_content_service_enabled_yn",
    "ai_external_promotion_yn",
)
REQUIRED_PRODUCT_FIELDS = {
    "ongoing_state": "ongoing",
    "title": "신규 작품",
    "author_nickname": "작가",
    "update_frequency": ["mon"],
    "publish_regular_yn": "Y",
    "primary_genre": "판타지",
    "synopsis": "작품 소개",
    "adult_yn": "N",
    "open_yn": "Y",
    "monopoly_yn": "N",
    "cp_contract_yn": "N",
}


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _load_function(relative_path: str, function_name: str):
    source = _read(relative_path)
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), relative_path, "exec"), namespace)
    return namespace[function_name]


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


def test_new_product_defaults_ai_content_on_without_external_promotion():
    omitted = PostProductsReqBody(**REQUIRED_PRODUCT_FIELDS)
    explicit_opt_out = PostProductsReqBody(
        **REQUIRED_PRODUCT_FIELDS,
        ai_content_service_enabled_yn="N",
    )
    normalize_ai_consent_yn = _load_function(
        "app/services/product/product_service.py",
        "_normalize_ai_consent_yn",
    )
    service = _read("app/services/product/product_service.py")

    assert omitted.ai_content_service_enabled_yn == "Y"
    assert omitted.ai_external_promotion_yn == "N"
    assert explicit_opt_out.ai_content_service_enabled_yn == "N"
    assert normalize_ai_consent_yn(explicit_opt_out.ai_content_service_enabled_yn) == "N"
    assert (
        '"ai_content_service_enabled_yn": ai_content_service_enabled_yn'
        in service
    )


def test_ai_content_default_is_consistent_in_orm_fresh_schema_and_forward_migration():
    model = _read("app/models/product.py")
    create_tables = _read("dist/init/02-create_tables.sql")
    migration = _read("dist/init/107-alter-product-ai-content-default-y.sql")

    assert """ai_content_service_enabled_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        nullable=False,
        server_default="Y",""" in model
    assert (
        "ai_content_service_enabled_yn VARCHAR(1) NOT NULL DEFAULT 'Y'"
        in create_tables
    )
    assert (
        "ALTER COLUMN ai_content_service_enabled_yn SET DEFAULT 'Y'"
        in migration
    )
    migration_upper = migration.upper()
    assert migration.count("ALTER COLUMN") == 1
    assert "AI_EXTERNAL_PROMOTION_YN" not in migration_upper
    for forbidden_statement in ("UPDATE ", "INSERT ", "DELETE ", "ADD COLUMN"):
        assert forbidden_statement not in migration_upper


def test_product_update_omission_preserves_existing_ai_content_value():
    service = _read("app/services/product/product_service.py")
    omitted = PutProductsProductIdReqBody(**REQUIRED_PRODUCT_FIELDS)
    explicit_opt_out = PutProductsProductIdReqBody(
        **REQUIRED_PRODUCT_FIELDS,
        ai_content_service_enabled_yn="N",
    )

    assert 'if "ai_content_service_enabled_yn" in fields_set' in service
    assert "else current_ai_content_service_enabled_yn" in service
    assert "ai_content_service_enabled_yn" not in omitted.model_fields_set
    assert "ai_content_service_enabled_yn" in explicit_opt_out.model_fields_set
    for current_value in ("Y", "N"):
        selected_value = (
            omitted.ai_content_service_enabled_yn
            if "ai_content_service_enabled_yn" in omitted.model_fields_set
            else current_value
        )
        assert selected_value == current_value


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
