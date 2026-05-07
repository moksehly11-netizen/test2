import os
import io
import pandas as pd
from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename
from egyptian_names import predict_gender

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max

ALLOWED_EXTENSIONS = {"xlsx", "xls", "csv"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def find_name_column(df: pd.DataFrame) -> str | None:
    """Auto-detect which column contains customer names."""
    name_keywords = [
        "name", "الاسم", "اسم", "customer", "عميل", "العميل",
        "client", "buyer", "المشتري", "اسم العميل", "اسم الزبون",
        "billing_name", "shipping_name", "full_name", "الاسم الكامل",
        "اسم المستلم", "المستلم", "استلام",
    ]
    cols_lower = {c.strip().lower(): c for c in df.columns}

    for kw in name_keywords:
        if kw.lower() in cols_lower:
            return cols_lower[kw.lower()]

    # Fuzzy: column whose values look like Arabic names (>50% contain Arabic chars)
    import re
    arabic_re = re.compile(r"[؀-ۿ]")
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(20)
        arabic_count = sum(1 for v in sample if arabic_re.search(v))
        if arabic_count > len(sample) * 0.5:
            return col

    return None


def analyze_names(df: pd.DataFrame, name_col: str) -> dict:
    results = []
    counts = {"female": 0, "male": 0, "unknown": 0}

    for raw in df[name_col].dropna().astype(str):
        name = raw.strip()
        if not name or name.lower() in ("nan", "none", ""):
            continue
        gender = predict_gender(name)
        counts[gender] += 1
        results.append({"name": name, "gender": gender})

    total = counts["female"] + counts["male"] + counts["unknown"]
    classified = counts["female"] + counts["male"]

    def pct(n, base=total):
        return round(n / base * 100, 1) if base > 0 else 0

    return {
        "total": total,
        "classified": classified,
        "female": counts["female"],
        "male": counts["male"],
        "unknown": counts["unknown"],
        "female_pct": pct(counts["female"]),
        "male_pct": pct(counts["male"]),
        "unknown_pct": pct(counts["unknown"]),
        "female_pct_classified": pct(counts["female"], classified),
        "male_pct_classified": pct(counts["male"], classified),
        "rows": results[:500],  # cap preview to 500
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    if "file" not in request.files:
        return jsonify({"error": "مفيش ملف اتبعت"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "اختار ملف الأول"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "نوع الملف مش صح. ارفع xlsx أو xls أو csv"}), 400

    filename = secure_filename(file.filename)
    ext = filename.rsplit(".", 1)[1].lower()

    try:
        content = file.read()
        if ext == "csv":
            # try utf-8 then cp1256 (Windows Arabic)
            try:
                df = pd.read_csv(io.BytesIO(content), encoding="utf-8")
            except Exception:
                df = pd.read_csv(io.BytesIO(content), encoding="cp1256")
        else:
            df = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        return jsonify({"error": f"مقدرتش أقرأ الملف: {str(e)}"}), 400

    if df.empty:
        return jsonify({"error": "الملف فاضي"}), 400

    # Let caller override name column
    name_col = request.form.get("name_column", "").strip()
    if name_col and name_col not in df.columns:
        return jsonify({"error": f"العمود '{name_col}' مش موجود في الملف"}), 400

    if not name_col:
        name_col = find_name_column(df)

    if not name_col:
        columns = list(df.columns)
        return jsonify({
            "error": "مش قادر أحدد عمود الأسماء تلقائياً",
            "columns": columns,
            "needs_column_selection": True,
        }), 422

    stats = analyze_names(df, name_col)
    stats["name_column_used"] = name_col
    stats["all_columns"] = list(df.columns)
    return jsonify(stats)


@app.route("/columns", methods=["POST"])
def get_columns():
    """Return list of columns in the uploaded file."""
    if "file" not in request.files:
        return jsonify({"error": "مفيش ملف"}), 400
    file = request.files["file"]
    ext = secure_filename(file.filename).rsplit(".", 1)[-1].lower()
    content = file.read()
    try:
        if ext == "csv":
            try:
                df = pd.read_csv(io.BytesIO(content), encoding="utf-8", nrows=5)
            except Exception:
                df = pd.read_csv(io.BytesIO(content), encoding="cp1256", nrows=5)
        else:
            df = pd.read_excel(io.BytesIO(content), nrows=5)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"columns": list(df.columns)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)
