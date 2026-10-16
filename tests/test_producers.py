from datetime import datetime, timezone

from bale_crier.producers import SmokeProducer

NOW = datetime(2026, 10, 17, 8, 30, tzinfo=timezone.utc)


def test_smoke_producer_has_a_name():
    assert SmokeProducer().name == "smoke"


def test_it_produces_exactly_one_smoke_bulletin():
    bulletins = SmokeProducer().produce(NOW)

    assert len(bulletins) == 1
    assert bulletins[0].kind == "smoke"
    assert bulletins[0].note_id is None


def test_its_text_is_persian():
    bulletin = SmokeProducer().produce(NOW)[0]

    assert bulletin.text.strip()
    assert any("\u0600" <= char <= "\u06ff" for char in bulletin.text)
    # «می‌بینید»: a half-space word written without U+200C still reads as Persian,
    # so nothing else in the suite would notice the character going missing.
    assert "\u200c" in bulletin.text


def test_it_is_deterministic():
    producer = SmokeProducer()

    assert producer.produce(NOW) == producer.produce(NOW)
