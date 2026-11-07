"""Cấu trúc repo và an toàn bí mật: bắt lỗi trước khi push lên GitHub."""
import re
import subprocess

import pytest

REQUIRED_FILES = [
    ".gitignore", ".env.example", "README.md", "requirements.txt", "requirements-dev.txt", "pytest.ini",
    "sql/init_raw_db.sql", "sql/audit_queries.sql", "sql/extract_products.sql",
    "src/__init__.py", "src/db.py", "src/fetch_from_dump.py", "src/load_raw_to_postgres.py", "src/cleaning.py",
    "src/features.py", "src/modeling.py", "src/predict.py", "dashboard/app.py", ".streamlit/config.toml",
    "notebooks/01_bai_toan.ipynb", "notebooks/02_thu_thap_du_lieu.ipynb", "notebooks/03_eda.ipynb",
    "notebooks/04_chuan_bi_du_lieu.ipynb", "notebooks/05_mo_hinh.ipynb", "notebooks/06_danh_gia.ipynb",
    "docs/problem_statement.md", "docs/scope_decision.md", "docs/data_dictionary.md",
]


@pytest.mark.parametrize("rel", REQUIRED_FILES)
def test_required_file_exists(root, rel):
    assert (root / rel).is_file(), f"thiếu {rel}"


@pytest.mark.parametrize("pattern", [".env", "data/raw/*", "data/processed/*", "data/final/*", "data/external/*",
                                     "*.jsonl.gz", "*.parquet", "*.joblib", "__pycache__/"])
def test_gitignore_blocks(root, pattern):
    lines = {ln.strip() for ln in (root / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert pattern in lines


def test_git_really_ignores_env(root):
    try:
        r = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=root, capture_output=True)
    except FileNotFoundError:
        pytest.skip("không có git")
    if r.returncode == 128:
        pytest.skip("không phải kho git")
    assert r.returncode == 0, ".env KHÔNG bị .gitignore chặn"


def test_env_example_has_only_placeholders(root):
    text = (root / ".env.example").read_text(encoding="utf-8")
    assert "DB_PASSWORD=your_password_here" in text


def test_no_hardcoded_secret_or_email_in_src(root):
    password = re.compile(r"""password["']?\s*[:=]\s*["'][^"']+["']""", re.IGNORECASE)
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    for py in (root / "src").rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert not password.search(text), f"mật khẩu viết cứng trong {py.name}"
        assert not email.search(text), f"địa chỉ email trong {py.name}"


def test_requirements_cover_libraries(root):
    reqs = (root / "requirements.txt").read_text(encoding="utf-8").lower()
    for lib in ("psycopg2", "python-dotenv", "pandas", "pyarrow", "duckdb", "scipy", "scikit-learn", "lightgbm",
                "optuna", "joblib", "matplotlib", "seaborn", "streamlit"):
        assert lib in reqs, f"requirements.txt thiếu {lib}"


def test_readme_mentions_license_and_tests(root):
    text = (root / "README.md").read_text(encoding="utf-8")
    assert "ODbL" in text and "pytest" in text


def test_requirements_pinned_and_ascii(root):
    """pip tren Windows doc requirements bang cp1252: chu co dau se lam pip bao loi; moi thu vien phai ghim ==."""
    text = (root / "requirements.txt").read_bytes()
    assert text.isascii(), "requirements.txt chi duoc chua ky tu ASCII"
    libs = [ln for ln in text.decode().splitlines() if ln.strip() and not ln.startswith("#")]
    assert all("==" in ln for ln in libs), "moi thu vien trong requirements.txt phai ghim phien ban"
