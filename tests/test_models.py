from epaper_studio.gicisky.models import get_model, parse_advert


def test_parse_advert_42_bwr() -> None:
    info = parse_advert(bytes.fromhex("4b 1e 81 01 40"))
    assert info["model_id"] == 0x004B
    assert info["hardware"] == "0x404B"
    assert info["firmware"] == "0x8101"
    assert info["volts"] == 3.0
    assert info["known"] and info["supported"]
    assert (info["width"], info["height"], info["palette"]) == (400, 300, "bwr")


def test_parse_advert_rejects_wrong_length() -> None:
    assert parse_advert(b"\x01\x02") is None


def test_unknown_model() -> None:
    info = parse_advert(bytes.fromhex("ff 1e 00 01 3f"))
    assert info["known"] is False
    assert get_model(0x3FFF) is None
