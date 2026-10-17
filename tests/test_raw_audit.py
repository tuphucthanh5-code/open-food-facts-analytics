"""Kiểm thử bước kiểm toán dữ liệu thô."""
import gzip
import json

import pytest

from src import raw_audit as ra
from tests.helpers import make_payload as mp


# --------------------------------------------------------------------------- hàm chuẩn hóa
@pytest.mark.parametrize("value,expected", [
    ("a", "a"), ("A", "a"), (" b ", "b"), ("E", "e"),
    ("unknown", None), ("not-applicable", None), ("", None), ("  ", None),
    ("f", None), (None, None), (3, None), (["a"], None),
])
def test_normalize_grade(value, expected):
    assert ra.normalize_grade(value) == expected


@pytest.mark.parametrize("value,expected", [
    (1, 1), (4, 4), ("3", 3), (" 2 ", 2), (4.0, 4),
    (0, None), (5, None), (-1, None), (2.5, None), ("x", None), (None, None), (True, None), ("", None),
])
def test_normalize_nova(value, expected):
    assert ra.normalize_nova(value) == expected


@pytest.mark.parametrize("value,absent,empty", [
    (None, True, False), ("", False, True), ("  ", False, True),
    ([], False, True), ({}, False, True),
    ("x", False, False), (["a"], False, False), (0, False, False), ({"a": 1}, False, False),
])
def test_absent_and_empty(value, absent, empty):
    assert ra.is_absent(value) is absent
    assert ra.is_empty(value) is empty
    assert ra.is_missing(value) is (absent or empty)


def test_find_leakage_fields():
    keys = ["code", "ingredients_tags", "nutriments", "nutriscore_grade", "nutriscore_score",
            "nutrition-score-fr_100g", "nutrition_grades_tags", "nutrient_levels_tags",
            "misc_tags", "states_tags", "data_quality_tags", "nova_group", "additives_tags"]
    found = ra.find_leakage_fields(keys)
    assert set(found) == {"nutriments", "nutriscore_grade", "nutriscore_score",
                          "nutrition-score-fr_100g", "nutrition_grades_tags", "nutrient_levels_tags",
                          "misc_tags", "states_tags", "data_quality_tags"}
    assert "ingredients_tags" not in found and "nova_group" not in found


def test_scheme_a_features_are_never_flagged_as_leakage():
    for k in ("ingredients_tags", "additives_tags", "categories_tags", "nova_group",
              "pnns_groups_1", "allergens_tags", "labels_tags", "brands_tags"):
        assert ra.find_leakage_fields([k]) == []


def test_find_pii_fields():
    assert ra.find_pii_fields(["creator", "code", "last_editor", "editors_tags"]) == \
        ["creator", "editors_tags", "last_editor"]


def test_find_nutriscore_fields():
    assert ra.find_nutriscore_fields(["nutriscore_grade", "nutriscore_version", "nova_group"]) == \
        ["nutriscore_grade", "nutriscore_version"]


# --------------------------------------------------------------------------- đọc tệp
def test_iter_jsonl_yields_payloads_and_counts_malformed(write_jsonl_gz):
    path = write_jsonl_gz([mp(code="1"), mp(code="2")], extra_lines=["{khong phai json", "", '"chuoi"'])
    stats = {}
    got = list(ra.iter_jsonl(path, stats))
    assert [p["code"] for p in got] == ["1", "2"]
    assert stats["malformed_lines"] == 2          # dòng hỏng + dòng JSON không phải đối tượng


def test_iter_payloads_reads_all_matching_files(tmp_path, write_jsonl_gz):
    write_jsonl_gz([mp(code="1")], name="raw_a.jsonl.gz")
    write_jsonl_gz([mp(code="2"), mp(code="3")], name="raw_b.jsonl.gz")
    codes = [p["code"] for p in ra.iter_payloads(str(tmp_path / "*.jsonl.gz"))]
    assert codes == ["1", "2", "3"]


# --------------------------------------------------------------------------- audit_records
def sample_payloads():
    return [
        mp(code="0000001", grade="a", nova=1, countries=("en:france",), brand="b1"),
        mp(code="0000002", grade="B", nova=3, countries=("en:france", "en:belgium"), brand="b1"),
        mp(code="0000003", grade="e", nova=4, countries=("en:vietnam",), brand="b2"),
        mp(code="0000004", grade="unknown", nova=4),                         # nhãn không hợp lệ
        mp(code="0000005", grade=None, nova=2),                              # thiếu nhãn
        mp(code="0000006", grade="c", ingredients=()),                       # có nhãn, không thành phần
        mp(code="0000007", grade="d", nova=None, ingredients=("fr:sucre",)), # thiếu NOVA, thẻ không phải en:
        mp(code="0000001", grade="a", nova=1),                               # trùng mã vạch
    ]


def test_counts_total_labeled_and_usable():
    s = ra.audit_records(sample_payloads())
    assert s["total"] == 8
    assert s["labeled"] == 6          # a, B, e, c, d, a
    assert s["usable"] == 5           # trừ bản ghi không có thành phần


def test_grade_distribution_normalizes_case_and_separates_usable():
    s = ra.audit_records(sample_payloads())
    assert s["labeled_grades"] == {"a": 2, "b": 1, "c": 1, "d": 1, "e": 1}
    assert s["usable_grades"] == {"a": 2, "b": 1, "c": 0, "d": 1, "e": 1}


def test_raw_grade_distribution_keeps_odd_values():
    raw = dict(map(tuple, ra.audit_records(sample_payloads())["grade_raw"]))
    assert raw["unknown"] == 1
    assert raw["(thiếu)"] == 1
    assert raw["a"] == 2 and raw["b"] == 1


def test_duplicate_codes_are_counted():
    c = ra.audit_records(sample_payloads())["code"]
    assert c["unique"] == 7
    assert c["duplicate_records"] == 1


def test_barcode_quality_counters():
    payloads = [mp(code="0123"), mp(code="ABC12"), mp(code=456), mp(code=None), mp(code="  ")]
    c = ra.audit_records(payloads)["code"]
    assert c["missing"] == 2
    assert c["leading_zero"] == 1
    assert c["non_digit"] == 1
    assert c["non_string"] == 1


def test_nova_coverage_only_among_usable():
    s = ra.audit_records(sample_payloads())
    assert s["usable_with_nova"] == 4          # bản ghi 0000007 thiếu NOVA
    assert s["grade_by_nova"]["a"]["1"] == 2
    assert s["grade_by_nova"]["e"]["4"] == 1
    assert s["grade_by_nova"]["d"] == {"1": 0, "2": 0, "3": 0, "4": 0}


def test_countries_are_exploded_among_usable():
    s = ra.audit_records(sample_payloads())
    countries = dict(map(tuple, s["countries_usable"]))
    assert countries["en:france"] == 4
    assert countries["en:belgium"] == 1
    assert countries["en:vietnam"] == 1


def test_brand_concentration():
    s = ra.audit_records([mp(brand="x")] * 3 + [mp(brand="y")])
    assert s["brands"]["unique"] == 2
    assert s["brands"]["top_share"] == pytest.approx(0.75)


def test_missing_brand_is_grouped_under_placeholder():
    s = ra.audit_records([mp(brand=None)])
    assert s["brands"]["top"][0][0] == "(thiếu)"


def test_en_prefix_share_and_ingredient_lengths():
    s = ra.audit_records([mp(ingredients=("en:a", "en:b", "fr:c", "fr:d")), mp(ingredients=("en:a",))])
    assert s["ingredients"]["en_prefix_share"] == pytest.approx(3 / 5)
    assert s["ingredients"]["mean_n"] == pytest.approx(2.5)
    assert s["ingredients"]["share_le1"] == pytest.approx(0.5)


def test_missing_rates_distinguish_absent_from_empty():
    payloads = [mp(additives_tags=[]), mp(additives_tags=["en:e330"]), mp()]   # [] vs có vs vắng
    f = ra.audit_records(payloads)["fields"]["additives_tags"]
    assert f["absent_all"] == 1
    assert f["missing_all"] == 2


def test_missing_labeled_counts_only_labeled_records():
    payloads = [mp(grade="a", categories_tags=[]), mp(grade=None, categories_tags=[])]
    f = ra.audit_records(payloads)["fields"]["categories_tags"]
    assert f["missing_all"] == 2
    assert f["missing_labeled"] == 1


def test_detects_leakage_pii_and_nutriscore_fields():
    s = ra.audit_records([mp(creator="someone", nutriscore_score=12, nutrient_levels_tags=["x"])])
    assert "creator" in s["pii_fields_present"]
    assert {"nutriments", "nutriscore_grade", "nutriscore_score", "nutrient_levels_tags"} <= \
        set(s["leakage_fields_present"])
    assert "nutriscore_score" in s["nutriscore_related_fields"]


def test_empty_input_does_not_crash():
    s = ra.audit_records([])
    assert s["total"] == 0 and s["usable"] == 0
    assert s["brands"]["top_share"] == 0.0
    assert s["ingredients"]["mean_n"] == 0.0


def test_summary_is_json_serializable():
    json.dumps(ra.audit_records(sample_payloads()), ensure_ascii=False)


# --------------------------------------------------------------------------- evaluate_checks
def status_of(checks, fragment):
    return next(c["status"] for c in checks if fragment in c["name"])


def test_pii_present_is_a_failure():
    s = ra.audit_records([mp(creator="x")])
    assert status_of(ra.evaluate_checks(s), "trường cá nhân") == "FAIL"


def test_no_data_is_a_failure():
    assert status_of(ra.evaluate_checks(ra.audit_records([])), "Có dữ liệu") == "FAIL"


def test_small_dataset_warns_about_usable_count_and_class_size():
    checks = ra.evaluate_checks(ra.audit_records(sample_payloads()))
    assert status_of(checks, "dùng được") == "WARN"
    assert status_of(checks, "đủ mẫu") == "WARN"


def test_duplicates_warn():
    checks = ra.evaluate_checks(ra.audit_records(sample_payloads()))
    assert status_of(checks, "Trùng mã vạch") == "WARN"


def test_healthy_dataset_has_no_warn_or_fail():
    payloads = []
    for i in range(500):
        payloads.append(mp(code=f"{i:013d}", grade="abcde"[i % 5], nova=(i % 4) + 1,
                           brand=f"brand{i % 50}", countries=("en:france",)))
    checks = ra.evaluate_checks(ra.audit_records(payloads), min_usable=400, min_class=50)
    bad = [c for c in checks if c["status"] in ("WARN", "FAIL")]
    assert bad == [], bad


def test_brand_concentration_warns_when_one_brand_dominates():
    payloads = [mp(code=f"{i:013d}", brand="big") for i in range(10)]
    checks = ra.evaluate_checks(ra.audit_records(payloads), max_brand_share=0.10)
    assert status_of(checks, "thương hiệu") == "WARN"


def test_low_nova_coverage_warns():
    payloads = [mp(code=f"{i:013d}", nova=None) for i in range(10)]
    assert status_of(ra.evaluate_checks(ra.audit_records(payloads)), "NOVA") == "WARN"


def test_every_check_has_valid_status():
    for c in ra.evaluate_checks(ra.audit_records(sample_payloads())):
        assert c["status"] in {"OK", "WARN", "FAIL", "INFO"}
        assert c["name"] and c["detail"]


# --------------------------------------------------------------------------- báo cáo
def test_markdown_contains_key_sections_and_numbers():
    s = ra.audit_records(sample_payloads())
    md = ra.render_markdown(s, ra.evaluate_checks(s), source="test", generated_at="2026-01-01")
    for heading in ("# Báo cáo kiểm toán dữ liệu thô", "## 1. Kết quả các kiểm tra",
                    "## 3. Phân bố hạng A-E", "## 9. Tỷ lệ thiếu theo trường"):
        assert heading in md
    assert "Tổng bản ghi: **8**" in md
    assert "Dùng được (nhãn hợp lệ + có thành phần): **5**" in md


def test_markdown_escapes_pipe_in_names():
    s = ra.audit_records([mp(brand="a|b")])
    assert "a/b" in ra.render_markdown(s, ra.evaluate_checks(s))


def test_write_reports_creates_both_files(tmp_path):
    s = ra.audit_records(sample_payloads())
    md, js = ra.write_reports(s, ra.evaluate_checks(s), str(tmp_path / "out" / "audit"), "src", "t")
    assert (tmp_path / "out" / "audit.md").read_text(encoding="utf-8").startswith("# Báo cáo")
    data = json.loads((tmp_path / "out" / "audit.json").read_text(encoding="utf-8"))
    assert data["summary"]["total"] == 8 and data["checks"]


# --------------------------------------------------------------------------- dòng lệnh
def test_main_end_to_end(tmp_path, write_jsonl_gz, capsys):
    write_jsonl_gz(sample_payloads())
    out = tmp_path / "rep" / "audit"
    rc = ra.main(["--pattern", str(tmp_path / "*.jsonl.gz"), "--out", str(out)])
    assert rc == 0
    assert (tmp_path / "rep" / "audit.md").exists()
    assert (tmp_path / "rep" / "audit.json").exists()
    assert "dùng được 5" in capsys.readouterr().out


def test_main_reports_malformed_lines(tmp_path, write_jsonl_gz):
    write_jsonl_gz(sample_payloads(), extra_lines=["{hong"])
    out = tmp_path / "audit"
    ra.main(["--pattern", str(tmp_path / "*.jsonl.gz"), "--out", str(out)])
    data = json.loads((tmp_path / "audit.json").read_text(encoding="utf-8"))
    assert data["summary"]["malformed_lines"] == 1


def test_main_without_files_returns_error(tmp_path, capsys):
    rc = ra.main(["--pattern", str(tmp_path / "none*.jsonl.gz"), "--out", str(tmp_path / "x")])
    assert rc == 1
    assert "Không tìm thấy" in capsys.readouterr().out
    assert not (tmp_path / "x.md").exists()


def test_main_with_empty_file_returns_error(tmp_path):
    with gzip.open(tmp_path / "empty.jsonl.gz", "wt", encoding="utf-8"):
        pass
    assert ra.main(["--pattern", str(tmp_path / "*.jsonl.gz"), "--out", str(tmp_path / "x")]) == 1


# ---------------------------------------------------------------- sửa lỗi: "(thiếu)" không phải thương hiệu
def test_missing_brand_does_not_count_as_top_brand():
    payloads = [mp(code=f"{i:013d}", brand=None) for i in range(15)]
    payloads += [mp(code=f"9{i:012d}", brand=f"b{i}") for i in range(85)]
    s = ra.audit_records(payloads)
    assert s["brands"]["top_share"] == pytest.approx(0.01)
    assert s["brands"]["missing_share"] == pytest.approx(0.15)
    assert s["brands"]["unique"] == 85
    checks = {c["name"]: c for c in ra.evaluate_checks(s)}
    assert checks["Mức tập trung thương hiệu"]["status"] == "OK"
    assert "15.0%" in checks["Thiếu thương hiệu"]["detail"]


def test_all_brands_missing_gives_zero_concentration():
    s = ra.audit_records([mp(code=f"{i:013d}", brand=None) for i in range(5)])
    assert s["brands"]["top_share"] == 0.0
    assert s["brands"]["missing_share"] == 1.0
