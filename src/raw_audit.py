"""Bước 2 - Kiểm toán dữ liệu thô (raw audit).

Đọc dữ liệu thô (tệp .jsonl.gz hoặc bảng raw_products trong PostgreSQL) và trả lời:
  - Có bao nhiêu bản ghi, bao nhiêu có nhãn hợp lệ, bao nhiêu DÙNG ĐƯỢC cho Phương án A
    (nhãn hợp lệ + có danh sách thành phần)?
  - Nhãn A-E có cân bằng không? Quốc gia, thương hiệu, ngôn ngữ phân bố ra sao?
  - Trường nào thiếu nhiều? Có trường rò rỉ nhãn hoặc trường cá nhân nào trong dữ liệu thô không?

Chạy từ thư mục gốc dự án:
    python -m src.raw_audit                       # đọc data/raw/*.jsonl.gz
    python -m src.raw_audit --source db           # đọc bảng raw_products trong PostgreSQL

Kết quả: reports/raw_audit.md và reports/raw_audit.json
Module chỉ dùng thư viện chuẩn của Python nên dễ kiểm thử.
"""
import argparse
import glob
import gzip
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from statistics import median

VALID_GRADES = ("a", "b", "c", "d", "e")

# --- Cột bị cấm làm đặc trưng (Phương án A) -------------------------------------------
LEAKAGE_EXACT = frozenset({
    "nutriments",
    "nutrient_levels",
    "nutrient_levels_tags",
    "misc_tags",
    "states_tags",
    "data_quality_tags",
})
LEAKAGE_PREFIXES = ("nutriscore", "nutrition-score", "nutrition_score", "nutrition_grade")

# --- Trường cá nhân: không được thu thập (mục Đạo đức) --------------------------------
PII_FIELDS = frozenset({
    "creator", "editors_tags", "last_editor", "correctors_tags",
    "photographers_tags", "informers_tags", "checkers_tags",
})

# --- Các trường cốt lõi cần thống kê tỷ lệ thiếu ---------------------------------------
CORE_FIELDS = (
    "code", "product_name", "brands_tags", "countries_tags", "categories_tags",
    "pnns_groups_1", "pnns_groups_2", "ingredients_text", "ingredients_tags",
    "ingredients_n", "ingredients_analysis_tags", "additives_tags", "additives_n",
    "allergens_tags", "labels_tags", "nova_group", "nutriscore_grade",
    "nutriments", "last_modified_t", "lang",
)


# ======================================================================================
# Hàm nhỏ, thuần
# ======================================================================================
def normalize_grade(value):
    """Chuẩn hóa nhãn về a-e (chữ thường). Giá trị khác (unknown, not-applicable, rỗng) -> None."""
    if not isinstance(value, str):
        return None
    g = value.strip().lower()
    return g if g in VALID_GRADES else None


def normalize_nova(value):
    """Chuẩn hóa nhóm NOVA về số nguyên 1-4, ngoài khoảng đó hoặc không phải số -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 4 else None


def is_absent(value):
    """Trường vắng mặt: khóa không có hoặc giá trị None."""
    return value is None


def is_empty(value):
    """Trường có mặt nhưng rỗng: chuỗi trắng, list/dict rỗng."""
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False


def is_missing(value):
    return is_absent(value) or is_empty(value)


def find_leakage_fields(keys):
    """Các khóa là nhãn hoặc suy ra từ bảng dinh dưỡng -> phải loại khỏi đặc trưng."""
    return sorted(k for k in keys if k in LEAKAGE_EXACT or k.startswith(LEAKAGE_PREFIXES))


def find_pii_fields(keys):
    return sorted(k for k in keys if k in PII_FIELDS)


def find_nutriscore_fields(keys):
    """Các khóa liên quan Nutri-Score (để người dùng tự xem có trường phiên bản công thức không)."""
    return sorted(k for k in keys if k.startswith("nutriscore"))


def pct(n, d):
    return (100.0 * n / d) if d else 0.0


def top_items(counter, n):
    return [[k, v] for k, v in counter.most_common(n)]


# ======================================================================================
# Nguồn dữ liệu
# ======================================================================================
def iter_jsonl(path, stats=None):
    """Sinh từng raw_payload từ một tệp .jsonl.gz. Bỏ qua dòng trống, đếm dòng hỏng."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                if stats is not None:
                    stats["malformed_lines"] = stats.get("malformed_lines", 0) + 1
                continue
            payload = rec.get("raw_payload") if isinstance(rec, dict) else None
            if isinstance(payload, dict):
                yield payload
            elif stats is not None:
                stats["malformed_lines"] = stats.get("malformed_lines", 0) + 1


def iter_payloads(pattern, stats=None):
    for path in sorted(glob.glob(pattern)):
        yield from iter_jsonl(path, stats)


DB_PAYLOAD_QUERY = "SELECT payload FROM {table} ORDER BY id"


def iter_db(table="raw_products"):
    """Đọc cột payload từ PostgreSQL bằng con trỏ phía máy chủ (không nạp hết vào RAM).

    ORDER BY id để thứ tự đọc cố định giữa các lần chạy: staging dùng thứ tự này làm row_id,
    nếu không có thì PostgreSQL được phép trả dòng theo thứ tự vật lý bất kỳ và row_id sẽ đổi."""
    import psycopg2
    from dotenv import load_dotenv

    load_dotenv()
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "food_facts_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.environ["DB_PASSWORD"],
    )
    try:
        with conn.cursor(name="raw_audit_cursor") as cur:
            cur.itersize = 2000
            cur.execute(DB_PAYLOAD_QUERY.format(table=table))
            for (payload,) in cur:
                if isinstance(payload, dict):
                    yield payload
    finally:
        conn.close()


# ======================================================================================
# Kiểm toán
# ======================================================================================
def audit_records(payloads, top_n=15):
    """Quét một lượt qua các payload và trả về dict thống kê (không phụ thuộc pandas)."""
    total = 0
    codes = Counter()
    code_missing = code_leading_zero = code_non_digit = code_non_string = 0

    grade_raw = Counter()
    labeled = usable = usable_nova = 0
    labeled_grades = Counter()
    usable_grades = Counter()
    grade_by_nova = {g: Counter() for g in VALID_GRADES}

    absent_all = Counter()
    missing_all = Counter()
    missing_lab = Counter()

    keys_seen = Counter()
    countries_all = Counter()
    countries_usable = Counter()
    lang_usable = Counter()
    brands_usable = Counter()
    ing_lengths = []
    ing_tags_total = ing_tags_en = 0

    for p in payloads:
        total += 1
        keys_seen.update(p.keys())

        # --- mã vạch
        code = p.get("code")
        if code is None or (isinstance(code, str) and not code.strip()):
            code_missing += 1
        else:
            if not isinstance(code, str):
                code_non_string += 1
            s = str(code).strip()
            codes[s] += 1
            if s.startswith("0"):
                code_leading_zero += 1
            if not s.isdigit():
                code_non_digit += 1

        # --- nhãn
        raw = p.get("nutriscore_grade")
        grade_raw["(thiếu)" if raw is None else (str(raw).strip().lower() or "(chuỗi rỗng)")] += 1
        grade = normalize_grade(raw)

        # --- thiếu theo trường
        for field in CORE_FIELDS:
            v = p.get(field)
            if is_absent(v):
                absent_all[field] += 1
            if is_missing(v):
                missing_all[field] += 1
                if grade:
                    missing_lab[field] += 1

        for c in (p.get("countries_tags") or []):
            countries_all[c] += 1

        if not grade:
            continue
        labeled += 1
        labeled_grades[grade] += 1

        ing = p.get("ingredients_tags")
        if not (isinstance(ing, list) and ing):
            continue

        # --- bản ghi DÙNG ĐƯỢC: nhãn hợp lệ + có thành phần
        usable += 1
        usable_grades[grade] += 1
        ing_lengths.append(len(ing))
        ing_tags_total += len(ing)
        ing_tags_en += sum(1 for t in ing if isinstance(t, str) and t.startswith("en:"))

        nova = normalize_nova(p.get("nova_group"))
        if nova:
            usable_nova += 1
            grade_by_nova[grade][nova] += 1

        for c in (p.get("countries_tags") or []):
            countries_usable[c] += 1
        if p.get("lang"):
            lang_usable[p["lang"]] += 1
        bt = p.get("brands_tags")
        brands_usable[bt[0] if isinstance(bt, list) and bt else "(thiếu)"] += 1

    total_with_code = total - code_missing
    # Thương hiệu "(thiếu)" KHÔNG phải một thương hiệu: loại ra khi đo mức tập trung, báo riêng tỷ lệ thiếu.
    named_brands = Counter({b: n for b, n in brands_usable.items() if b != "(thiếu)"})
    top_brand_share = (named_brands.most_common(1)[0][1] / usable) if usable and named_brands else 0.0
    brand_missing_share = (brands_usable["(thiếu)"] / usable) if usable else 0.0
    top_country_share = (countries_usable.most_common(1)[0][1] / usable) if usable else 0.0

    all_keys = list(keys_seen)
    return {
        "total": total,
        "code": {
            "missing": code_missing,
            "unique": len(codes),
            "duplicate_records": total_with_code - len(codes),
            "leading_zero": code_leading_zero,
            "non_digit": code_non_digit,
            "non_string": code_non_string,
        },
        "grade_raw": top_items(grade_raw, 20),
        "labeled": labeled,
        "labeled_grades": {g: labeled_grades[g] for g in VALID_GRADES},
        "usable": usable,
        "usable_grades": {g: usable_grades[g] for g in VALID_GRADES},
        "usable_with_nova": usable_nova,
        "grade_by_nova": {g: {str(n): grade_by_nova[g][n] for n in (1, 2, 3, 4)} for g in VALID_GRADES},
        "countries_all_unique": len(countries_all),
        "countries_usable_unique": len(countries_usable),
        "countries_usable": top_items(countries_usable, top_n),
        "top_country_share": top_country_share,
        "lang_usable": top_items(lang_usable, top_n),
        "brands": {
            "unique": len(named_brands),
            "top": top_items(brands_usable, top_n),
            "top_share": top_brand_share,
            "missing_share": brand_missing_share,
        },
        "ingredients": {
            "mean_n": (sum(ing_lengths) / len(ing_lengths)) if ing_lengths else 0.0,
            "median_n": median(ing_lengths) if ing_lengths else 0,
            "share_le1": (sum(1 for n in ing_lengths if n <= 1) / len(ing_lengths)) if ing_lengths else 0.0,
            "en_prefix_share": (ing_tags_en / ing_tags_total) if ing_tags_total else 0.0,
        },
        "fields": {
            f: {
                "absent_all": absent_all[f],
                "missing_all": missing_all[f],
                "missing_labeled": missing_lab[f],
            }
            for f in CORE_FIELDS
        },
        "keys_seen_count": len(all_keys),
        "leakage_fields_present": find_leakage_fields(all_keys),
        "pii_fields_present": find_pii_fields(all_keys),
        "nutriscore_related_fields": find_nutriscore_fields(all_keys),
    }


def evaluate_checks(summary, min_usable=10000, min_class=100, min_nova_share=0.5,
                    max_brand_share=0.10, min_en_prefix=0.90):
    """Biến thống kê thành các kiểm tra OK / WARN / FAIL / INFO kèm giải thích."""
    checks = []

    def add(name, status, detail):
        checks.append({"name": name, "status": status, "detail": detail})

    total, usable = summary["total"], summary["usable"]

    add("Có dữ liệu", "OK" if total > 0 else "FAIL", f"{total} bản ghi")

    dup = summary["code"]["duplicate_records"]
    add("Trùng mã vạch", "OK" if dup == 0 else "WARN",
        f"{dup} bản ghi trùng mã (xử lý ở bước cleaning)")

    add("Số bản ghi dùng được (nhãn hợp lệ + có thành phần)",
        "OK" if usable >= min_usable else "WARN",
        f"{usable} bản ghi, mục tiêu tối thiểu {min_usable}")

    smallest = min(summary["usable_grades"].values()) if usable else 0
    add("Mỗi hạng A-E đủ mẫu", "OK" if smallest >= min_class else "WARN",
        f"hạng ít nhất có {smallest} mẫu, ngưỡng {min_class}")

    nova_share = (summary["usable_with_nova"] / usable) if usable else 0.0
    add("Độ phủ NOVA", "OK" if nova_share >= min_nova_share else "WARN",
        f"{100 * nova_share:.1f}% bản ghi dùng được có nova_group hợp lệ (ngưỡng {100 * min_nova_share:.0f}%)")

    en_share = summary["ingredients"]["en_prefix_share"]
    add("Thẻ thành phần đã chuẩn hóa taxonomy (tiền tố en:)",
        "OK" if en_share >= min_en_prefix else "WARN",
        f"{100 * en_share:.1f}% thẻ có tiền tố en: (ngưỡng {100 * min_en_prefix:.0f}%)")

    top_brand = summary["brands"]["top_share"]
    add("Mức tập trung thương hiệu", "OK" if top_brand <= max_brand_share else "WARN",
        f"thương hiệu lớn nhất chiếm {100 * top_brand:.1f}% (ngưỡng {100 * max_brand_share:.0f}%), ảnh hưởng GroupKFold")
    add("Thiếu thương hiệu", "INFO",
        f"{100 * summary['brands'].get('missing_share', 0.0):.1f}% bản ghi dùng được không có thương hiệu "
        "-> không gộp chung thành một nhóm khi chia GroupKFold")

    add("Mức tập trung quốc gia", "INFO",
        f"quốc gia lớn nhất chiếm {100 * summary['top_country_share']:.1f}% bản ghi dùng được")

    pii = summary["pii_fields_present"]
    add("Không thu thập trường cá nhân", "OK" if not pii else "FAIL",
        "không có" if not pii else "đang có: " + ", ".join(pii) + " -> kiểm tra tham số fields của crawler")

    leak = summary["leakage_fields_present"]
    add("Trường rò rỉ nhãn có trong dữ liệu thô", "INFO",
        (", ".join(leak) if leak else "không có") + " -> phải loại ở bước staging, không đưa vào đặc trưng")

    ns = summary["nutriscore_related_fields"]
    add("Trường liên quan Nutri-Score (kiểm tra phiên bản công thức)", "INFO",
        ", ".join(ns) if ns else "không có")

    c = summary["code"]
    add("Mã vạch lưu dạng chuỗi", "OK" if c["non_string"] == 0 else "WARN",
        f"{c['non_string']} mã không phải chuỗi; {c['leading_zero']} mã bắt đầu bằng 0")
    return checks


# ======================================================================================
# Báo cáo
# ======================================================================================
def _cell(x):
    return str(x).replace("|", "/")


def _table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render_markdown(summary, checks, source="", generated_at=None):
    s = summary
    total = s["total"]
    lines = ["# Báo cáo kiểm toán dữ liệu thô", ""]
    if generated_at:
        lines.append(f"- Thời điểm: {generated_at}")
    if source:
        lines.append(f"- Nguồn: {source}")
    lines += [
        f"- Tổng bản ghi: **{total}**",
        f"- Có nhãn A-E hợp lệ: **{s['labeled']}** ({pct(s['labeled'], total):.1f}%)",
        f"- Dùng được (nhãn hợp lệ + có thành phần): **{s['usable']}** ({pct(s['usable'], total):.1f}%)",
        "", "## 1. Kết quả các kiểm tra", "",
        _table(["Kiểm tra", "Trạng thái", "Chi tiết"],
               [[c["name"], c["status"], c["detail"]] for c in checks]),
        "", "## 2. Phân bố nhãn gốc (trước khi chuẩn hóa)", "",
        _table(["Giá trị", "Số bản ghi"], s["grade_raw"]),
        "", "## 3. Phân bố hạng A-E", "",
        _table(["Hạng", "Có nhãn", "Dùng được"],
               [[g.upper(), s["labeled_grades"][g], s["usable_grades"][g]] for g in VALID_GRADES]),
        "", "## 4. Hạng theo NOVA (bản ghi dùng được)", "",
        _table(["Hạng", "NOVA 1", "NOVA 2", "NOVA 3", "NOVA 4"],
               [[g.upper()] + [s["grade_by_nova"][g][str(n)] for n in (1, 2, 3, 4)] for g in VALID_GRADES]),
        "", f"## 5. Quốc gia (bản ghi dùng được; tổng {s['countries_usable_unique']} quốc gia)", "",
        _table(["Quốc gia", "Số bản ghi"], s["countries_usable"]),
        "", "## 6. Ngôn ngữ (bản ghi dùng được)", "",
        _table(["Ngôn ngữ", "Số bản ghi"], s["lang_usable"]),
        "", f"## 7. Thương hiệu (bản ghi dùng được; {s['brands']['unique']} thương hiệu khác nhau)", "",
        _table(["Thương hiệu", "Số bản ghi"], s["brands"]["top"]),
        "", "## 8. Thành phần", "",
        f"- Số thành phần trung bình: {s['ingredients']['mean_n']:.1f}; trung vị: {s['ingredients']['median_n']}",
        f"- Tỷ lệ bản ghi chỉ có ≤ 1 thành phần: {100 * s['ingredients']['share_le1']:.1f}%",
        f"- Tỷ lệ thẻ có tiền tố en:: {100 * s['ingredients']['en_prefix_share']:.1f}%",
        "", "## 9. Tỷ lệ thiếu theo trường", "",
        _table(["Trường", "Vắng mặt (toàn bộ)", "Vắng hoặc rỗng (toàn bộ)", "Vắng hoặc rỗng (có nhãn)"],
               [[f, f"{pct(v['absent_all'], total):.1f}%", f"{pct(v['missing_all'], total):.1f}%",
                 f"{pct(v['missing_labeled'], s['labeled']):.1f}%"] for f, v in s["fields"].items()]),
        "", "## 10. Mã vạch", "",
        f"- Thiếu: {s['code']['missing']}; duy nhất: {s['code']['unique']}; bản ghi trùng: {s['code']['duplicate_records']}",
        f"- Bắt đầu bằng 0: {s['code']['leading_zero']}; chứa ký tự không phải số: {s['code']['non_digit']}; "
        f"không phải chuỗi: {s['code']['non_string']}",
        "", "## 11. Trường rò rỉ, trường cá nhân, trường Nutri-Score", "",
        f"- Rò rỉ nhãn: {', '.join(s['leakage_fields_present']) or 'không có'}",
        f"- Cá nhân: {', '.join(s['pii_fields_present']) or 'không có'}",
        f"- Liên quan Nutri-Score: {', '.join(s['nutriscore_related_fields']) or 'không có'}",
        "",
    ]
    return "\n".join(lines)


def write_reports(summary, checks, out_prefix, source="", generated_at=None):
    """Ghi <out_prefix>.md và <out_prefix>.json. Trả về (đường dẫn md, đường dẫn json)."""
    folder = os.path.dirname(out_prefix)
    if folder:
        os.makedirs(folder, exist_ok=True)
    md_path, json_path = out_prefix + ".md", out_prefix + ".json"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(summary, checks, source, generated_at))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": generated_at, "source": source, "summary": summary, "checks": checks},
                  f, ensure_ascii=False, indent=2)
    return md_path, json_path


# ======================================================================================
# Dòng lệnh
# ======================================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Kiểm toán dữ liệu thô Open Food Facts")
    ap.add_argument("--source", choices=["file", "db"], default="file")
    ap.add_argument("--pattern", default="data/raw/*.jsonl.gz", help="mẫu tệp khi --source file")
    ap.add_argument("--out", default="reports/raw_audit", help="tiền tố tệp kết quả (không có đuôi)")
    ap.add_argument("--min-usable", type=int, default=10000)
    ap.add_argument("--min-class", type=int, default=100)
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    stats = {}
    if args.source == "file":
        if not glob.glob(args.pattern):
            print(f"Không tìm thấy tệp nào khớp '{args.pattern}'. Hãy chạy src.fetch_from_dump trước.")
            return 1
        payloads = iter_payloads(args.pattern, stats)
        source = f"tệp {args.pattern}"
    else:
        payloads = iter_db()
        source = "PostgreSQL, bảng raw_products"

    summary = audit_records(payloads)
    if stats.get("malformed_lines"):
        summary["malformed_lines"] = stats["malformed_lines"]
    if summary["total"] == 0:
        print("Không có bản ghi nào để kiểm toán.")
        return 1

    checks = evaluate_checks(summary, min_usable=args.min_usable, min_class=args.min_class)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    md_path, json_path = write_reports(summary, checks, args.out, source, stamp)

    print(f"Tổng {summary['total']} | có nhãn {summary['labeled']} | dùng được {summary['usable']}")
    for c in checks:
        print(f"[{c['status']:>4}] {c['name']}: {c['detail']}")
    print(f"Đã ghi: {md_path} và {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
