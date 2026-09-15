import pytest

from accounts.models import Address
from bot import services
from common.enums import Channel, Region

pytestmark = pytest.mark.django_db


def test_get_or_create_user_creates_once():
    user1 = services.get_or_create_user("111")
    user2 = services.get_or_create_user("111")
    assert user1.id == user2.id
    assert user1.channel == Channel.TELEGRAM


def test_list_addresses_returns_only_that_users_addresses():
    user = services.get_or_create_user("1")
    other = services.get_or_create_user("2")
    Address.objects.create(user=user, region=Region.YEREVAN, district_or_city="Kentron", street="Tumanyan", house_number=1)
    Address.objects.create(user=other, region=Region.YEREVAN, district_or_city="Kentron", street="Other", house_number=1)
    assert [a.street for a in services.list_addresses(user)] == ["Tumanyan"]


def test_get_address_scoped_to_user():
    user = services.get_or_create_user("1")
    other = services.get_or_create_user("2")
    address = Address.objects.create(user=other, region=Region.YEREVAN, district_or_city="Kentron", street="Other", house_number=1)
    assert services.get_address(user, address.id) is None
    assert services.get_address(other, address.id) == address


def test_create_update_delete_address():
    user = services.get_or_create_user("1")
    address = services.create_address(
        user, region=Region.YEREVAN, district_or_city="Kentron", street="Tumanyan",
        house_number=1, house_number_sub="", label="",
    )
    services.update_address(address, street="Changed")
    address.refresh_from_db()
    assert address.street == "Changed"

    services.delete_address(address)
    assert Address.objects.count() == 0


def test_list_recent_notifications_empty_by_default():
    user = services.get_or_create_user("1")
    assert services.list_recent_notifications(user) == []
