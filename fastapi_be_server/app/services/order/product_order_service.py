from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings


async def create_product_order_with_items(
    *,
    db: AsyncSession,
    user_id: int,
    pay_type: str,
    items: list[dict],
    device_type: str = "web",
    created_id: int | None = None,
) -> int:
    """
    Create one product order (+items +payment) as canonical sales source.

    Each item dict supports:
      - item_name: str
      - item_price: int
      - quantity: int (optional, default 1)
      - product_id: int | None
      - episode_id: int | None
      - item_id_override: int | None (use existing item id directly)
    """
    if not items:
        raise ValueError("items must not be empty")

    dml_id = settings.DB_DML_DEFAULT_ID if created_id is None else created_id
    total_price = sum(int(i.get("item_price", 0)) * int(i.get("quantity", 1)) for i in items)

    order_query = text(
        """
        INSERT INTO tb_product_order
        (device_type, order_no, user_id, order_date, total_price, cancel_yn, created_id, updated_id)
        VALUES
        (:device_type, 0, :user_id, NOW(), :total_price, 'N', :created_id, :updated_id)
        """
    )
    order_result = await db.execute(
        order_query,
        {
            "device_type": device_type,
            "user_id": user_id,
            "total_price": total_price,
            "created_id": dml_id,
            "updated_id": dml_id,
        },
    )
    order_id = int(order_result.lastrowid)

    item_info_query = text(
        """
        INSERT INTO tb_product_order_item_info
        (product_id, episode_id, created_id, updated_id)
        VALUES
        (:product_id, :episode_id, :created_id, :updated_id)
        """
    )
    order_item_query = text(
        """
        INSERT INTO tb_product_order_item
        (order_id, item_id, item_name, item_price, cancel_yn, quantity, created_id, updated_id)
        VALUES
        (:order_id, :item_id, :item_name, :item_price, 'N', :quantity, :created_id, :updated_id)
        """
    )

    for item in items:
        item_id_override = item.get("item_id_override")
        if item_id_override is None:
            info_result = await db.execute(
                item_info_query,
                {
                    "product_id": int(item.get("product_id", 0) or 0),
                    "episode_id": int(item.get("episode_id", 0) or 0),
                    "created_id": dml_id,
                    "updated_id": dml_id,
                },
            )
            item_id = int(info_result.lastrowid)
        else:
            item_id = int(item_id_override)

        await db.execute(
            order_item_query,
            {
                "order_id": order_id,
                "item_id": item_id,
                "item_name": str(item.get("item_name", "")),
                "item_price": int(item.get("item_price", 0)),
                "quantity": int(item.get("quantity", 1)),
                "created_id": dml_id,
                "updated_id": dml_id,
            },
        )

    payment_query = text(
        """
        INSERT INTO tb_product_payment
        (order_id, pay_type, price, created_id, updated_id)
        VALUES
        (:order_id, :pay_type, :price, :created_id, :updated_id)
        """
    )
    await db.execute(
        payment_query,
        {
            "order_id": order_id,
            "pay_type": pay_type,
            "price": total_price,
            "created_id": dml_id,
            "updated_id": dml_id,
        },
    )

    return order_id
