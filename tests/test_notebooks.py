"""Notebook là sản phẩm nộp chính: phải chạy hết, có kết quả, không mở tập test, không lộ bí mật."""
import json

import pytest

NOTEBOOKS = ["01_bai_toan", "02_thu_thap_du_lieu", "03_eda", "04_chuan_bi_du_lieu", "05_mo_hinh"]
FORBIDDEN = ["final=True", ".env", "DB_PASSWORD", "password", "overwrite"]


def load(root, name):
    return json.loads((root / "notebooks" / f"{name}.ipynb").read_text(encoding="utf-8"))


def code_cells(nb):
    return [c for c in nb["cells"] if c["cell_type"] == "code"]


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_notebook_was_run_without_errors(root, name):
    cells = code_cells(load(root, name))
    assert cells, "notebook không có ô code"
    assert all(c.get("execution_count") for c in cells), "có ô chưa chạy: chạy lại bằng jupyter nbconvert --execute"
    errors = [o for c in cells for o in c.get("outputs", []) if o.get("output_type") == "error"]
    assert not errors, f"có ô báo lỗi: {errors[0].get('ename')}"


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_notebook_rules(root, name):
    cells = code_cells(load(root, name))
    assert "os.chdir(root)" in "".join(cells[0]["source"])
    code = "\n".join("".join(c["source"]) for c in cells)
    found = [p for p in FORBIDDEN if p in code]
    assert not found, f"notebook chứa mẫu bị cấm: {found}"
    assert 'to_parquet("data/final/split.parquet"' not in code, "notebook không được ghi đè tập chia đã khóa"
