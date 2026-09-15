"""
Sync DB operations backing the bot's handlers (Django's ORM is
sync-only) -- kept separate from handlers.py so this is testable the
normal Django way. Wrapped with sync_to_async at each call site in
handlers.py rather than here, since PTB callbacks run in an async
event loop.
"""
from accounts.models import Address, User
from common.enums import Channel
from notifications.models import NotificationLog


def get_or_create_user(telegram_id: str) -> User:
    user, _ = User.objects.get_or_create(channel=Channel.TELEGRAM, external_id=telegram_id)
    return user


def list_addresses(user: User) -> list[Address]:
    return list(user.addresses.order_by("id"))


def get_address(user: User, address_id: int) -> Address | None:
    return user.addresses.filter(id=address_id).first()


def create_address(user: User, **fields) -> Address:
    return Address.objects.create(user=user, **fields)


def update_address(address: Address, **fields) -> Address:
    for key, value in fields.items():
        setattr(address, key, value)
    address.save()
    return address


def delete_address(address: Address) -> None:
    address.delete()


def list_recent_notifications(user: User, limit: int = 10) -> list[NotificationLog]:
    return list(
        user.notifications.select_related("outage_announcement", "address").order_by("-created_at")[:limit]
    )
