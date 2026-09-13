import pytest
from django.db import IntegrityError

from accounts.models import Address, User
from common.enums import Channel, Region

pytestmark = pytest.mark.django_db


def test_user_str_includes_channel_and_external_id():
    user = User.objects.create(external_id="12345")
    assert str(user) == "telegram:12345"


def test_channel_defaults_to_telegram():
    user = User.objects.create(external_id="12345")
    assert user.channel == Channel.TELEGRAM


def test_channel_and_external_id_together_must_be_unique():
    User.objects.create(external_id="12345")
    with pytest.raises(IntegrityError):
        User.objects.create(external_id="12345")


def test_uniqueness_is_scoped_to_channel_not_external_id_alone():
    # Only 'telegram' exists today, so there's no second channel to
    # construct a real second row with -- this asserts the constraint's
    # field list directly, since that's the whole point of keeping the
    # schema channel-generic rather than a bare telegram_id.
    constraint_fields = {tuple(c.fields) for c in User._meta.constraints}
    assert ("channel", "external_id") in constraint_fields


def test_address_belongs_to_its_user():
    user = User.objects.create(external_id="1")
    address = Address.objects.create(
        user=user, region=Region.YEREVAN, district_or_city="Kentron",
        street="Tumanyan", house_number=5,
    )
    assert address.user == user
    assert list(user.addresses.all()) == [address]


def test_address_has_no_provider_field():
    field_names = {f.name for f in Address._meta.get_fields()}
    assert "provider" not in field_names


def test_address_str_uses_label_when_present():
    user = User.objects.create(external_id="1")
    address = Address.objects.create(
        user=user, region=Region.ARARAT, district_or_city="Artashat",
        street="Bakunts", house_number=10, label="Home",
    )
    assert str(address) == "Home (Bakunts 10)"


def test_address_str_falls_back_to_street_and_number_without_label():
    user = User.objects.create(external_id="2")
    address = Address.objects.create(
        user=user, region=Region.ARARAT, district_or_city="Artashat",
        street="Bakunts", house_number=10,
    )
    assert str(address) == "Bakunts 10"


def test_address_str_includes_house_number_sub():
    user = User.objects.create(external_id="3")
    address = Address.objects.create(
        user=user, region=Region.YEREVAN, district_or_city="Arabkir",
        street="Gyulbenkyan", house_number=4, house_number_sub="A",
    )
    assert str(address) == "Gyulbenkyan 4A"


def test_deleting_user_cascades_to_their_addresses():
    user = User.objects.create(external_id="4")
    Address.objects.create(
        user=user, region=Region.YEREVAN, district_or_city="Kentron",
        street="Tumanyan", house_number=1,
    )
    user.delete()
    assert Address.objects.count() == 0
