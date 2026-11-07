"""Dashboard chạy được từ đầu đến cuối với mô hình và dữ liệu thật (bỏ qua nếu máy không có các tệp này, ví dụ CI)."""
import pytest


@pytest.fixture
def app(root):
    pytest.importorskip("streamlit")
    needed = [root / "artifacts" / "best_model.joblib", root / "data" / "final" / "clean_features.parquet",
              root / "data" / "final" / "clean_labels.parquet"]
    if not all(p.exists() for p in needed):
        pytest.skip("không có mô hình hoặc dữ liệu sạch trên máy này")
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(root / "dashboard" / "app.py"), default_timeout=300).run()


def test_dashboard_barcode_and_manual_input(app):
    assert not app.exception
    assert any("Hạng thật" in m.value for m in app.markdown)               # sản phẩm ví dụ có hạng thật để so
    assert len(app.metric) == 4                                              # 4 chỉ số trên tập test
    app.segmented_control(key="market").set_value("Bán ở Mỹ").run()          # lọc thị trường ở tab Tổng quan
    assert not app.exception
    app.segmented_control(key="mode").set_value("Tự nhập").run()
    assert not app.exception
    assert any("Nhận ra" in c.value for c in app.caption)


def test_dashboard_unknown_barcode_does_not_crash(app):
    app.text_input[0].set_value("123").run()
    assert not app.exception
    assert any("Không có mã vạch" in w.value for w in app.warning)
