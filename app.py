import hmac
import os
import re
import secrets
import hashlib
from html.parser import HTMLParser
from datetime import date, datetime, timezone
from functools import wraps
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from database import Database
from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

app = Flask(__name__, template_folder=".", static_folder=None)

YOUTUBE_CHANNEL_URL = "https://www.youtube.com/channel/UCWZD5jrTFf8GoIigABi8RkA"
YOUTUBE_CHANNEL_ID = "UCWZD5jrTFf8GoIigABi8RkA"
FACEBOOK_PAGE_URL = "https://www.facebook.com/p/RCM-RADIO-61585037325434/"
FACEBOOK_LIVE_URL = (
    "https://www.facebook.com/61585037325434/videos/1597956511645496/"
)
YOUTUBE_FEED_URL = (
    "https://www.youtube.com/feeds/videos.xml?"
    f"channel_id={YOUTUBE_CHANNEL_ID}"
)
DATABASE_PATH = os.path.join(app.instance_path, "rcm_radio.sqlite3")
NEWS_STORE_PATH = os.path.join(app.instance_path, "news.json")
ACCOUNTS_STORE_PATH = os.path.join(app.instance_path, "accounts.json")
SECRET_KEY_PATH = os.path.join(app.instance_path, "flask_secret_key")
database = Database(DATABASE_PATH)
PASSWORD_HASH_ITERATIONS = 600_000


def load_or_create_secret_key():
    configured_key = os.environ.get("FLASK_SECRET_KEY")
    if configured_key:
        return configured_key

    os.makedirs(app.instance_path, exist_ok=True)
    try:
        with open(SECRET_KEY_PATH, encoding="utf-8") as secret_file:
            return secret_file.read().strip()
    except FileNotFoundError:
        secret_key = secrets.token_hex(32)
        try:
            with open(SECRET_KEY_PATH, "x", encoding="utf-8") as secret_file:
                secret_file.write(secret_key)
        except FileExistsError:
            with open(SECRET_KEY_PATH, encoding="utf-8") as secret_file:
                return secret_file.read().strip()
        return secret_key


app.config["SECRET_KEY"] = load_or_create_secret_key()


class YouTubeFeedParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries = []
        self.current_entry = None
        self.current_field = None
        self.field_value = []

    def handle_starttag(self, tag, attrs):
        if tag == "entry":
            self.current_entry = {}
        elif self.current_entry is not None and tag in (
            "yt:videoid",
            "title",
            "published",
            "updated",
        ):
            self.current_field = tag
            self.field_value = []

    def handle_data(self, data):
        if self.current_field is not None:
            self.field_value.append(data)

    def handle_endtag(self, tag):
        if self.current_field == tag and self.current_entry is not None:
            self.current_entry[self.current_field] = "".join(self.field_value).strip()
            self.current_field = None
            self.field_value = []
        elif tag == "entry" and self.current_entry is not None:
            self.entries.append(self.current_entry)
            self.current_entry = None


def hash_password(password, salt=None):
    password_salt = salt or secrets.token_hex(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(password_salt),
        PASSWORD_HASH_ITERATIONS,
    ).hex()
    return password_salt, password_hash


def verify_password(account, password):
    _, supplied_hash = hash_password(password, account["password_salt"])
    return hmac.compare_digest(supplied_hash, account["password_hash"])


def validate_account_fields(username, role, password, password_required=True):
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,12}", username):
        return "Usernames must be 3-12 characters: letters, numbers, ., _, @, or -."
    if role not in ("journalist", "editor"):
        return "Choose a valid role."
    if password_required and len(password) < 12:
        return "Passwords must be at least 12 characters long."
    if password and len(password) < 12:
        return "New passwords must be at least 12 characters long."
    if len(password) > 56:
        return "Passwords cannot exceed 56 characters."
    return None


def get_session_account():
    account_id = session.get("account_id")
    if account_id is None:
        return None
    return database.get_account(account_id, active_only=True)


@app.context_processor
def inject_platform_links():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    account = get_session_account()
    return {
        "youtube_channel_url": YOUTUBE_CHANNEL_URL,
        "youtube_channel_id": YOUTUBE_CHANNEL_ID,
        "facebook_page_url": FACEBOOK_PAGE_URL,
        "facebook_live_url": FACEBOOK_LIVE_URL,
        "user_role": account["role"] if account else None,
        "csrf_token": session["csrf_token"],
    }


def require_journalist(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        account = get_session_account()
        if account is None or account["role"] not in ("journalist", "editor"):
            session.clear()
            flash("Please sign in with your RCM journalist account.", "error")
            return redirect(url_for("journalist_login"))
        g.account = account
        return view(*args, **kwargs)

    return wrapped_view


def require_editor(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        account = get_session_account()
        if account is None:
            session.clear()
            flash("Please sign in with your RCM editor account.", "error")
            return redirect(url_for("journalist_login"))
        if account["role"] != "editor":
            abort(403)
        g.account = account
        return view(*args, **kwargs)

    return wrapped_view


def validate_csrf():
    supplied_token = request.form.get("csrf_token", "")
    session_token = session.get("csrf_token", "")
    if not session_token or not hmac.compare_digest(supplied_token, session_token):
        abort(400, description="Invalid form token. Refresh the page and try again.")


def get_published_articles():
    articles = database.get_articles(published_only=True)
    for article in articles:
        article["program_title"] = program_title(article["program_id"])
    return articles


def program_title(program_id):
    return database.get_program_title(program_id)


def is_valid_source_url(value):
    try:
        parsed_url = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed_url.scheme in ("http", "https")
        and parsed_url.hostname is not None
        and parsed_url.username is None
        and parsed_url.password is None
    )


def fetch_youtube_videos():
    feed_request = Request(
        YOUTUBE_FEED_URL,
        headers={"User-Agent": "RCMMedia/1.0 (+https://www.youtube.com/)"},
    )
    with urlopen(feed_request, timeout=8) as response:
        feed_xml = response.read().decode("utf-8-sig")
    if "<feed" not in feed_xml.lower():
        raise ValueError("The YouTube channel returned an invalid feed.")

    parser = YouTubeFeedParser()
    parser.feed(feed_xml)
    parser.close()

    videos = []
    for entry in parser.entries:
        video_id = entry.get("yt:videoid", "")
        title = entry.get("title", "")
        published_at = entry.get("published", entry.get("updated", ""))
        if not video_id or not title:
            continue

        matched_program = next(
            (
                item["title"]
                for item in PROGRAMS
                if item["title"].casefold() in title.casefold()
            ),
            None,
        )
        series = matched_program
        if series is None and " | " in title:
            series = title.rsplit(" | ", 1)[1].strip()
        if series is None and " - " in title:
            series = title.rsplit(" - ", 1)[1].strip()
        videos.append(
            {
                "id": video_id,
                "title": title,
                "published_at": published_at,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "program": matched_program,
                "series": series or "Other RCM Media videos",
            }
        )
    return sequence_channel_videos(videos)


def sequence_channel_videos(videos):
    series_queues = {}
    for video in videos:
        series_queues.setdefault(video["series"], []).append(video)

    sequence = []
    while any(series_queues.values()):
        for video_queue in series_queues.values():
            if video_queue:
                sequence.append(video_queue.pop(0))
    return sequence


# ====================== VERIFIED RCM RADIO PROGRAMMING ======================
PROGRAMS = [
    {
        "id": 1,
        "title": "RCM BREAKFAST",
        "host": "NOAH ESOKON",
        "time": "06:00 - 10:00",
        "status": "live",
        "category": "Live broadcast",
        "category_id": "live",
        "description": "Tune in to RCM Radio's live broadcast .",
        "icon": "fa-tower-broadcast",
        "url": FACEBOOK_LIVE_URL,
        "action_label": "Open broadcast on Facebook",
    },
    {
        "id": 2,
        "title": "GUMZO 254",
        "host": "GLORIA BRIDGET AND RAEL JEPNGETICH ",
        "time": "10:00 - 13:00",
        "status": "format",
        "category": "News",
        "category_id": "news",
        "description": "The latest news and stories from the community.",
        "icon": "fa-newspaper",
    },
    {
        "id": 3,
        "title": "VIBES MTAANI",
        "host": "JARED KWE AND CRAFT YUN",
        "time": "13:00 - 16:00",
        "status": "format",
        "category": "Trending stories",
        "category_id": "trending",
        "description": "Trending stories and conversations that matter to listeners.",
        "icon": "fa-arrow-trend-up",
    },
    {
        "id": 4,
        "title": "RCM DRIVE ",
        "host": "FESTUS ANDAYI ",
        "time": "16:00 - 18:00",
        "status": "format",
        "category": "Business",
        "category_id": "business",
        "description": "Business insights to inform and inspire the community.",
        "icon": "fa-briefcase",
    },
    {
        "id": 5,
        "title": "AROUND THE WORLD",
        "host": "OLILO AND PAPSI ",
        "time": "18:00 - 21:00",
        "status": "format",
        "category": "Music",
        "category_id": "music",
        "description": "Hit music around the clock, as described on RCM Radio's Facebook page.",
        "icon": "fa-music",
    }
]

database.initialize(PROGRAMS, NEWS_STORE_PATH, ACCOUNTS_STORE_PATH)

# ====================== ROUTES ======================

@app.route("/")
@app.route("/blog")
def index():
    return render_template("index.html", articles=get_published_articles())


@app.route("/dashboard")
@app.route("/shows")
def dashboard():
    return render_template("Dashboard.html")


@app.route("/programs")
def programs():
    return render_template("Program.html")


@app.route("/news")
def news():
    return render_template("News.html", articles=get_published_articles())


@app.route("/setup", methods=["GET", "POST"])
def initial_setup():
    if database.has_accounts():
        return redirect(url_for("journalist_login"))

    if request.method == "POST":
        validate_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirmation", "")
        error = validate_account_fields(username, "editor", password)
        if error:
            flash(error, "error")
        elif password != confirmation:
            flash("The passwords do not match.", "error")
        else:
            salt, password_hash = hash_password(password)
            account_id = database.create_initial_editor(
                {
                    "username": username,
                    "password_salt": salt,
                    "password_hash": password_hash,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            if account_id is None:
                return redirect(url_for("journalist_login"))
            flash("First editor account created. Sign in to manage accounts.", "success")
            return redirect(url_for("journalist_login"))

    return render_template("AccountSetup.html")


@app.route("/journalist/login", methods=["GET", "POST"])
def journalist_login():
    current_account = get_session_account()
    if current_account:
        destination = "editor" if current_account["role"] == "editor" else "journalist_submit"
        return redirect(url_for(destination))

    accounts_exist = database.has_accounts()
    if request.method == "POST":
        validate_csrf()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        account = (
            database.find_account_by_username(username)
            if len(username) <= 64 and len(password) <= 1024
            else None
        )
        if account and account["active"] and verify_password(account, password):
            session.clear()
            session["account_id"] = account["id"]
            session["user_role"] = account["role"]
            flash(f"Signed in as {account['role']}.", "success")
            destination = "editor" if account["role"] == "editor" else "journalist_submit"
            return redirect(url_for(destination))
        else:
            flash("The username or password is incorrect.", "error")

    return render_template(
        "JournalistLogin.html",
        accounts_exist=accounts_exist,
    )


@app.route("/journalist/logout", methods=["POST"])
@require_journalist
def journalist_logout():
    validate_csrf()
    session.clear()
    flash("You have signed out.", "success")
    return redirect(url_for("index"))


@app.route("/journalist/submit", methods=["GET", "POST"])
@require_journalist
def journalist_submit():
    if request.method == "POST":
        validate_csrf()
        headline = request.form.get("headline", "").strip()
        author = request.form.get("author", "").strip()
        body = request.form.get("body", "").strip()
        source_url = request.form.get("source_url", "").strip()
        reported_date = request.form.get("reported_date", "").strip()
        program_value = request.form.get("program_id", "").strip()
        try:
            date.fromisoformat(reported_date)
        except ValueError:
            flash("Enter a valid report date.", "error")
        else:
            programs = database.get_programs()
            valid_program_ids = {str(program["id"]) for program in programs}
            if program_value and program_value not in valid_program_ids:
                flash("Select a valid show or program.", "error")
            elif not headline or len(headline) > 200:
                flash("Headlines must be between 1 and 200 characters.", "error")
            elif not author or len(author) > 100:
                flash("Enter an author name (up to 100 characters).", "error")
            elif not body or len(body) > 20000:
                flash("Reports must be between 1 and 20,000 characters.", "error")
            elif source_url and (
                len(source_url) > 2048 or not is_valid_source_url(source_url)
            ):
                flash("Source links must be valid HTTP or HTTPS URLs.", "error")
            else:
                database.create_article(
                    {
                        "headline": headline,
                        "author": author,
                        "body": body,
                        "source_url": source_url,
                        "program_id": int(program_value) if program_value else None,
                        "submitted_by": g.account["id"],
                        "reported_date": reported_date,
                        "submitted_at": datetime.now(timezone.utc).isoformat(),
                        "status": "draft",
                    }
                )
                flash("Report saved as a draft for editor review.", "success")
                return redirect(url_for("editor"))

    return render_template(
        "SubmitReport.html",
        programs=database.get_programs(),
        today=date.today().isoformat(),
    )


@app.route("/editor")
@require_editor
def editor():
    articles = database.get_articles()
    for article in articles:
        article["program_title"] = program_title(article["program_id"])
    articles.sort(
        key=lambda article: (
            article["status"] != "draft",
            article["reported_date"],
            article["id"],
        )
    )
    return render_template("Editor.html", articles=articles)


@app.route("/editor/accounts", methods=["GET", "POST"])
@require_editor
def manage_accounts():
    if request.method == "POST":
        validate_csrf()
        username = request.form.get("username", "").strip()
        role = request.form.get("role", "")
        password = request.form.get("password", "")
        error = validate_account_fields(username, role, password)
        if error:
            flash(error, "error")
        else:
            salt, password_hash = hash_password(password)
            account_id = database.create_account(
                {
                    "username": username,
                    "role": role,
                    "password_salt": salt,
                    "password_hash": password_hash,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            if account_id is None:
                flash("That username is already in use.", "error")
            else:
                flash(f"{role.title()} account created.", "success")
                return redirect(url_for("manage_accounts"))

    accounts = database.get_accounts()
    return render_template("Accounts.html", accounts=accounts)


@app.route("/editor/accounts/<int:account_id>", methods=["POST"])
@require_editor
def update_account(account_id):
    validate_csrf()
    username = request.form.get("username", "").strip()
    role = request.form.get("role", "")
    password = request.form.get("password", "")
    active = request.form.get("active") == "on"
    error = validate_account_fields(username, role, password, password_required=False)
    if error:
        flash(error, "error")
        return redirect(url_for("manage_accounts"))

    salt = password_hash = None
    if password:
        salt, password_hash = hash_password(password)
    result = database.update_account(
        account_id,
        username,
        role,
        active,
        salt,
        password_hash,
    )
    if result == "not_found":
        abort(404)
    if result == "duplicate":
        flash("That username is already in use.", "error")
    elif result == "last_editor":
        flash("Keep at least one active editor account.", "error")
    else:
        signing_out = account_id == g.account["id"] and (
            not active or role != "editor"
        )
        if signing_out:
            session.clear()
        flash("Account updated.", "success")
        destination = "journalist_login" if signing_out else "manage_accounts"
        return redirect(url_for(destination))

    return redirect(url_for("manage_accounts"))


@app.route("/editor/publish/<int:article_id>", methods=["POST"])
@require_editor
def publish_article(article_id):
    validate_csrf()
    if not database.publish_article(article_id):
        abort(404)
    flash("Report published on the RCM news page.", "success")
    return redirect(url_for("editor"))


@app.route("/static/css/style.css")
def stylesheet():
    return send_from_directory(app.root_path, "Static.css")


@app.route("/static/js/script.js")
def javascript():
    return send_from_directory(app.root_path, "script.js")


@app.route("/static/images/rcm-radio-logo.png")
def brand_logo():
    return send_from_directory(
        os.path.join(app.root_path, "static", "images"),
        "rcm-radio-logo.png",
        mimetype="image/png",
    )


# ---------- API ENDPOINTS ----------
@app.route("/api/youtube-videos")
def api_youtube_videos():
    try:
        return jsonify(fetch_youtube_videos())
    except (URLError, TimeoutError, UnicodeDecodeError, ValueError) as error:
        app.logger.error("Could not load the RCM Media YouTube feed: %s", error)
        return jsonify(error="RCM Media videos are temporarily unavailable."), 502


@app.route("/api/live")
def api_live():
    live = next(
        (program for program in database.get_programs() if program["status"] == "live"),
        None,
    )
    return jsonify(live)

@app.route("/api/programs")
def api_programs():
    return jsonify(database.get_programs())

@app.route("/api/recorded")
def api_recorded():
    recorded = [
        program
        for program in database.get_programs()
        if program["status"] == "recorded"
    ]
    return jsonify(recorded)

@app.route("/api/upcoming")
def api_upcoming():
    upcoming = [
        program
        for program in database.get_programs()
        if program["status"] == "upcoming"
    ]
    return jsonify(upcoming)

# --- REQUIRED FOR CPANEL DEPLOYMENT ---
# Expose the WSGI callable named 'application' for Passenger
application = app

if __name__ == "__main__":
    print("\nRCM Radio Media Blog is running!")
    print("Open http://127.0.0.1:5000 in your browser\n")
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
        use_reloader=False,
    )