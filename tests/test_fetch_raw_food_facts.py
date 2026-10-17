"""Kiểm thử crawler: giới hạn tốc độ, retry, trường xin về, ghi tệp, xử lý lỗi."""
import gzip
import json

import pytest
import requests

import src.fetch_raw_food_facts as fetch
from src.raw_audit import PII_FIELDS


class FakeResponse:
    def __init__(self, status_code=200, products=None, count=0, url="https://example.test/search"):
        self.status_code = status_code
        self._products = products or []
        self._count = count
        self.url = url

    def json(self):
        return {"products": self._products, "count": self._count}


class FakeSession:
    """Trả lần lượt các phản hồi đã chuẩn bị; ghi lại tham số mỗi lần gọi."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def products(n, start=0):
    return [{"code": f"{start + i:013d}", "nutriscore_grade": "a"} for i in range(n)]


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(fetch.time, "sleep", lambda s: calls.append(s))
    return calls


def read_records(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# --------------------------------------------------------------------------- cấu hình
def test_min_delay_respects_search_rate_limit():
    # Search API: 10 request/phút -> tối thiểu 6 giây mỗi request
    assert fetch.MIN_DELAY >= 6.0


def test_fields_exclude_personal_data():
    assert not (set(fetch.FIELDS) & PII_FIELDS)


def test_fields_include_what_scheme_a_needs():
    needed = {"code", "ingredients_tags", "additives_tags", "categories_tags",
              "nova_group", "nutriscore_grade", "brands_tags", "countries_tags"}
    assert needed <= set(fetch.FIELDS)


def test_user_agent_is_not_the_fake_placeholder_email():
    assert "contact@student.university.edu" not in fetch.USER_AGENT


def test_session_has_retry_policy_and_user_agent():
    s = fetch.create_robust_session()
    retry = s.get_adapter("https://world.openfoodfacts.org").max_retries
    assert retry.total == 5
    assert {429, 500, 502, 503, 504} <= set(retry.status_forcelist)
    assert retry.backoff_factor == 1.5
    assert s.headers["User-Agent"] == fetch.USER_AGENT
    assert s.headers["Accept"] == "application/json"


# --------------------------------------------------------------------------- fetch_one_filter
def test_stops_exactly_at_target_across_pages(tmp_path, sleeps):
    session = FakeSession([FakeResponse(products=products(3), count=99),
                           FakeResponse(products=products(3, 3), count=99)])
    out = tmp_path / "out.jsonl.gz"
    with gzip.open(out, "wt", encoding="utf-8") as gz:
        n = fetch.fetch_one_filter(session, gz, {"nutrition_grades_tags": "a"}, target=5, page_size=3, delay=7.0)
    assert n == 5
    assert len(read_records(out)) == 5
    assert len(session.calls) == 2


def test_pages_increment_and_params_are_sent(tmp_path, sleeps):
    session = FakeSession([FakeResponse(products=products(2)), FakeResponse(products=products(2, 2))])
    with gzip.open(tmp_path / "o.gz", "wt", encoding="utf-8") as gz:
        fetch.fetch_one_filter(session, gz, {"countries_tags_en": "vietnam"}, target=4, page_size=2, delay=7.0)
    p1, p2 = session.calls[0]["params"], session.calls[1]["params"]
    assert (p1["page"], p2["page"]) == (1, 2)
    assert p1["page_size"] == 2
    assert p1["countries_tags_en"] == "vietnam"
    assert p1["fields"] == ",".join(fetch.FIELDS)
    assert session.calls[0]["timeout"] == 30


def test_sleeps_between_requests_with_given_delay(tmp_path, sleeps):
    session = FakeSession([FakeResponse(products=products(2)), FakeResponse(products=products(2, 2))])
    with gzip.open(tmp_path / "o.gz", "wt", encoding="utf-8") as gz:
        fetch.fetch_one_filter(session, gz, {}, target=4, page_size=2, delay=7.0)
    assert sleeps and all(s == 7.0 for s in sleeps)


def test_record_wraps_payload_with_metadata(tmp_path, sleeps):
    session = FakeSession([FakeResponse(products=products(1), url="https://x.test/q?page=1")])
    out = tmp_path / "o.gz"
    with gzip.open(out, "wt", encoding="utf-8") as gz:
        fetch.fetch_one_filter(session, gz, {"nutrition_grades_tags": "e"}, target=1, page_size=1, delay=7.0)
    rec = read_records(out)[0]
    assert rec["raw_payload"]["code"] == "0000000000000"  # giữ nguyên số 0 đầu
    meta = rec["_metadata"]
    assert meta["http_status"] == 200
    assert meta["page"] == 1
    assert meta["request_url"] == "https://x.test/q?page=1"
    assert meta["filters"] == {"nutrition_grades_tags": "e"}
    assert meta["source_endpoint"] == fetch.ENDPOINT
    assert meta["retrieved_at"]


def test_stops_on_empty_page(tmp_path, sleeps):
    session = FakeSession([FakeResponse(products=products(2)), FakeResponse(products=[])])
    with gzip.open(tmp_path / "o.gz", "wt", encoding="utf-8") as gz:
        n = fetch.fetch_one_filter(session, gz, {}, target=100, page_size=2, delay=7.0)
    assert n == 2


def test_stops_on_http_error_without_raising(tmp_path, sleeps):
    session = FakeSession([FakeResponse(status_code=429)])
    with gzip.open(tmp_path / "o.gz", "wt", encoding="utf-8") as gz:
        n = fetch.fetch_one_filter(session, gz, {}, target=10, page_size=2, delay=7.0)
    assert n == 0


def test_stops_on_network_error_without_raising(tmp_path, sleeps):
    session = FakeSession([requests.exceptions.ConnectionError("down")])
    with gzip.open(tmp_path / "o.gz", "wt", encoding="utf-8") as gz:
        n = fetch.fetch_one_filter(session, gz, {}, target=10, page_size=2, delay=7.0)
    assert n == 0


def test_vietnamese_text_is_not_escaped(tmp_path, sleeps):
    item = {"code": "1", "product_name": "Bánh gạo vị ngọt"}
    session = FakeSession([FakeResponse(products=[item])])
    out = tmp_path / "o.gz"
    with gzip.open(out, "wt", encoding="utf-8") as gz:
        fetch.fetch_one_filter(session, gz, {}, target=1, page_size=1, delay=7.0)
    with gzip.open(out, "rt", encoding="utf-8") as f:
        assert "Bánh gạo vị ngọt" in f.read()


# --------------------------------------------------------------------------- main()
@pytest.fixture
def run_main(monkeypatch, tmp_path):
    (tmp_path / "data" / "raw").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    seen = []

    def fake_fetch(session, gz, filters, target, page_size, delay):
        seen.append({"filters": filters, "target": target, "page_size": page_size, "delay": delay})
        return 0

    monkeypatch.setattr(fetch, "fetch_one_filter", fake_fetch)

    def _run(*argv):
        monkeypatch.setattr("sys.argv", ["fetch_raw_food_facts.py", *argv])
        fetch.main()
        return seen
    return _run


def test_main_enforces_minimum_delay(run_main):
    seen = run_main("--delay", "0.5")
    assert seen[0]["delay"] == fetch.MIN_DELAY


def test_main_keeps_larger_delay(run_main):
    seen = run_main("--delay", "12")
    assert seen[0]["delay"] == 12.0


def test_main_runs_once_per_grade(run_main):
    seen = run_main("--grades", "a, e")
    assert [s["filters"]["nutrition_grades_tags"] for s in seen] == ["a", "e"]


def test_main_without_grades_runs_a_single_unfiltered_pass(run_main):
    seen = run_main()
    assert len(seen) == 1
    assert "nutrition_grades_tags" not in seen[0]["filters"]


def test_main_country_filter_has_no_en_prefix_by_default(run_main):
    seen = run_main("--country", "vietnam")
    assert seen[0]["filters"]["countries_tags_en"] == "vietnam"


def test_main_creates_output_file_in_data_raw(run_main, tmp_path):
    run_main()
    files = list((tmp_path / "data" / "raw").glob("raw_products_*.jsonl.gz"))
    assert len(files) == 1
