GUEST_FREE_EPISODE_LIMIT = 25


def guest_episode_login_required(
    *,
    episode_price_type: str | None,
    episode_no: int,
) -> bool:
    return (
        episode_price_type == "paid"
        or episode_no > GUEST_FREE_EPISODE_LIMIT
    )
