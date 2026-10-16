from datetime import datetime, timezone

import pytest
import requests

from bale_crier.credit import CREDIT_PATH, fetch_report, tier_of

BASE = "https://api.avalai.ir"


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def stub_get(monkeypatch, response):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    return captured


def test_the_request_is_a_get_carrying_the_bearer_key(monkeypatch):
    captured = stub_get(monkeypatch, FakeResponse({"remaining_irt": 1}))

    fetch_report(key="SECRET", timeout=5)

    assert captured["url"] == BASE + CREDIT_PATH
    assert captured["headers"]["Authorization"] == "Bearer SECRET"
    assert captured["timeout"] == 5


def test_a_string_number_and_a_json_number_both_parse(monkeypatch):
    stub_get(
        monkeypatch,
        FakeResponse(
            {
                "remaining_irt": 439968.18,
                "credit_sources": {
                    "packages": [
                        {
                            "template_id": "d-1",
                            "name": "پایه",
                            "remaining_irt": "12000.5",
                            "amount_irt": "50000",
                            "end_date": "2099-01-01T00:00:00Z",
                        }
                    ]
                },
            }
        ),
    )

    read = fetch_report(key="k")

    assert read.error == ""
    assert read.report.main_balance_irt == 439968.18
    package = read.report.packages[0]
    assert package.remaining_irt == 12000.5
    assert package.amount_irt == 50000.0
    assert package.end_date == datetime(2099, 1, 1, tzinfo=timezone.utc)


def test_a_package_number_that_arrives_as_a_json_number_still_parses(monkeypatch):
    """The provider is not consistent about the form — the top-level balance is a
    number and package amounts are strings today — so a change on either side must
    not read as an unreadable package."""
    stub_get(
        monkeypatch,
        FakeResponse(
            {
                "remaining_irt": 100,
                "credit_sources": {
                    "packages": [{"template_id": "d-1", "name": "پایه", "remaining_irt": 12000.5}]
                },
            }
        ),
    )

    package = fetch_report(key="k").report.packages[0]

    assert package.remaining_irt == 12000.5
    assert package.spendable is True


def test_a_main_balance_that_arrives_as_a_string_still_parses(monkeypatch):
    stub_get(monkeypatch, FakeResponse({"remaining_irt": "1000"}))

    assert fetch_report(key="k").report.main_balance_irt == 1000.0


@pytest.mark.parametrize(
    ("package", "expected"),
    [
        ({"template_id": "d-1"}, "daily"),
        ({"template_id": "w-2"}, "weekly"),
        ({"name": "وایب کُدر روزانه پایه"}, "daily"),
        ({"name": "وایب کُدر هفتگی پایه"}, "weekly"),
        ({"template_id": "x-9", "name": "چیز دیگری"}, "other"),
    ],
)
def test_tier_of_maps_the_template_and_the_name(package, expected):
    assert tier_of(package) == expected


def test_the_spendable_rules(monkeypatch):
    stub_get(
        monkeypatch,
        FakeResponse(
            {
                "credit_sources": {
                    "packages": [
                        # Empty, so not spendable however far off its end date is.
                        {"template_id": "d-1", "remaining_irt": "0", "end_date": "2099-01-01T00:00:00Z"},
                        # A balance left on a lapsed package is not spendable.
                        {"template_id": "d-2", "remaining_irt": "100", "end_date": "2000-01-01T00:00:00Z"},
                        # No end date at all, and a positive remaining: spendable.
                        {"template_id": "d-3", "remaining_irt": "100"},
                    ]
                }
            }
        ),
    )

    packages = fetch_report(key="k").report.packages

    assert [package.spendable for package in packages] == [False, False, True]


def test_two_live_daily_packages_add_up(monkeypatch):
    stub_get(
        monkeypatch,
        FakeResponse(
            {
                "credit_sources": {
                    "packages": [
                        {"template_id": "d-1", "remaining_irt": "12000"},
                        {"template_id": "d-2", "remaining_irt": "8000"},
                    ]
                }
            }
        ),
    )

    report = fetch_report(key="k").report

    assert report.tier_remaining["daily"] == 20000


def test_a_spendable_package_of_another_tier_is_not_summed_in(monkeypatch):
    stub_get(
        monkeypatch,
        FakeResponse(
            {
                "credit_sources": {
                    "packages": [
                        {"template_id": "d-1", "remaining_irt": "12000"},
                        {"template_id": "w-1", "remaining_irt": "999999"},
                        {"template_id": "d-9", "remaining_irt": "500", "end_date": "2000-01-01T00:00:00Z"},
                    ]
                }
            }
        ),
    )

    report = fetch_report(key="k").report

    assert report.tier_remaining == {"daily": 12000, "weekly": 999999, "other": 0}


def test_daily_is_active_even_when_weekly_holds_more(monkeypatch):
    stub_get(
        monkeypatch,
        FakeResponse(
            {
                "credit_sources": {
                    "packages": [
                        {"template_id": "d-1", "remaining_irt": "100"},
                        {"template_id": "w-1", "remaining_irt": "999999"},
                    ]
                }
            }
        ),
    )

    report = fetch_report(key="k").report

    assert report.active_tier == "daily"
    assert report.active_remaining_irt == 100


def test_weekly_is_active_when_daily_is_empty(monkeypatch):
    stub_get(
        monkeypatch,
        FakeResponse(
            {
                "credit_sources": {
                    "packages": [
                        {"template_id": "d-1", "remaining_irt": "0"},
                        {"template_id": "w-1", "remaining_irt": "500"},
                    ]
                }
            }
        ),
    )

    report = fetch_report(key="k").report

    assert report.active_tier == "weekly"
    assert report.active_remaining_irt == 500


def test_no_live_tier_is_none(monkeypatch):
    stub_get(
        monkeypatch,
        FakeResponse(
            {
                "remaining_irt": 0,
                "credit_sources": {
                    "packages": [{"template_id": "d-1", "remaining_irt": "100", "end_date": "2000-01-01T00:00:00Z"}]
                },
            }
        ),
    )

    report = fetch_report(key="k").report

    assert report.active_tier is None


def test_the_main_balance_is_the_answer_when_no_tier_is_live(monkeypatch):
    stub_get(monkeypatch, FakeResponse({"remaining_irt": 700, "credit_sources": {"packages": []}}))

    report = fetch_report(key="k").report

    assert report.active_tier is None
    assert report.active_remaining_irt == 700


def test_an_unreadable_balance_is_none_and_never_zero(monkeypatch):
    """The owner's rule: "I cannot tell" must not read as "the credit is gone"."""
    stub_get(monkeypatch, FakeResponse({"credit_sources": {"packages": []}}))

    report = fetch_report(key="k").report

    assert report.main_balance_irt is None
    assert report.active_tier is None
    assert report.active_remaining_irt is None


def test_a_main_balance_that_is_not_a_number_is_none(monkeypatch):
    stub_get(monkeypatch, FakeResponse({"remaining_irt": "not a number"}))

    assert fetch_report(key="k").report.active_remaining_irt is None


def test_a_transport_failure_is_a_read_error(monkeypatch):
    def failing_get(url, headers=None, timeout=None):
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "get", failing_get)

    read = fetch_report(key="k")

    assert read.report is None
    assert read.error


def test_a_non_json_body_is_a_read_error(monkeypatch):
    stub_get(monkeypatch, FakeResponse(ValueError("Expecting value: line 1 column 1")))

    read = fetch_report(key="k")

    assert read.report is None
    assert read.error


def test_a_body_that_is_not_an_object_is_a_read_error(monkeypatch):
    stub_get(monkeypatch, FakeResponse(["unexpected"]))

    read = fetch_report(key="k")

    assert read.report is None
    assert read.error


def test_a_package_that_is_not_an_object_is_skipped(monkeypatch):
    stub_get(
        monkeypatch,
        FakeResponse(
            {
                "credit_sources": {
                    "packages": [
                        "not a package",
                        {"template_id": "d-1", "remaining_irt": "10"},
                    ]
                }
            }
        ),
    )

    report = fetch_report(key="k").report

    assert len(report.packages) == 1
    assert report.tier_remaining["daily"] == 10
