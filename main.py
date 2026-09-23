import sqlite3
import threading
import scratchattach as sa
import time
import os
import warnings
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

def init_db():
    conn = sqlite3.connect('oswars.db')
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

init_db()

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
                
            cloud = session.connect_cloud(project_id="1379095740")
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
                
            cloud2 = session2.connect_cloud(project_id="1379095740")
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