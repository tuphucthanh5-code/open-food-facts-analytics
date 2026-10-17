"""Bước 3 - Staging: làm phẳng JSON thô thành hai bảng tách biệt.

  staging_features.parquet  CHỈ chứa đặc trưng hợp lệ cho Phương án A (thành phần, phụ gia, danh mục, NOVA...).
  staging_audit.parquet     chứa nhãn Nutri-Score và bảng dinh dưỡng (*_100g). Chỉ dùng để kiểm tra nhãn và EDA,
                            KHÔNG bao giờ đưa vào đặc trưng mô hình.

Hai bảng có cùng cột row_id (số thứ tự trong lượt đọc) để ghép lại khi cần.
Staging KHÔNG lọc dòng nào: lọc, loại trùng, xử lý ngoại lai là việc của bước cleaning.
Trường cá nhân (creator, editors_tags...) không bao giờ được chép sang.

Chạy từ thư mục gốc dự án:
    python -m src.staging                 # đọc data/raw/*.jsonl.gz
    python -m src.staging --source db     # đọc bảng raw_products trong PostgreSQL
"""
import argparse
import glob
import json
import math
import os
import sys
from datetime import datetime, timezone

import pandas as pd

from src.raw_audit import (VALID_GRADES, find_leakage_fields, find_pii_fields,
                           iter_db, iter_payloads, normalize_grade, normalize_nova)

# --- Cột của bảng đặc trưng ---------------------------------------------------------------
FEATURE_COLUMNS = [
    "row_id", "code", "product_name", "brand", "brands_tags", "countries_tags", "categories_tags",
    "pnns_groups_1", "pnns_groups_2", "ingredients_tags", "ingredients_text", "ingredients_n",
    "ingredients_from_palm_oil_n", "ingredients_analysis_tags", "additives_tags", "additives_n",
    "allergens_tags", "labels_tags", "nova_group", "lang", "last_modified",
]
LIST_COLUMNS = [
    "brands_tags", "countries_tags", "categories_tags", "ingredients_tags",
    "ingredients_analysis_tags", "additives_tags", "allergens_tags", "labels_tags",
]

# --- Cột của bảng kiểm toán -------------------------------------------------------------------
NUTRIENT_KEYS = [
    "energy-kcal_100g", "energy-kj_100g", "fat_100g", "saturated-fat_100g", "carbohydrates_100g",
    "sugars_100g", "fiber_100g", "proteins_100g", "salt_100g", "sodium_100g",
]
AUDIT_BASE_COLUMNS = ["row_id", "code", "nutriscore_grade", "nutriscore_grade_raw"] + NUTRIENT_KEYS


# ======================================================================================
# Hàm ép kiểu: không bao giờ ném lỗi, giá trị không hợp lệ -> None
# ======================================================================================
def to_str(value):
    """Chuỗi đã strip; chuỗi rỗng và giá trị không phải chuỗi/số -> None. Số được đổi sang chuỗi."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return None


def to_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def to_float(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(str(value).strip()) if not isinstance(value, (int, float)) else float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def to_list(value):
    """list các chuỗi. Vắng/không phải list -> None (giữ phân biệt với list rỗng [])."""
    if not isinstance(value, list):
        return None
    return [x.strip() for x in value if isinstance(x, str) and x.strip()]


def to_category(value):
    """Chuỗi chữ thường; 'unknown' hoặc rỗng -> None."""
    s = to_str(value)
    if s is None:
        return None
    s = s.lower()
    return None if s == "unknown" else s


# ======================================================================================
# Dựng từng dòng
# ======================================================================================
def build_feature_row(payload, row_id):
    brands = to_list(payload.get("brands_tags"))
    row = {
        "row_id": row_id,
        "code": to_str(payload.get("code")),            # luôn là chuỗi: giữ số 0 ở đầu
        "product_name": to_str(payload.get("product_name")),
        "brand": brands[0] if brands else None,
        "pnns_groups_1": to_category(payload.get("pnns_groups_1")),
        "pnns_groups_2": to_category(payload.get("pnns_groups_2")),
        "ingredients_text": to_str(payload.get("ingredients_text")),
        "ingredients_n": to_int(payload.get("ingredients_n")),
        "ingredients_from_palm_oil_n": to_int(payload.get("ingredients_from_palm_oil_n")),
        "additives_n": to_int(payload.get("additives_n")),
        "nova_group": normalize_nova(payload.get("nova_group")),
        "lang": to_str(payload.get("lang")),
        "last_modified": to_int(payload.get("last_modified_t")),   # đổi sang datetime ở bước DataFrame
    }
    for col in LIST_COLUMNS:
        row[col] = to_list(payload.get(col))
    return row


def build_audit_row(payload, row_id):
    raw = payload.get("nutriscore_grade")
    row = {
        "row_id": row_id,
        "code": to_str(payload.get("code")),
        "nutriscore_grade": normalize_grade(raw),
        "nutriscore_grade_raw": to_str(raw),
    }
    nutriments = payload.get("nutriments")
    nutriments = nutriments if isinstance(nutriments, dict) else {}
    for key in NUTRIENT_KEYS:
        row[key] = to_float(nutriments.get(key))
    # Giữ các trường nutriscore_* khác (điểm, phiên bản công thức nếu có) để xử lý ở bước cleaning
    for key in sorted(k for k in payload if k.startswith("nutriscore") and k != "nutriscore_grade"):
        v = payload[key]
        row[key] = v if isinstance(v, (str, int, float, bool)) or v is None else json.dumps(v, ensure_ascii=False)
    return row


def assert_features_are_clean(columns):
    """Chốt chặn cuối: bảng đặc trưng không được chứa nhãn, dinh dưỡng hay trường cá nhân."""
    bad = set(find_leakage_fields(columns)) | set(find_pii_fields(columns))
    bad |= {c for c in columns if c.endswith("_100g") or c.endswith("_serving")}
    if bad:
        raise ValueError(f"Bảng đặc trưng chứa cột bị cấm: {sorted(bad)}")


def stage(payloads):
    """Biến các payload thành (features_df, audit_df). Không lọc dòng nào."""
    feat_rows, audit_rows = [], []
    for i, payload in enumerate(payloads):
        feat_rows.append(build_feature_row(payload, i))
        audit_rows.append(build_audit_row(payload, i))

    features = pd.DataFrame(feat_rows, columns=FEATURE_COLUMNS)
    extra = [c for c in pd.DataFrame(audit_rows).columns if c not in AUDIT_BASE_COLUMNS] if audit_rows else []
    audit = pd.DataFrame(audit_rows, columns=AUDIT_BASE_COLUMNS + extra)

    features["last_modified"] = pd.to_datetime(features["last_modified"], unit="s", utc=True, errors="coerce")
    for col in ("ingredients_n", "ingredients_from_palm_oil_n", "additives_n", "nova_group"):
        features[col] = features[col].astype("Int64")
    for col in AUDIT_BASE_COLUMNS[4:]:
        audit[col] = audit[col].astype("float64")

    assert_features_are_clean(list(features.columns))
    return features, audit


# ======================================================================================
# Ghi tệp và báo cáo
# ======================================================================================
def write_outputs(features, audit, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    f_path = os.path.join(out_dir, "staging_features.parquet")
    a_path = os.path.join(out_dir, "staging_audit.parquet")
    features.to_parquet(f_path, index=False)
    audit.to_parquet(a_path, index=False)
    return f_path, a_path


def _has_items(value):
    """True nếu là list/mảng không rỗng (cả list Python lẫn mảng numpy đọc từ parquet)."""
    return value is not None and hasattr(value, "__len__") and not isinstance(value, str) and len(value) > 0


def summarize(features, audit):
    n = len(features)
    return {
        "rows": n,
        "feature_columns": list(features.columns),
        "audit_columns": list(audit.columns),
        "with_valid_grade": int(audit["nutriscore_grade"].isin(VALID_GRADES).sum()),
        "with_ingredients": int(features["ingredients_tags"].map(_has_items).sum()) if n else 0,
        "with_nova": int(features["nova_group"].notna().sum()),
        "missing_pct_features": {c: round(100 * float(features[c].isna().mean()), 1) for c in features.columns} if n else {},
    }


def render_report(summary, generated_at, source):
    rows = summary["rows"]
    lines = [
        "# Báo cáo staging", "",
        f"- Thời điểm: {generated_at}", f"- Nguồn: {source}",
        f"- Số dòng (không lọc): **{rows}**",
        f"- Có nhãn A-E hợp lệ: {summary['with_valid_grade']}",
        f"- Có danh sách thành phần: {summary['with_ingredients']}",
        f"- Có NOVA hợp lệ: {summary['with_nova']}", "",
        "## Cột của staging_features (đặc trưng hợp lệ)", "",
        ", ".join(f"`{c}`" for c in summary["feature_columns"]), "",
        "## Cột của staging_audit (chỉ để kiểm tra nhãn và EDA)", "",
        ", ".join(f"`{c}`" for c in summary["audit_columns"]), "",
        "## Tỷ lệ thiếu (%) trong staging_features", "",
        "| Cột | Thiếu (%) |", "|---|---|",
    ]
    lines += [f"| {c} | {v} |" for c, v in summary["missing_pct_features"].items()]
    return "\n".join(lines) + "\n"


# ======================================================================================
# Dòng lệnh
# ======================================================================================
def main(argv=None):
    ap = argparse.ArgumentParser(description="Staging: làm phẳng dữ liệu thô")
    ap.add_argument("--source", choices=["file", "db"], default="file")
    ap.add_argument("--pattern", default="data/raw/*.jsonl.gz")
    ap.add_argument("--out-dir", default="data/processed")
    ap.add_argument("--report", default="reports/staging_report.md")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if args.source == "file":
        if not glob.glob(args.pattern):
            print(f"Không tìm thấy tệp nào khớp '{args.pattern}'. Hãy chạy fetch_raw_food_facts.py trước.")
            return 1
        payloads, source = iter_payloads(args.pattern), f"tệp {args.pattern}"
    else:
        payloads, source = iter_db(), "PostgreSQL, bảng raw_products"

    features, audit = stage(payloads)
    if features.empty:
        print("Không có bản ghi nào để staging.")
        return 1

    f_path, a_path = write_outputs(features, audit, args.out_dir)
    summary = summarize(features, audit)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    folder = os.path.dirname(args.report)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(render_report(summary, stamp, source))

    print(f"Staging {summary['rows']} dòng | nhãn hợp lệ {summary['with_valid_grade']} | "
          f"có thành phần {summary['with_ingredients']} | có NOVA {summary['with_nova']}")
    print(f"Đã ghi: {f_path}, {a_path}, {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
