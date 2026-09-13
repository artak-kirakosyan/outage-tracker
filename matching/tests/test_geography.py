from common.enums import Region
from matching.geography import canonicalize_marz, marz_values_for_region


def test_yerevan_is_already_canonical():
    assert canonicalize_marz("Երևան") == Region.YEREVAN


def test_ararat_genitive_form_canonicalizes():
    assert canonicalize_marz("Արարատի") == Region.ARARAT


def test_unmapped_marz_returns_none():
    assert canonicalize_marz("Սյունիքի") is None


def test_none_and_empty_marz_return_none():
    assert canonicalize_marz(None) is None
    assert canonicalize_marz("") is None


def test_marz_values_for_region_round_trips():
    assert marz_values_for_region(Region.ARARAT) == ["Արարատի"]
    assert marz_values_for_region(Region.YEREVAN) == ["Երևան"]


def test_unsupported_region_returns_empty_list():
    assert marz_values_for_region("shirak") == []
