"""Bước 9 - Dashboard dự đoán Nutri-Score. Chạy từ thư mục gốc dự án (đã bật venv):

    streamlit run dashboard/app.py

Chỉ dùng mô hình đã đóng băng (artifacts/best_model.joblib) và dữ liệu sạch cục bộ; không học lại gì.
Phần logic (tạo dòng, dự đoán, giải thích, gợi ý) nằm ở src/predict.py; tệp này chỉ là giao diện.
"""
import json
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.cleaning import as_list  # noqa: E402
from src.features import feature_names  # noqa: E402
from src.modeling import GRADES  # noqa: E402
from src.predict import alternatives, explain, ingredient_matrix, load_model, make_row, predict, to_tags  # noqa: E402

COLORS = {"A": "#038141", "B": "#85BB2F", "C": "#FECB02", "D": "#EE8100", "E": "#E63E11"}   # màu chính thức Nutri-Score
GRADE_COLOR = alt.Scale(domain=list(COLORS), range=list(COLORS.values()))
EXAMPLE_CODE = "3457221000505"          # Caramel au beurre salé (ví dụ xuyên suốt trong notebook)
MODES = ["Sản phẩm có sẵn (mã vạch)", "Tự nhập"]

st.set_page_config(page_title="Dự đoán Nutri-Score", page_icon=":material/nutrition:", layout="wide")


# ------------------------------------------------------------------ nạp một lần, dùng lại giữa các lần bấm
@st.cache_resource
def get_model():
    return load_model(ROOT / "artifacts" / "best_model.joblib")


@st.cache_data
def get_data():
    X = pd.read_parquet(ROOT / "data" / "final" / "clean_features.parquet")
    y = pd.read_parquet(ROOT / "data" / "final" / "clean_labels.parquet")["nutriscore_grade"].to_numpy(dtype=object)
    return X, y


@st.cache_resource
def get_ingredient_matrix():
    return ingredient_matrix(get_model(), get_data()[0])


@st.cache_data
def vocabulary(part):
    """Các giá trị mô hình biết của một phần đặc trưng, ví dụ 'additives' -> ['en:e322', ...]."""
    names = feature_names(get_model()["features"])
    return sorted(n.split("__", 1)[1] for n in names if n.startswith(part + "__"))


def vn(x, fmt=".3f"):
    """Số kiểu Việt Nam: 0,635 và 29.904 (đổi chỗ dấu chấm và dấu phẩy)."""
    return format(x, fmt).replace(",", " ").replace(".", ",").replace(" ", ".")


def short(tag):
    return tag.removeprefix("en:")


# ------------------------------------------------------------------ biểu đồ
def grade_badge(grade):
    # Ô chữ cái màu kiểu nhãn Nutri-Score: Streamlit không có phần tử tô màu tùy ý nên dùng một đoạn HTML nhỏ.
    st.html(f"<div style='text-align:center'>Hạng dự đoán<br><span style='display:inline-block;margin-top:6px;"
            f"background:{COLORS[grade.upper()]};color:white;font-size:3rem;font-weight:700;line-height:1.2;"
            f"border-radius:12px;padding:2px 28px'>{grade.upper()}</span></div>")


def proba_chart(proba):
    df = pd.DataFrame({"hạng": [g.upper() for g in GRADES], "xác suất": proba.to_numpy()})
    base = alt.Chart(df, height=220).encode(
        x=alt.X("hạng:N", title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("xác suất:Q", title=None, scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%")))
    bars = base.mark_bar().encode(color=alt.Color("hạng:N", scale=GRADE_COLOR, legend=None),
                                  tooltip=["hạng", alt.Tooltip("xác suất:Q", format=".1%")])
    return bars + base.mark_text(dy=-8).encode(text=alt.Text("xác suất:Q", format=".0%"))


def explain_chart(effect):
    df = effect.rename("thay đổi").rename_axis("thẻ").reset_index()
    return alt.Chart(df).mark_bar().encode(
        x=alt.X("thay đổi:Q", title="xác suất hạng dự đoán giảm bao nhiêu khi tắt thẻ", axis=alt.Axis(format=".1%")),
        y=alt.Y("thẻ:N", sort=list(df["thẻ"]), title=None, axis=alt.Axis(labelLimit=320)),   # giữ thứ tự |thay đổi|
        color=alt.condition("datum['thay đổi'] > 0", alt.value("#3182bd"), alt.value("#bbbbbb")),
        tooltip=["thẻ", alt.Tooltip("thay đổi:Q", format=".2%")])


def grade_mix_chart(long, order):
    return alt.Chart(long).mark_bar().encode(
        x=alt.X("tỷ lệ:Q", stack="normalize", title=None, axis=alt.Axis(format="%")),
        y=alt.Y("nhóm:N", sort=order, title=None, axis=alt.Axis(labelLimit=320)),
        color=alt.Color("hạng:N", scale=GRADE_COLOR, legend=alt.Legend(orient="top", title=None)),
        order=alt.Order("hạng:N"),
        tooltip=["nhóm", "hạng", alt.Tooltip("tỷ lệ:Q", format=".0%")])


# ------------------------------------------------------------------ kết quả cho một sản phẩm
def show_prediction(row, true_grade=None):
    """Hạng dự đoán, xác suất, giải thích bằng 'tắt thẻ' và gợi ý sản phẩm tốt hơn cho một dòng sản phẩm."""
    proba = predict(model, row)
    grade = proba.idxmax()
    left, right = st.columns([1, 2], border=True)
    with left:
        grade_badge(grade)
        if true_grade is not None:
            verdict = ":green[đúng]" if true_grade == grade else ":red[sai]"
            st.markdown(f"Hạng thật: **{true_grade.upper()}** ({verdict})", text_alignment="center")
        st.altair_chart(proba_chart(proba), alt=f"Xác suất 5 hạng, cao nhất là {grade.upper()} {proba.max():.0%}")
        if proba.max() < 0.5:
            a, b = proba.sort_values(ascending=False).index[:2]
            st.warning(f"Hai hạng khả năng nhất: {a.upper()} hoặc {b.upper()}. Trên tập test, khi độ tự tin dưới 50% "
                       "mô hình chỉ đúng 38,2%.", title=f"Mô hình chưa chắc (độ tự tin {proba.max():.0%})")
        else:
            st.success(f"Độ tự tin {proba.max():.0%}.")
    with right:
        st.subheader("Vì sao? (tắt từng thẻ rồi dự đoán lại)")
        effect = explain(model, row, grade)
        if effect.empty:
            st.write("Sản phẩm không có thẻ nào mô hình biết.")
        else:
            st.altair_chart(explain_chart(effect), alt="Mức giảm xác suất hạng dự đoán khi tắt từng thẻ")
            st.caption("Xanh: thẻ ủng hộ hạng dự đoán (tắt đi thì xác suất giảm). Xám: thẻ kéo về hạng khác. "
                       "Khi mô hình đã rất chắc, tắt một thẻ chỉ đổi xác suất rất ít.")

    if grade != "a":
        with st.container(border=True):
            st.subheader(f"Sản phẩm cùng nhóm có hạng tốt hơn {grade.upper()}, thành phần giống nhất")
            better = alternatives(model, row, grade, X, y, get_ingredient_matrix())
            if better.empty:
                st.write("Không tìm thấy (thiếu nhóm sản phẩm, hoặc nhóm này không có sản phẩm hạng tốt hơn).")
            else:
                st.dataframe(better, hide_index=True, alt="Sản phẩm thay thế cùng nhóm", column_config={
                    "code": st.column_config.TextColumn("Mã vạch"),
                    "product_name": st.column_config.TextColumn("Tên sản phẩm", width="large"),
                    "hạng": st.column_config.TextColumn("Hạng thật"),
                    "độ giống": st.column_config.ProgressColumn("Độ giống thành phần", min_value=0, max_value=1,
                                                                format="%.2f")})


# ------------------------------------------------------------------ kiểm tra tệp cần thiết
missing = [p for p in ("artifacts/best_model.joblib", "data/final/clean_features.parquet") if not (ROOT / p).exists()]
if missing:
    st.error(f"Thiếu {missing}. Chạy notebook 04 và 05 trước (xem README).")
    st.stop()

model = get_model()
X, y = get_data()

st.title("Dự đoán Nutri-Score từ thành phần")
st.caption("Mô hình LightGBM chỉ dùng thành phần, phụ gia, danh mục, NOVA và quốc gia, không dùng bảng dinh dưỡng. "
           "Kết quả là ước lượng tham khảo, không phải lời khuyên sức khỏe.")
tab_predict, tab_overview = st.tabs(["Dự đoán", "Tổng quan kết quả"])

# ================================================================== TAB 1: DỰ ĐOÁN
with tab_predict:
    mode = st.segmented_control("Cách nhập", MODES, default=MODES[0], required=True, key="mode")
    row, true_grade = None, None
    if mode == MODES[0]:
        code = st.text_input("Mã vạch", EXAMPLE_CODE, key="code", help="Mã vạch của một sản phẩm trong 29.904 sản phẩm sạch")
        found = X[X["code"] == code.strip()]
        if found.empty:
            st.warning("Không có mã vạch này trong dữ liệu. Thử 3457221000505, hoặc chọn 'Tự nhập'.")
        else:
            row, true_grade = found.head(1), y[found.index[0]]
            st.markdown(f"**{row['product_name'].iloc[0]}** · nhóm: {row['pnns_groups_2'].iloc[0]} · "
                        f"NOVA: {row['nova_group'].iloc[0]}")
            st.caption("Thành phần: " + ", ".join(map(short, as_list(row["ingredients_tags"].iloc[0]) or [])))
    else:
        st.info("Nhập thành phần theo **thứ tự trên bao bì** (nhiều nhất trước), bằng tiếng Anh, cách nhau dấu phẩy. "
                "Thành phần mô hình chưa từng gặp đủ nhiều vẫn được đếm nhưng không có cột riêng.")
        text = st.text_area("Thành phần", "sugar, wheat flour, palm oil, cocoa powder, salt, E322")
        c1, c2, c3 = st.columns(3, vertical_alignment="bottom")
        groups_1 = sorted(n.removeprefix("pnns_groups_1_") for n in vocabulary("pnns") if n.startswith("pnns_groups_1_"))
        groups_2 = sorted(n.removeprefix("pnns_groups_2_") for n in vocabulary("pnns") if n.startswith("pnns_groups_2_"))
        pnns_1 = c1.selectbox("Nhóm lớn (pnns_groups_1)", groups_1, index=groups_1.index("sugary snacks"))
        pnns_2 = c2.selectbox("Nhóm nhỏ (pnns_groups_2)", groups_2, index=groups_2.index("biscuits and cakes"))
        nova = c3.segmented_control("NOVA", [1, 2, 3, 4, "không rõ"], default=4, required=True)
        additives = st.multiselect("Phụ gia", vocabulary("additives"), default=["en:e322"], format_func=short)
        categories = st.multiselect("Thẻ danh mục", vocabulary("categories"), default=["en:biscuits"], format_func=short)
        countries = st.multiselect("Quốc gia bán", vocabulary("countries"), default=["en:france"], format_func=short)
        row = make_row(to_tags(text), additives, categories,
                       None if pnns_1 == "missing" else pnns_1, None if pnns_2 == "missing" else pnns_2,
                       None if nova == "không rõ" else nova, countries)
        known = set(vocabulary("ingredients"))
        tags = row["ingredients_tags"].iloc[0]
        st.caption(f"Nhận ra {sum(t in known for t in tags)}/{len(tags)} thành phần: "
                   + ", ".join(short(t) if t in known else f"~~{short(t)}~~" for t in tags))

    if row is not None:
        show_prediction(row, true_grade)

# ================================================================== TAB 2: TỔNG QUAN
with tab_overview:
    results_path = ROOT / "reports" / "test_results.json"
    if results_path.exists():
        R = json.loads(results_path.read_text(encoding="utf-8"))
        test, base = R["test"][R["model"]], R["test"]["Đường cơ sở: theo pnns_groups_2"]
        st.subheader(f"Kết quả trên tập test ({vn(R['n_test'], ',')} sản phẩm của các thương hiệu mô hình chưa thấy)")
        metrics = [("macro_f1", "Macro-F1", "Trung bình F1 của 5 hạng, hạng nào cũng nặng như nhau (chỉ số chính)."),
                   ("qwk", "QWK", "Độ đồng thuận có tính thứ tự: đoán A thành E bị phạt nặng hơn A thành B."),
                   ("accuracy", "Accuracy", "Tỷ lệ đoán đúng hạng."),
                   ("within_one", "Lệch ≤ 1 hạng", "Tỷ lệ đoán đúng hoặc lệch một hạng.")]
        for col, (key, label, note) in zip(st.columns(4), metrics):
            col.metric(label, vn(test[key]), f"{vn(test[key] - base[key], '+.3f')} so với đoán theo nhóm", help=note,
                       border=True)
        c1, c2 = st.columns(2)
        c1.image(str(ROOT / "reports" / "figures" / "eval_01_ma_tran_nham_lan_test.png"),
                 alt="Ma trận nhầm lẫn trên tập test, tỷ lệ theo hàng")
        c2.image(str(ROOT / "reports" / "figures" / "eval_03_the_keo_hang.png"),
                 alt="Các thẻ kéo hạng xuống D, E và kéo hạng lên")

    st.subheader("Phân bố hạng thật theo nhóm sản phẩm")
    market = st.segmented_control("Thị trường", ["Tất cả", "Bán ở Pháp", "Bán ở Mỹ"], default="Tất cả", required=True,
                                  key="market")
    tag = {"Bán ở Pháp": "en:france", "Bán ở Mỹ": "en:united-states"}.get(market)
    keep = X["countries_tags"].map(lambda v: tag is None or tag in (as_list(v) or [])).to_numpy()
    groups = pd.Series(X.loc[keep, "pnns_groups_1"].fillna("missing").to_numpy())
    n = groups.map(groups.value_counts())
    big = (n >= 30).to_numpy()                                # nhóm quá ít sản phẩm thì tỷ lệ không đáng tin
    labels = (groups + " (" + n.map(lambda v: vn(v, ",")) + ")")[big]                       # kèm số sản phẩm
    table = pd.crosstab(labels.to_numpy(), y[keep][big], normalize="index").reindex(columns=GRADES, fill_value=0)
    order = (table["a"] + table["b"]).sort_values(ascending=False).index.tolist()           # nhiều A, B nhất ở trên
    long = table.rename(columns=str.upper).rename_axis(index="nhóm", columns="hạng").stack().rename("tỷ lệ").reset_index()
    st.altair_chart(grade_mix_chart(long, order), alt="Tỷ lệ 5 hạng trong từng nhóm sản phẩm")
    st.caption(f"{vn(big.sum(), ',')} sản phẩm. Mỗi thanh là tỷ lệ các hạng trong một nhóm, xếp theo tỷ lệ A + B "
               "giảm dần; số trong ngoặc là số sản phẩm của nhóm; bỏ nhóm dưới 30 sản phẩm.")
