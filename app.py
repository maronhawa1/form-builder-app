from flask import Flask, render_template, request, redirect, url_for, flash, session
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash
from bson import ObjectId
from datetime import datetime

app = Flask(__name__)

app.secret_key = "CHANGE_THIS_SECRET_KEY"


import os

def get_db():
    # אם יש MONGO_URI (בענן)
    mongo_uri = os.environ.get("MONGO_URI")

    if mongo_uri:
        client = MongoClient(mongo_uri)
        db = client["form_app"]   # ← אותו שם גם לענן
    else:
        # מצב לוקאלי
        client = MongoClient("mongodb://localhost:27017/")
        db = client["form_app"]   # ← אותו שם גם ללוקאל

    return db

db = get_db()
user_col = db['users']
form_col = db['forms']
response_col = db['responses']


@app.route("/")
def index():
    # אם המשתמש כבר מחובר – נשלח אותו ישר לדשבורד
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route('/test_mongo')
def test_mongo():
    demo_user = {
        "name": "Demo User",
        "email": "demo@example.com"
    }
    result = user_col.insert_one(demo_user)
    return f"Inserted demo user with id: {result.inserted_id}"


@app.route("/register", methods=["GET", "POST"])
def register():
    # אם המשתמש כבר מחובר – לא צריך לראות את דף ההרשמה
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password")

        existing_user = user_col.find_one({"email": email})
        if existing_user:
            flash("האימייל הזה כבר רשום במערכת", "error")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password, method='pbkdf2:sha256')

        user_col.insert_one({
            "name": name,
            "email": email,
            "password_hash": password_hash,
            "created_at": datetime.utcnow()
        })

        flash("נרשמת בהצלחה! עכשיו אפשר להתחבר", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    # אם כבר מחובר – אין סיבה לראות דף התחברות
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password")

        user = user_col.find_one({"email": email})

        if not user or not check_password_hash(user["password_hash"], password):
            flash("אימייל או סיסמה לא נכונים", "error")
            return redirect(url_for("login"))

        session["user_id"] = str(user["_id"])
        session["user_name"] = user["name"]

        flash("התחברת בהצלחה!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]

    # כל הטפסים שייכים למשתמש המחובר
    forms = list(form_col.find({"owner_id": ObjectId(user_id)}))

    return render_template(
        "dashboard.html",
        name=session["user_name"],
        forms=forms
    )


@app.route("/forms/new", methods=["GET", "POST"])
def create_form():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")

        if not title:
            flash("חייב למלא שם טופס", "error")
            return redirect(url_for("create_form"))

        # רשימות השדות מהטופס
        labels = request.form.getlist("field_label[]")
        types = request.form.getlist("field_type[]")
        options_raw = request.form.getlist("field_options[]")

        fields = []

        for i in range(len(labels)):
            label = labels[i].strip()
            ftype = types[i]
            opts_str = options_raw[i].strip() if i < len(options_raw) else ""

            if not label:
                continue

            # שם טכני לשדה (ללא רווחים)
            name = label.replace(" ", "_").lower()

            options = []
            if ftype in ["select", "checkbox_group"] and opts_str:
                options = [o.strip() for o in opts_str.split(",") if o.strip()]

            fields.append({
                "label": label,
                "name": name,
                "type": ftype,
                "required": False,  # אפשר לשפר בהמשך
                "options": options
            })

        form_doc = {
            "owner_id": ObjectId(session["user_id"]),
            "title": title,
            "description": description,
            "fields": fields,
            "created_at": datetime.utcnow()
        }

        form_col.insert_one(form_doc)
        flash("הטופס נוצר בהצלחה", "success")
        return redirect(url_for("dashboard"))

    return render_template("form_new.html")


@app.route("/f/<form_id>", methods=["GET", "POST"])
def public_form(form_id):
    try:
        form = form_col.find_one({"_id": ObjectId(form_id)})
    except:
        form = None

    if not form:
        return "Form not found", 404

    fields = form.get("fields", [])

    if request.method == "POST":
        answers = {}

        for field in fields:
            fname = field["name"]
            ftype = field["type"]

            if ftype == "checkbox":
                # תיבת סימון יחידה - כן/לא
                value = request.form.get(fname)
                answers[fname] = bool(value)

            elif ftype == "checkbox_group":
                # רשימת צ'קבוקסים - כמה אפשרויות
                values = request.form.getlist(fname + "[]")
                answers[fname] = values

            else:
                value = request.form.get(fname)
                answers[fname] = value

        response_doc = {
            "form_id": form["_id"],
            "answers": answers,
            "created_at": datetime.utcnow()
        }

        response_col.insert_one(response_doc)
        return render_template("form_thanks.html", form=form)

    return render_template("form_public.html", form=form)


@app.route("/forms/<form_id>/responses")
def form_responses(form_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    # מוצאים את הטופס
    try:
        form = form_col.find_one({"_id": ObjectId(form_id)})
    except:
        form = None

    if not form:
        return "Form not found", 404

    # לוודא שהטופס שייך למשתמש המחובר
    if str(form["owner_id"]) != session["user_id"]:
        return "Unauthorized", 403

    # כל התשובות לטופס הזה
    responses = list(response_col.find({"form_id": form["_id"]}))

    return render_template("form_responses.html", form=form, responses=responses)


@app.route("/logout")
def logout():
    session.clear()
    flash("התנתקת מהמערכת", "success")
    return redirect(url_for("index"))


if __name__ == '__main__':
    app.run(debug=True, port=5007)
