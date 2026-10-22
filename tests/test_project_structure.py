"""Kiểm thử cấu trúc repo và an toàn bí mật: bắt lỗi trước khi push lên GitHub."""
import re
import subprocess

import pytest

REQUIRED_FILES = [
    ".gitignore", ".env.example", "README.md", "requirements.txt", "requirements-dev.txt", "pytest.ini",
    "sql/init_raw_db.sql", "sql/audit_queries.sql",
    "src/__init__.py", "src/load_raw_to_postgres.py", "src/raw_audit.py", "src/staging.py", "src/fetch_from_dump.py", "src/cleaning.py",
    "docs/problem_statement.md", "docs/scope_decision.md", "docs/data_dictionary.md",
]


@pytest.mark.parametrize("rel", REQUIRED_FILES)
def test_required_file_exists(root, rel):
    assert (root / rel).is_file(), f"thiếu {rel}"


@pytest.mark.parametrize("rel", ["data/raw", "data/processed", "data/final", "data/external", "logs"])
def test_placeholder_dirs_are_kept_by_gitkeep(root, rel):
    assert (root / rel / ".gitkeep").is_file()


# --------------------------------------------------------------------------- .gitignore
@pytest.fixture
def ignore_lines(root):
    text = (root / ".gitignore").read_text(encoding="utf-8")
    return {ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")}


@pytest.mark.parametrize("pattern", [".env", "data/raw/*", "data/processed/*", "data/final/*",
                                     "*.jsonl.gz", "*.parquet", "*.db", "*.sqlite3", "__pycache__/", "data/external/*"])
def test_gitignore_blocks(ignore_lines, pattern):
    assert pattern in ignore_lines


@pytest.mark.parametrize("pattern", ["!data/raw/.gitkeep", "!data/processed/.gitkeep",
                                     "!data/final/.gitkeep", "!logs/.gitkeep"])
def test_gitignore_keeps_placeholders(ignore_lines, pattern):
    assert pattern in ignore_lines


def test_gitignore_does_not_block_source_files(ignore_lines):
    for bad in ("*.py", "*.sql", "*.md", "src/", "sql/", "tests/", "docs/", "reports/"):
        assert bad not in ignore_lines


def test_git_really_ignores_env_when_inside_a_repo(root):
    try:
        r = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=root, capture_output=True)
    except FileNotFoundError:
        pytest.skip("không có git")
    if r.returncode == 128:
        pytest.skip("thư mục không phải kho git")
    assert r.returncode == 0, ".env KHÔNG bị .gitignore chặn"


# --------------------------------------------------------------------------- bí mật
def test_env_example_has_only_placeholders(root):
    text = (root / ".env.example").read_text(encoding="utf-8")
    assert "DB_PASSWORD=your_password_here" in text
    assert "OFF_USER_AGENT=" in text


def test_env_example_lists_every_variable_used_in_src(root):
    example = (root / ".env.example").read_text(encoding="utf-8")
    used = set()
    for py in (root / "src").glob("*.py"):
        used |= set(re.findall(r'(?:getenv|environ)\(?\[?\s*["\'](\w+)["\']', py.read_text(encoding="utf-8")))
    assert used, "không tìm thấy biến môi trường nào trong src"
    missing = {v for v in used if f"{v}=" not in example}
    assert not missing, f".env.example thiếu: {missing}"


def test_no_hardcoded_password_in_src(root):
    pattern = re.compile(r"""password["']?\s*[:=]\s*["'][^"']+["']""", re.IGNORECASE)
    for py in (root / "src").rglob("*.py"):
        assert not pattern.search(py.read_text(encoding="utf-8")), f"mật khẩu viết cứng trong {py.name}"


def test_no_email_address_in_src(root):
    for py in (root / "src").rglob("*.py"):
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", py.read_text(encoding="utf-8")), \
            f"địa chỉ email trong {py.name}"


# --------------------------------------------------------------------------- tài liệu
def test_readme_mentions_license_and_tests(root):
    text = (root / "README.md").read_text(encoding="utf-8")
    assert "ODbL" in text
    assert "pytest" in text


def test_requirements_cover_imports_used_in_src(root):
    reqs = (root / "requirements.txt").read_text(encoding="utf-8").lower()
    for lib in ("requests", "urllib3", "psycopg2", "python-dotenv", "pandas", "pyarrow", "duckdb"):
        assert lib in reqs, f"requirements.txt thiếu {lib}"
