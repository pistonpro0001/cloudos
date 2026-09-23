import sqlite3
import threading
import scratchattach as sa
import time
import os
import warnings
import json
import hashlib
from urllib.parse import quote
import requests
from flask import Flask
from website_and_encode import decode_numbers_to_string as dns
from website_and_encode import encode_string_to_numbers as esn
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings('ignore', category=sa.LoginDataWarning)

# --- SCRATCHATTACH BUG #608 PATCH ---
try:
    original_process = sa.Session._process_session_id
    def patched_process_session_id(self):
        try:
            original_process(self)
        except KeyError as e:
            if str(e) == "'_language'":
                self.language = "en"
            else:
                raise e
    sa.Session._process_session_id = patched_process_session_id
except AttributeError:
    pass 

app = Flask(__name__)
status = ['<span style="color:gold">Booting OS Server...</span>']

def log(msg, color="grey"):
    global status
    status.append(f'<span style="color:{color}">{msg}</span>')
    print(msg)

@app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>cloudos Logs</title>
        <style>
            body { background-color: #1e1e1e; color: #d4d4d4; font-family: monospace; padding: 20px; }
            #logs { font-size: 22px; white-space: pre-wrap; word-wrap: break-word; }
        </style>
    </head>
    <body>
        <div id="logs">Loading logs...</div>
        <script>
            function fetchLogs() {
                fetch('/raw_logs')
                    .then(response => response.text())
                    .then(data => {
                        const logDiv = document.getElementById('logs');
                        logDiv.innerHTML = data;
                    });
            }
            fetchLogs();
            setInterval(fetchLogs, 1000);
        </script>
    </body>
    </html>
    """

@app.route('/raw_logs')
def raw_logs():
    return "\n".join(status[-150:])

DB_PATH = "oswars.db"
GOFILE_STATE_PATH = os.getenv("GOFILE_STATE_PATH", ".gofile_db_state.json")
GOFILE_BOOTSTRAP_URL = os.getenv("GOFILE_DB_URL", "").strip()
GOFILE_TOKEN = os.getenv("GOFILE_TOKEN", "").strip()
GOFILE_UPLOAD_URL = "https://upload.gofile.io/uploadfile"
GOFILE_API_URL = "https://api.gofile.io"
GOFILE_POLL_SECONDS = float(os.getenv("GOFILE_POLL_SECONDS", "2"))
_gofile_lock = threading.Lock()
_gofile_last_hash = None
_gofile_restoring = False


def _gofile_headers():
    if not GOFILE_TOKEN:
        raise RuntimeError("GOFILE_TOKEN is not set")
    return {"Authorization": f"Bearer {GOFILE_TOKEN}"}


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_gofile_state():
    try:
        with open(GOFILE_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save_gofile_state(state):
    tmp = GOFILE_STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, GOFILE_STATE_PATH)


def _validate_sqlite(path):
    conn = sqlite3.connect(path)
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()
        return bool(result and result[0] == "ok")
    finally:
        conn.close()


def _direct_url_from_upload(data):
    servers = data.get("servers") or []
    server = data.get("serverSelected") or data.get("serverChoosen")
    if not server and servers:
        server = servers[0]

    file_id = data.get("id")
    name = data.get("name") or data.get("fileName") or "oswars.db"

    if server and file_id:
        return f"https://{server}.gofile.io/download/web/{file_id}/{quote(name)}"
    return None


def gofile_restore_on_boot():
    global _gofile_last_hash, _gofile_restoring

    if not GOFILE_TOKEN:
        log("GOFILE_TOKEN is not set; Gofile sync disabled.", "gold")
        return False

    state = _load_gofile_state()
    download_url = state.get("download_url") or GOFILE_BOOTSTRAP_URL

    if not download_url:
        log(
            "No Gofile DB URL/state found. Keeping local oswars.db; "
            "the first successful sync will create the remote copy.",
            "gold",
        )
        return False

    _gofile_restoring = True
    tmp_path = DB_PATH + ".gofile-download.tmp"

    try:
        log("Downloading oswars.db from Gofile...", "blue")
        response = requests.get(
            download_url,
            headers=_gofile_headers(),
            timeout=60,
            stream=True,
            allow_redirects=True,
        )
        response.raise_for_status()

        with open(tmp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

        if not _validate_sqlite(tmp_path):
            raise RuntimeError("Downloaded file is not a valid SQLite database")

        os.replace(tmp_path, DB_PATH)
        _gofile_last_hash = _file_sha256(DB_PATH)
        log("Restored oswars.db from Gofile.", "lime")
        return True

    except Exception as e:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        log(f"Gofile boot restore failed: {e}", "red")
        return False
    finally:
        _gofile_restoring = False


def gofile_upload_db():
    global _gofile_last_hash

    if not GOFILE_TOKEN:
        return False

    with _gofile_lock:
        if not os.path.exists(DB_PATH):
            return False

        try:
            current_hash = _file_sha256(DB_PATH)
            if current_hash == _gofile_last_hash:
                return False

            state = _load_gofile_state()
            old_id = state.get("file_id")
            folder_id = state.get("folder_id")

            file_handle = open(DB_PATH, "rb")
            try:
                files = {
                    "file": ("oswars.db", file_handle, "application/x-sqlite3")
                }
                data = {}
                if folder_id:
                    data["folderId"] = folder_id

                log("Uploading changed oswars.db to Gofile...", "blue")
                response = requests.post(
                    GOFILE_UPLOAD_URL,
                    headers=_gofile_headers(),
                    files=files,
                    data=data,
                    timeout=120,
                )
            finally:
                file_handle.close()

            response.raise_for_status()
            payload = response.json()

            if payload.get("status") != "ok":
                raise RuntimeError(f"Gofile upload failed: {payload}")

            uploaded = payload.get("data", {})
            new_id = uploaded.get("id")
            if not new_id:
                raise RuntimeError(f"Gofile returned no file ID: {payload}")

            new_url = _direct_url_from_upload(uploaded)
            if not new_url:
                raise RuntimeError(
                    "Gofile upload succeeded but no downloadable storage URL "
                    "was returned"
                )

            new_state = {
                "file_id": new_id,
                "folder_id": uploaded.get("parentFolder") or folder_id,
                "download_url": new_url,
                "download_page": uploaded.get("downloadPage"),
                "name": uploaded.get("name") or "oswars.db",
                "sha256": current_hash,
            }
            _save_gofile_state(new_state)
            _gofile_last_hash = current_hash

            if old_id and old_id != new_id:
                try:
                    delete_response = requests.delete(
                        f"{GOFILE_API_URL}/contents",
                        headers={
                            **_gofile_headers(),
                            "Content-Type": "application/json",
                        },
                        json={"contentsId": old_id},
                        timeout=30,
                    )
                    delete_payload = delete_response.json()
                    if delete_payload.get("status") != "ok":
                        log(
                            f"Uploaded new DB, but old Gofile copy was not "
                            f"deleted: {delete_payload}",
                            "gold",
                        )
                except Exception as e:
                    log(f"Uploaded new DB, but old copy delete failed: {e}", "gold")

            log("oswars.db synced to Gofile.", "lime")
            return True

        except Exception as e:
            log(f"Gofile DB upload failed: {e}", "red")
            return False


def start_gofile_sync():
    global _gofile_last_hash

    if not GOFILE_TOKEN:
        return

    if os.path.exists(DB_PATH) and _gofile_last_hash is None:
        try:
            _gofile_last_hash = _file_sha256(DB_PATH)
        except OSError:
            pass

    while True:
        try:
            if not _gofile_restoring and os.path.exists(DB_PATH):
                current_hash = _file_sha256(DB_PATH)
                if current_hash != _gofile_last_hash:
                    gofile_upload_db()
        except Exception as e:
            log(f"Gofile watcher error: {e}", "red")
        time.sleep(GOFILE_POLL_SECONDS)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    background TEXT,
                    icon TEXT,
                    brightness TEXT,
                    color TEXT,
                    theme TEXT
                )''')
    conn.commit()
    conn.close()


gofile_restore_on_boot()
init_db()

if GOFILE_TOKEN:
    threading.Thread(target=start_gofile_sync, daemon=True).start()

save_queue = []
get_queue = []

def run_bot():
    global save_queue, get_queue
    try_ = 0
    while True:
        try:
            try:
                session = sa.login(os.getenv("SCRATCH_USER"), os.getenv("SCRATCH_PASS"))
                log(f"Executor login as {os.getenv('SCRATCH_USER')} successful.", "gold")
            except:
                log("Executor falling back to Session ID...", "red")
                session = sa.login_by_id(os.getenv("SC_SESS_ID"))
                
            cloud = session.connect_cloud(project_id="1384039906")
            log("Executor Cloud Connection Ready", "lime")
            
            while True:
                time.sleep(0.2)
                
                if len(save_queue) > 0:
                    hit = save_queue.pop(0)
                    decoded_hit = dns(hit)
                    log(f"Decoding SAVE payload: {decoded_hit}")
                    
                    parts = decoded_hit[:-1].split('/')
                    if len(parts) == 7:
                        user, pwd, bg, icon, bright, color, theme = parts
                        
                        conn = sqlite3.connect('oswars.db')
                        c = conn.cursor()
                        c.execute('''REPLACE INTO users (username, password, background, icon, brightness, color, theme)
                                     VALUES (?, ?, ?, ?, ?, ?, ?)''', (user, pwd, bg, icon, bright, color, theme))
                        conn.commit()
                        conn.close()
                        log(f"Saved DB data for user: {user}", "lime")
                    else:
                        log(f"Invalid payload structure. Expected 7 parameters, got {len(parts)}", "red")

                if len(get_queue) > 0:
                    req_hit = get_queue.pop(0)
                    target_user = dns(req_hit)
                    log(f"Fetching DB record for: {target_user}")
                    
                    conn = sqlite3.connect('oswars.db')
                    c = conn.cursor()
                    c.execute("SELECT username, password, background, icon, brightness, color, theme FROM users WHERE username = ?", (target_user,))
                    row = c.fetchone()
                    conn.close()
                    
                    if row:
                        formatted_str = "/".join([str(item) for item in row])
                        print(esn(formatted_str))
                        cloud.set_var("USER DATA RECIEVER", esn(formatted_str))
                        log(f"Dispatched data for user {target_user}", "lime")
                    else:
                        print(esn("not_found"))
                        cloud.set_var("USER DATA RECIEVER", esn("not_found"))
                        log(f"User {target_user} not found in database", "gold")

        except Exception as e:
            try_ += 1
            log(f'Bot executor errored: "{e}", try #{try_}', "red")
            time.sleep(3)

def start_listener():
    global save_queue, get_queue
    try_ = 0
    while True:
        try:
            try:
                session2 = sa.login(os.getenv("SCRATCH_USER"), os.getenv("SCRATCH_PASS"))
            except:
                session2 = sa.login_by_id(os.getenv("SC_SESS_ID"))
                
            cloud2 = session2.connect_cloud(project_id="1384039906")
            events = cloud2.events()
            
            @events.event
            def on_set(activity):
                print(activity.var)
                global save_queue, get_queue
                
                if activity.var == "CLOUD 1":
                    val = str(activity.value).strip()
                    if val != "0" and val != "":
                        log(f"Scanner found CLOUD 1 payload.", "purple")
                        save_queue.append(val)
                        try:
                            cloud2.set_var("CLOUD 1", "0")
                        except:
                            pass
                            
                elif activity.var == "GET_USER":
                    val = str(activity.value).strip()
                    if val != "0" and val != "":
                        log(f"Scanner found GET_USER request.", "purple")
                        get_queue.append(val)
                        try:
                            pass
                            #cloud2.set_var("GET_USER", "0")
                        except:
                            pass

                elif activity.var == "PING":
                    val = str(activity.value).strip()
                    if val != "0" and val != "":
                        log(f"Ping requested. Acknowledging...", "blue")
                        try:
                            cloud2.set_var("PING", "0")
                        except:
                            pass

            log("Cloud WebSocket listener active.", "lime")
            events.start(thread=False)

        except Exception as e:
            try_ += 1
            log(f'Scanner error: "{e}", try #{try_}', "red")
            time.sleep(5)

threading.Thread(target=start_listener, daemon=True).start()
threading.Thread(target=run_bot, daemon=True).start()

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=11306)