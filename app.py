"""
Personal Attendance Tracker – Single File Flask App
====================================================
Routes:
  /            Today  – clock in / out, mark holiday
  /calendar    Calendar view with edit / delete per day
  /settings    Change timezone, manage settings
  /entry/edit  (POST) Save edited entry
  /entry/delete(POST) Delete an entry
  /mark        (POST) Clock-in / clock-out / holiday
  /unmark_holiday (POST)

Data stored in SQLite3:  attendance.db  (next to this file)
"""

import os
import sqlite3
import calendar as cal_mod
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from markupsafe import Markup
from flask import (
    Flask, g, redirect, render_template_string, request, url_for
)

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, "attendance.db")

app = Flask(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    """Create tables on first run."""
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS attendance (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                date     TEXT UNIQUE NOT NULL,
                status   TEXT NOT NULL DEFAULT 'none',
                time_in  TEXT,
                time_out TEXT,
                note     TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO settings (key, value)
            VALUES ('timezone', 'Asia/Karachi');
        """)


def get_setting(key: str, default: str = "") -> str:
    row = get_db().execute(
        "SELECT value FROM settings WHERE key=?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    get_db().execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value)
    )
    get_db().commit()


def get_tz() -> ZoneInfo:
    tz_name = get_setting("timezone", "Asia/Karachi")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def now_local() -> datetime:
    return datetime.now(get_tz())


def today_str() -> str:
    return now_local().date().isoformat()


def fmt_time(iso: str) -> str:
    """'2025-06-01T09:05:00+05:00' → '09:05 AM'"""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%I:%M %p")
    except Exception:
        return iso


def hours_between(t_in: str, t_out: str) -> str:
    if not t_in or not t_out:
        return ""
    try:
        a = datetime.fromisoformat(t_in)
        b = datetime.fromisoformat(t_out)
        mins = int((b - a).total_seconds() // 60)
        h, m = divmod(abs(mins), 60)
        return f"{h}h {m:02d}m"
    except Exception:
        return ""


def get_record(day: str) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT * FROM attendance WHERE date=?", (day,)
    ).fetchone()


def upsert_record(day: str, status: str,
                  time_in: str | None = None,
                  time_out: str | None = None,
                  note: str | None = None):
    db = get_db()
    existing = db.execute(
        "SELECT id FROM attendance WHERE date=?", (day,)
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE attendance SET status=?,time_in=?,time_out=?,note=? WHERE date=?",
            (status, time_in, time_out, note, day)
        )
    else:
        db.execute(
            "INSERT INTO attendance(date,status,time_in,time_out,note) "
            "VALUES(?,?,?,?,?)",
            (day, status, time_in, time_out, note)
        )
    db.commit()


def delete_record(day: str):
    db = get_db()
    db.execute("DELETE FROM attendance WHERE date=?", (day,))
    db.commit()


def mark_past_absent():
    """Backfill every un-recorded past day as absent."""
    db    = get_db()
    today = now_local().date()
    yesterday = today - timedelta(days=1)

    first_row = db.execute(
        "SELECT MIN(date) AS d FROM attendance"
    ).fetchone()
    if not first_row or not first_row["d"]:
        return

    first  = date.fromisoformat(first_row["d"])
    cursor = first
    existing = {
        r["date"] for r in db.execute("SELECT date FROM attendance").fetchall()
    }
    rows = []
    while cursor <= yesterday:
        key = cursor.isoformat()
        if key not in existing:
            rows.append((key, "absent"))
        cursor += timedelta(days=1)

    if rows:
        db.executemany(
            "INSERT OR IGNORE INTO attendance(date,status) VALUES(?,?)", rows
        )
        db.commit()


def compute_stats() -> dict:
    rows = get_db().execute("SELECT * FROM attendance").fetchall()
    present = absent = holidays = 0
    total_mins = 0
    for r in rows:
        st = r["status"]
        if st == "holiday":
            holidays += 1
        elif st == "absent":
            absent += 1
        elif r["time_in"] and r["time_out"]:
            present += 1
            try:
                a = datetime.fromisoformat(r["time_in"])
                b = datetime.fromisoformat(r["time_out"])
                total_mins += int((b - a).total_seconds() // 60)
            except Exception:
                pass
    h, m = divmod(total_mins, 60)
    return {
        "present":     present,
        "absent":      absent,
        "holidays":    holidays,
        "total_hours": f"{h}h {m:02d}m",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Jinja2 filters
# ──────────────────────────────────────────────────────────────────────────────
@app.template_filter("fmt_time")
def jinja_fmt_time(v):
    return fmt_time(v) if v else ""


@app.template_filter("hours_between")
def jinja_hours_between(t_in, t_out):
    return hours_between(t_in, t_out)


# ──────────────────────────────────────────────────────────────────────────────
# Common timezones list for settings page
# ──────────────────────────────────────────────────────────────────────────────
COMMON_TIMEZONES = [
    "UTC",
    "Asia/Karachi",
    "Asia/Kolkata",
    "Asia/Dhaka",
    "Asia/Dubai",
    "Asia/Riyadh",
    "Asia/Baghdad",
    "Asia/Istanbul",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Moscow",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Toronto",
    "America/Sao_Paulo",
    "Africa/Cairo",
    "Africa/Lagos",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Asia/Singapore",
    "Australia/Sydney",
    "Pacific/Auckland",
]


# ──────────────────────────────────────────────────────────────────────────────
# Shared CSS
# ──────────────────────────────────────────────────────────────────────────────
BASE_STYLE = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d0f14; --surface:#13161e; --surface2:#1a1e2a; --border:#252a38;
  --accent:#6c63ff; --ag:rgba(108,99,255,.35);
  --green:#22d3a5;  --gg:rgba(34,211,165,.25);
  --red:#ff5f6d;    --rg:rgba(255,95,109,.25);
  --amber:#f5a623;  --amg:rgba(245,166,35,.25);
  --text:#e8eaf0;   --muted:#6b7280; --r:16px;
}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;line-height:1.6}
nav{display:flex;align-items:center;justify-content:space-between;padding:18px 32px;
    background:var(--surface);border-bottom:1px solid var(--border);
    position:sticky;top:0;z-index:200;backdrop-filter:blur(12px)}
.brand{font-size:1.2rem;font-weight:800;
       background:linear-gradient(135deg,var(--accent),var(--green));
       -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.nav-links a{color:var(--muted);text-decoration:none;font-size:.9rem;font-weight:500;
             padding:8px 18px;border-radius:10px;transition:all .2s;margin-left:6px}
.nav-links a:hover,.nav-links a.active{color:var(--text);background:var(--surface2)}
.nav-links a.active{border:1px solid var(--border)}
.container{max-width:980px;margin:0 auto;padding:40px 24px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:28px}
/* buttons */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;
     padding:14px 32px;border:none;border-radius:12px;font-family:inherit;
     font-size:1rem;font-weight:600;cursor:pointer;
     transition:all .25s cubic-bezier(.34,1.56,.64,1);text-decoration:none}
.btn-green{background:linear-gradient(135deg,var(--green),#10b981);color:#000;box-shadow:0 4px 24px var(--gg)}
.btn-green:hover{transform:translateY(-2px) scale(1.02);box-shadow:0 8px 32px var(--gg)}
.btn-red{background:linear-gradient(135deg,var(--red),#f43f5e);color:#fff;box-shadow:0 4px 24px var(--rg)}
.btn-red:hover{transform:translateY(-2px) scale(1.02);box-shadow:0 8px 32px var(--rg)}
.btn-amber{background:linear-gradient(135deg,var(--amber),#f59e0b);color:#000;box-shadow:0 4px 24px var(--amg)}
.btn-amber:hover{transform:translateY(-2px) scale(1.02);box-shadow:0 8px 32px var(--amg)}
.btn-accent{background:linear-gradient(135deg,var(--accent),#8b5cf6);color:#fff;box-shadow:0 4px 24px var(--ag)}
.btn-accent:hover{transform:translateY(-2px) scale(1.02);box-shadow:0 8px 32px var(--ag)}
.btn-ghost{background:var(--surface2);color:var(--muted);border:1px solid var(--border)}
.btn-ghost:hover{color:var(--text);background:var(--border)}
.btn-icon{padding:8px 10px;border-radius:8px;font-size:.85rem}
.btn:active{transform:scale(.97)}
/* badges */
.badge{display:inline-block;padding:4px 12px;border-radius:99px;
       font-size:.75rem;font-weight:600;letter-spacing:.5px;text-transform:uppercase}
.badge-present{background:rgba(34,211,165,.15);color:var(--green);border:1px solid rgba(34,211,165,.3)}
.badge-absent{background:rgba(255,95,109,.15);color:var(--red);border:1px solid rgba(255,95,109,.3)}
.badge-holiday{background:rgba(245,166,35,.15);color:var(--amber);border:1px solid rgba(245,166,35,.3)}
.badge-partial{background:rgba(108,99,255,.15);color:var(--accent);border:1px solid rgba(108,99,255,.3)}
/* misc */
.text-muted{color:var(--muted);font-size:.9rem}
.mt-1{margin-top:8px}.mt-2{margin-top:16px}.mt-3{margin-top:24px}.mt-4{margin-top:32px}
.pdot{width:10px;height:10px;border-radius:50%;display:inline-block;animation:blink 1.6s infinite}
.pg{background:var(--green);box-shadow:0 0 8px var(--green)}
.pr{background:var(--red);box-shadow:0 0 8px var(--red)}
@keyframes blink{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(1.4)}}
.flash{padding:14px 20px;border-radius:12px;margin-bottom:20px;font-weight:500;border-left:4px solid;animation:slideIn .3s ease}
.flash-success{background:rgba(34,211,165,.1);border-color:var(--green);color:var(--green)}
.flash-info{background:rgba(108,99,255,.1);border-color:var(--accent);color:var(--accent)}
.flash-warning{background:rgba(245,166,35,.1);border-color:var(--amber);color:var(--amber)}
@keyframes slideIn{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:none}}
/* form inputs */
.field{display:flex;flex-direction:column;gap:6px;margin-bottom:20px}
.field label{font-size:.82rem;font-weight:600;color:var(--muted);letter-spacing:.4px;text-transform:uppercase}
.field input,.field select,.field textarea{
  background:var(--surface2);border:1px solid var(--border);border-radius:10px;
  color:var(--text);font-family:inherit;font-size:.95rem;padding:12px 14px;
  outline:none;transition:border-color .2s,box-shadow .2s;width:100%}
.field input:focus,.field select:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--ag)}
.field select option{background:var(--surface2);color:var(--text)}
/* ── Modal overlay ─────────────────────────────────────────────── */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(6px);
               z-index:1000;display:flex;align-items:center;justify-content:center;
               opacity:0;pointer-events:none;transition:opacity .25s}
.modal-overlay.open{opacity:1;pointer-events:all}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:20px;
       padding:32px;width:100%;max-width:480px;position:relative;
       transform:scale(.94) translateY(20px);transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
.modal-overlay.open .modal{transform:scale(1) translateY(0)}
.modal-close{position:absolute;top:16px;right:16px;background:var(--surface2);
             border:1px solid var(--border);border-radius:8px;
             color:var(--muted);cursor:pointer;padding:6px 10px;font-size:.9rem;
             font-family:inherit;transition:all .2s}
.modal-close:hover{color:var(--text);background:var(--border)}
.modal-title{font-size:1.25rem;font-weight:700;margin-bottom:6px}
.modal-sub{color:var(--muted);font-size:.88rem;margin-bottom:24px}
/* ── Clock picker ──────────────────────────────────────────────── */
.clock-wrap{display:flex;gap:24px;align-items:flex-start;margin-bottom:24px}
.clock-face{flex-shrink:0}
.clock-face svg{display:block}
.clock-inputs{flex:1}
.time-picker-row{display:flex;align-items:center;gap:8px;margin-bottom:12px}
.time-picker-row label{font-size:.78rem;font-weight:600;color:var(--muted);
                        text-transform:uppercase;letter-spacing:.4px;width:36px}
.tp-input{background:var(--surface2);border:1px solid var(--border);border-radius:10px;
          color:var(--text);font-family:'Inter',monospace;font-size:1.4rem;font-weight:700;
          padding:10px 14px;outline:none;text-align:center;width:100%;
          transition:border-color .2s,box-shadow .2s}
.tp-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--ag)}
/* status radio tabs */
.status-tabs{display:flex;gap:8px;margin-bottom:24px}
.status-tab input{display:none}
.status-tab label{display:inline-flex;align-items:center;gap:6px;
                  padding:9px 16px;border-radius:10px;font-size:.85rem;font-weight:600;
                  cursor:pointer;border:1px solid var(--border);color:var(--muted);
                  background:var(--surface2);transition:all .2s}
.status-tab input:checked + label.l-present{background:rgba(34,211,165,.15);color:var(--green);border-color:rgba(34,211,165,.4)}
.status-tab input:checked + label.l-absent{background:rgba(255,95,109,.15);color:var(--red);border-color:rgba(255,95,109,.4)}
.status-tab input:checked + label.l-holiday{background:rgba(245,166,35,.15);color:var(--amber);border-color:rgba(245,166,35,.4)}
.status-tab label:hover{color:var(--text);background:var(--border)}
.delete-zone{margin-top:16px;padding-top:16px;border-top:1px solid var(--border)}
"""

# ──────────────────────────────────────────────────────────────────────────────
# NAV helper
# ──────────────────────────────────────────────────────────────────────────────
def nav_html(active: str) -> str:
    links = [
        ("/",         "Today",    "today"),
        ("/calendar", "Calendar", "calendar"),
        ("/settings", "Settings", "settings"),
    ]
    items = "".join(
        f'<a href="{href}" class="{"active" if active == key else ""}">{label}</a>'
        for href, label, key in links
    )
    return f"""
<nav>
  <span class="brand">&#9201; AttendTrack</span>
  <div class="nav-links">{items}</div>
</nav>"""


# ──────────────────────────────────────────────────────────────────────────────
# Edit / Delete modal  (reused on both Home and Calendar)
# ──────────────────────────────────────────────────────────────────────────────
EDIT_MODAL = """
<!-- Edit Modal -->
<div class="modal-overlay" id="editOverlay">
  <div class="modal">
    <button class="modal-close" onclick="closeModal()">&#10005;</button>
    <div class="modal-title" id="modalTitle">Edit Entry</div>
    <div class="modal-sub" id="modalSub">Adjust in / out times or status</div>

    <form method="post" action="/entry/edit" id="editForm">
      <input type="hidden" name="date"     id="ef_date">
      <input type="hidden" name="redirect" id="ef_redirect" value="/">

      <!-- Status radio tabs -->
      <div class="status-tabs">
        <div class="status-tab">
          <input type="radio" name="status" id="st_present" value="present">
          <label for="st_present" class="l-present">&#10003; Present</label>
        </div>
        <div class="status-tab">
          <input type="radio" name="status" id="st_absent"  value="absent">
          <label for="st_absent"  class="l-absent">&#10007; Absent</label>
        </div>
        <div class="status-tab">
          <input type="radio" name="status" id="st_holiday" value="holiday">
          <label for="st_holiday" class="l-holiday">&#127958; Holiday</label>
        </div>
      </div>

      <!-- Clock pickers -->
      <div id="timePickers">
        <div class="clock-wrap">
          <!-- SVG clock face -->
          <div class="clock-face">
            <svg id="clockSvg" width="110" height="110" viewBox="0 0 110 110">
              <circle cx="55" cy="55" r="52" fill="#1a1e2a" stroke="#252a38" stroke-width="2"/>
              <!-- tick marks -->
              <g id="ticks"></g>
              <!-- hour hand -->
              <line id="hHand" x1="55" y1="55" x2="55" y2="28"
                    stroke="#6c63ff" stroke-width="4" stroke-linecap="round"/>
              <!-- minute hand -->
              <line id="mHand" x1="55" y1="55" x2="55" y2="20"
                    stroke="#22d3a5" stroke-width="2.5" stroke-linecap="round"/>
              <circle cx="55" cy="55" r="4" fill="#e8eaf0"/>
              <!-- labels -->
              <text x="55" y="16"  text-anchor="middle" fill="#6b7280" font-size="8" font-family="Inter">12</text>
              <text x="96" y="58"  text-anchor="middle" fill="#6b7280" font-size="8" font-family="Inter">3</text>
              <text x="55" y="100" text-anchor="middle" fill="#6b7280" font-size="8" font-family="Inter">6</text>
              <text x="14" y="58"  text-anchor="middle" fill="#6b7280" font-size="8" font-family="Inter">9</text>
            </svg>
          </div>
          <div class="clock-inputs">
            <div class="time-picker-row">
              <label>In</label>
              <input type="time" name="time_in"  id="ef_in"  class="tp-input"
                     oninput="updateClock()">
            </div>
            <div class="time-picker-row">
              <label>Out</label>
              <input type="time" name="time_out" id="ef_out" class="tp-input"
                     oninput="updateClock()">
            </div>
            <div id="durDisplay" style="font-size:.82rem;color:var(--accent);font-weight:600;margin-top:8px"></div>
          </div>
        </div>
      </div>

      <div class="field" id="noteField" style="display:none">
        <label>Note</label>
        <input type="text" name="note" id="ef_note" placeholder="e.g. Eid Holiday">
      </div>

      <div style="display:flex;gap:10px">
        <button type="submit" class="btn btn-accent" style="flex:1">Save Changes</button>
        <button type="button" class="btn btn-ghost" onclick="closeModal()" style="flex:0 0 auto">Cancel</button>
      </div>
    </form>

    <div class="delete-zone">
      <form method="post" action="/entry/delete" id="deleteForm">
        <input type="hidden" name="date"     id="df_date">
        <input type="hidden" name="redirect" id="df_redirect" value="/">
        <button type="button" class="btn btn-red" style="width:100%;padding:12px"
                onclick="confirmDelete()">
          &#128465; Delete this entry permanently
        </button>
      </form>
    </div>
  </div>
</div>

<script>
// ── Modal open / close ────────────────────────────────────────────────────────
function openEditModal(dateIso, dateLabel, statusVal, timeIn, timeOut, note, redirectTo) {
  document.getElementById('modalTitle').textContent = 'Edit Entry — ' + dateLabel;
  document.getElementById('modalSub').textContent   = dateIso;
  document.getElementById('ef_date').value      = dateIso;
  document.getElementById('df_date').value      = dateIso;
  document.getElementById('ef_redirect').value  = redirectTo || '/';
  document.getElementById('df_redirect').value  = redirectTo || '/';

  // status radio
  var radios = document.querySelectorAll('input[name="status"]');
  radios.forEach(function(r){ r.checked = (r.value === statusVal); });

  // times – convert ISO timestamp to HH:MM for <input type="time">
  document.getElementById('ef_in').value  = isoToHHMM(timeIn);
  document.getElementById('ef_out').value = isoToHHMM(timeOut);
  document.getElementById('ef_note').value = note || '';

  updateTimePickers(statusVal);
  updateClock();

  var ov = document.getElementById('editOverlay');
  ov.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  document.getElementById('editOverlay').classList.remove('open');
  document.body.style.overflow = '';
}

document.getElementById('editOverlay').addEventListener('click', function(e){
  if (e.target === this) closeModal();
});

document.addEventListener('keydown', function(e){
  if (e.key === 'Escape') closeModal();
});

// ── Status change shows/hides time pickers ────────────────────────────────────
document.querySelectorAll('input[name="status"]').forEach(function(r){
  r.addEventListener('change', function(){ updateTimePickers(this.value); });
});

function updateTimePickers(st) {
  var show = (st === 'present' || st === 'partial');
  document.getElementById('timePickers').style.display = show ? '' : 'none';
  document.getElementById('noteField').style.display   = (st === 'holiday') ? '' : 'none';
}

// ── Clock face animation ──────────────────────────────────────────────────────
function isoToHHMM(iso) {
  if (!iso) return '';
  // handles '09:05', '2025-01-01T09:05:00', '2025-01-01T09:05:00+05:00'
  var m = iso.match(/T?(\\d{2}):(\\d{2})/);
  return m ? m[1] + ':' + m[2] : '';
}

function updateClock() {
  var inVal  = document.getElementById('ef_in').value;
  var outVal = document.getElementById('ef_out').value;

  // Drive clock off the IN time (or current time if empty)
  var h = 0, m = 0;
  if (inVal) {
    var parts = inVal.split(':');
    h = parseInt(parts[0]) % 12;
    m = parseInt(parts[1]);
  } else {
    var now = new Date();
    h = now.getHours() % 12;
    m = now.getMinutes();
  }

  var hAngle = (h / 12) * 360 + (m / 60) * 30 - 90;
  var mAngle = (m / 60) * 360 - 90;

  var cx = 55, cy = 55, hl = 27, ml = 35;
  document.getElementById('hHand').setAttribute('x2', cx + hl * Math.cos(hAngle * Math.PI/180));
  document.getElementById('hHand').setAttribute('y2', cy + hl * Math.sin(hAngle * Math.PI/180));
  document.getElementById('mHand').setAttribute('x2', cx + ml * Math.cos(mAngle * Math.PI/180));
  document.getElementById('mHand').setAttribute('y2', cy + ml * Math.sin(mAngle * Math.PI/180));

  // Duration
  var dur = '';
  if (inVal && outVal) {
    var a = new Date('1970-01-01T' + inVal + ':00');
    var b = new Date('1970-01-01T' + outVal + ':00');
    var diff = Math.abs(b - a) / 60000;
    var dh = Math.floor(diff / 60);
    var dm = Math.round(diff % 60);
    dur = dh + 'h ' + String(dm).padStart(2,'0') + 'm';
  }
  var dd = document.getElementById('durDisplay');
  dd.textContent = dur ? ('Duration: ' + dur) : '';
}

function confirmDelete() {
  if (confirm('Permanently delete this attendance entry? This cannot be undone.')) {
    document.getElementById('deleteForm').submit();
  }
}

// Draw tick marks on SVG
(function(){
  var g = document.getElementById('ticks');
  for (var i = 0; i < 12; i++) {
    var angle = (i / 12) * 2 * Math.PI - Math.PI/2;
    var r1 = 46, r2 = 50, cx = 55, cy = 55;
    var line = document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1', cx + r1 * Math.cos(angle));
    line.setAttribute('y1', cy + r1 * Math.sin(angle));
    line.setAttribute('x2', cx + r2 * Math.cos(angle));
    line.setAttribute('y2', cy + r2 * Math.sin(angle));
    line.setAttribute('stroke', '#252a38');
    line.setAttribute('stroke-width', '2');
    g.appendChild(line);
  }
})();
</script>
"""


# ──────────────────────────────────────────────────────────────────────────────
# Home template
# ──────────────────────────────────────────────────────────────────────────────
HOME_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AttendTrack &ndash; Today</title>
  <style>
  {{ base_style }}
  .hero{text-align:center;padding:56px 0 36px}
  .hero-date{font-size:.95rem;color:var(--muted);letter-spacing:1px;text-transform:uppercase;margin-bottom:8px}
  .hero-time{font-size:3.8rem;font-weight:800;
             background:linear-gradient(135deg,#fff 30%,var(--accent));
             -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
             letter-spacing:-2px;line-height:1.1}
  .hero-wd{font-size:1.05rem;color:var(--muted);margin-top:6px}
  .stat-row{display:flex;gap:16px;margin-top:32px}
  .stat-box{flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:18px;text-align:center}
  .stat-val{font-size:1.8rem;font-weight:700;
            background:linear-gradient(135deg,var(--accent),var(--green));
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
  .stat-lbl{color:var(--muted);font-size:.8rem;margin-top:4px}
  .info-row{display:flex;align-items:center;justify-content:space-between;padding:14px 0;border-bottom:1px solid var(--border)}
  .info-row:last-child{border-bottom:none}
  .info-key{color:var(--muted);font-size:.9rem}
  .info-val{font-weight:600}
  .big-btn{width:100%;padding:22px;font-size:1.15rem;border-radius:14px}
  .tz-badge{display:inline-flex;align-items:center;gap:6px;background:var(--surface2);
            border:1px solid var(--border);border-radius:8px;padding:5px 12px;
            font-size:.78rem;color:var(--muted);text-decoration:none;margin-top:4px;transition:.2s}
  .tz-badge:hover{color:var(--text);border-color:var(--accent)}
  @media(max-width:600px){.stat-row{flex-wrap:wrap}.stat-box{min-width:calc(50% - 8px)}}
  </style>
</head>
<body>
{{ nav }}
<div class="container">

  {% if msg %}
  <div class="flash flash-{{ msg_type }}">{{ msg }}</div>
  {% endif %}

  <div class="hero">
    <div class="hero-date">{{ today_fmt }}</div>
    <div class="hero-time" id="ltime">{{ cur_time }}</div>
    <div class="hero-wd">{{ weekday }}</div>
    <div style="margin-top:10px">
      <a href="/settings" class="tz-badge">&#128336; {{ timezone }}</a>
    </div>
  </div>

  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
      <div>
        <h2 style="font-size:1.2rem;font-weight:700">Today&#39;s Attendance</h2>
        <p class="text-muted mt-1">{{ today_full }}</p>
      </div>
      <div style="display:flex;align-items:center;gap:10px">
        <span class="badge badge-{{ status_class }}">{{ status_label }}</span>
        {% if record %}
        <button class="btn btn-ghost btn-icon"
                onclick="openEditModal(
                  '{{ today }}',
                  '{{ today_full }}',
                  '{{ record.status or '' }}',
                  '{{ record.time_in or '' }}',
                  '{{ record.time_out or '' }}',
                  '{{ record.note or '' }}',
                  '/'
                )" title="Edit today">&#9998;</button>
        {% endif %}
      </div>
    </div>

    {% if record %}
      {% if record.status == 'holiday' %}
        <div class="info-row">
          <span class="info-key">&#127958; Holiday</span>
          <span class="info-val">{{ record.note or 'Holiday' }}</span>
        </div>
      {% else %}
        {% if record.time_in %}
        <div class="info-row">
          <span class="info-key">&#128994; Clocked In</span>
          <span class="info-val">{{ record.time_in | fmt_time }}</span>
        </div>
        {% endif %}
        {% if record.time_out %}
        <div class="info-row">
          <span class="info-key">&#128308; Clocked Out</span>
          <span class="info-val">{{ record.time_out | fmt_time }}</span>
        </div>
        <div class="info-row">
          <span class="info-key">&#9203; Duration</span>
          <span class="info-val">{{ record.time_in | hours_between(record.time_out) }}</span>
        </div>
        {% endif %}
      {% endif %}
    {% else %}
      <div class="info-row">
        <span class="info-key">Status</span>
        <span class="info-val text-muted">No action taken yet today</span>
      </div>
    {% endif %}

    <div style="margin-top:24px">
      {% if status == 'none' %}
        <form action="/mark" method="post">
          <input type="hidden" name="action" value="in">
          <button class="btn btn-green big-btn" type="submit">
            <span class="pdot pg"></span> Clock In &mdash; Mark Arrival
          </button>
        </form>
        <div style="margin-top:12px">
          <form action="/mark" method="post">
            <input type="hidden" name="action" value="holiday">
            <button class="btn btn-amber big-btn" type="submit">
              &#127958; Mark Today as Holiday
            </button>
          </form>
        </div>

      {% elif status == 'in' %}
        <form action="/mark" method="post">
          <input type="hidden" name="action" value="out">
          <button class="btn btn-red big-btn" type="submit">
            <span class="pdot pr"></span> Clock Out &mdash; Mark Departure
          </button>
        </form>
        <p class="text-muted mt-2" style="text-align:center;font-size:.85rem">
          Clocked in at {{ record.time_in | fmt_time }} &middot; timer running
        </p>

      {% elif status == 'done' %}
        <div style="text-align:center;padding:12px 0;color:var(--green);font-weight:600">
          &#10003; Attendance complete for today
        </div>
        <p class="text-muted" style="text-align:center;font-size:.85rem;margin-top:6px">
          {{ record.time_in | fmt_time }} &rarr; {{ record.time_out | fmt_time }}
          &nbsp;&middot;&nbsp;
          {{ record.time_in | hours_between(record.time_out) }}
        </p>

      {% elif status == 'holiday' %}
        <div style="text-align:center;padding:12px 0;color:var(--amber);font-weight:600">
          &#127958; Today is marked as a Holiday
        </div>
        <form action="/unmark_holiday" method="post" style="margin-top:12px">
          <button class="btn btn-ghost big-btn" type="submit">
            &#8617; Undo &ndash; Treat as Work Day
          </button>
        </form>
      {% endif %}
    </div>
  </div>

  <div class="stat-row">
    <div class="stat-box"><div class="stat-val">{{ stats.present }}</div><div class="stat-lbl">Days Present</div></div>
    <div class="stat-box"><div class="stat-val">{{ stats.absent }}</div><div class="stat-lbl">Days Absent</div></div>
    <div class="stat-box"><div class="stat-val">{{ stats.holidays }}</div><div class="stat-lbl">Holidays</div></div>
    <div class="stat-box"><div class="stat-val">{{ stats.total_hours }}</div><div class="stat-lbl">Total Hours</div></div>
  </div>

</div>

{{ edit_modal }}

<script>
function tick(){
  var e=document.getElementById('ltime');
  var n=new Date();
  e.textContent=String(n.getHours()).padStart(2,'0')+':'+String(n.getMinutes()).padStart(2,'0')+':'+String(n.getSeconds()).padStart(2,'0');
}
tick(); setInterval(tick,1000);
</script>
</body>
</html>
"""

# ──────────────────────────────────────────────────────────────────────────────
# Calendar template
# ──────────────────────────────────────────────────────────────────────────────
CALENDAR_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AttendTrack &ndash; Calendar</title>
  <style>
  {{ base_style }}
  .page-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:32px}
  .page-title{font-size:1.6rem;font-weight:800;
              background:linear-gradient(135deg,#fff,var(--accent));
              -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
  .m-nav{display:flex;align-items:center;gap:12px}
  .m-lbl{font-weight:700;font-size:1.05rem;min-width:160px;text-align:center}
  .cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:6px}
  .cal-dh{text-align:center;font-size:.75rem;font-weight:700;color:var(--muted);
          text-transform:uppercase;padding:8px 0;letter-spacing:.8px}
  .cal-day{background:var(--surface);border:1px solid var(--border);border-radius:10px;
           padding:10px 8px 8px;min-height:90px;position:relative;
           transition:border-color .2s,box-shadow .2s;cursor:pointer}
  .cal-day:hover{border-color:var(--accent);box-shadow:0 0 0 1px var(--ag)}
  .cal-day.empty{background:transparent;border-color:transparent;cursor:default}
  .cal-day.empty:hover{border-color:transparent;box-shadow:none}
  .cal-day.today-c{border-color:var(--accent);box-shadow:0 0 0 1px var(--ag),inset 0 0 20px rgba(108,99,255,.06)}
  .cal-day.future-c{opacity:.45;cursor:default}
  .cal-day.future-c:hover{border-color:var(--border);box-shadow:none}
  .dn{font-size:.85rem;font-weight:700;color:var(--muted);margin-bottom:6px}
  .today-c .dn{color:var(--accent)}
  .dstrip{position:absolute;top:0;left:0;right:0;height:3px;border-radius:10px 10px 0 0}
  .s-present{background:var(--green)}.s-absent{background:var(--red)}
  .s-holiday{background:var(--amber)}.s-partial{background:var(--accent)}
  .dt{font-size:.7rem;color:var(--muted);line-height:1.5;margin-top:2px}
  .dt .tin{color:var(--green);font-weight:600}
  .dt .tout{color:var(--red);font-weight:600}
  .dt .tdur{color:var(--accent);font-weight:600}
  .dt .thol{color:var(--amber);font-weight:600}
  .dt .tabs{color:var(--red)}
  .edit-hint{position:absolute;bottom:5px;right:7px;font-size:.65rem;color:var(--border);
             transition:.2s;user-select:none}
  .cal-day:hover .edit-hint{color:var(--muted)}
  .legend{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:24px}
  .leg-i{display:flex;align-items:center;gap:7px;font-size:.82rem;color:var(--muted)}
  .leg-d{width:10px;height:10px;border-radius:3px}
  .stbl{width:100%;border-collapse:collapse;margin-top:10px;font-size:.88rem}
  .stbl th{color:var(--muted);font-weight:600;padding:10px 12px;
           border-bottom:1px solid var(--border);text-align:left;
           font-size:.78rem;text-transform:uppercase;letter-spacing:.6px}
  .stbl td{padding:12px;border-bottom:1px solid var(--border);vertical-align:middle}
  .stbl tr:last-child td{border-bottom:none}
  .stbl tr:hover td{background:rgba(255,255,255,.02)}
  .stbl .act-btn{display:inline-flex;gap:6px}
  @media(max-width:600px){
    .cal-day{min-height:60px;padding:6px 4px 4px}.dt{display:none}
    .page-hdr{flex-direction:column;gap:16px;align-items:flex-start}
    .edit-hint{display:none}
  }
  </style>
</head>
<body>
{{ nav }}
<div class="container">

  <div class="page-hdr">
    <h1 class="page-title">Attendance Calendar</h1>
    <div class="m-nav">
      <a href="/calendar?y={{ prev_y }}&amp;m={{ prev_m }}" class="btn btn-ghost" style="padding:8px 14px">&#8249;</a>
      <span class="m-lbl">{{ month_label }}</span>
      <a href="/calendar?y={{ next_y }}&amp;m={{ next_m }}" class="btn btn-ghost" style="padding:8px 14px">&#8250;</a>
    </div>
  </div>

  <div class="legend">
    <div class="leg-i"><div class="leg-d" style="background:var(--green)"></div> Present</div>
    <div class="leg-i"><div class="leg-d" style="background:var(--red)"></div> Absent</div>
    <div class="leg-i"><div class="leg-d" style="background:var(--amber)"></div> Holiday</div>
    <div class="leg-i"><div class="leg-d" style="background:var(--accent)"></div> Partial</div>
    <div class="leg-i" style="margin-left:auto;font-size:.75rem;color:var(--border)">
      &#9998; click any day to edit
    </div>
  </div>

  <div class="card" style="padding:20px">
    <div class="cal-grid">
      {% for dh in ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'] %}
      <div class="cal-dh">{{ dh }}</div>
      {% endfor %}

      {% for _ in range(start_weekday) %}
      <div class="cal-day empty"></div>
      {% endfor %}

      {% for day in days %}
      {% set rec = recs.get(day.iso, {}) %}
      {% set is_today  = (day.iso == today_str) %}
      {% set is_future = (day.iso > today_str) %}
      <div class="cal-day
          {% if is_today %}today-c{% endif %}
          {% if is_future %}future-c{% endif %}"
        {% if not is_future %}
        onclick="openEditModal(
          '{{ day.iso }}',
          '{{ day.label }}',
          '{{ rec.get('status','') }}',
          '{{ rec.get('time_in','') }}',
          '{{ rec.get('time_out','') }}',
          '{{ rec.get('note','') }}',
          '/calendar?y={{ y }}&m={{ m }}'
        )"
        {% endif %}
      >
        {% if rec.get('time_in') and rec.get('time_out') %}
          <div class="dstrip s-present"></div>
          <div class="dn">{{ day.d }}</div>
          <div class="dt">
            <div class="tin">&#9650; {{ rec['time_in'] | fmt_time }}</div>
            <div class="tout">&#9660; {{ rec['time_out'] | fmt_time }}</div>
            <div class="tdur">{{ rec['time_in'] | hours_between(rec['time_out']) }}</div>
          </div>
        {% elif rec.get('time_in') and not rec.get('time_out') %}
          <div class="dstrip s-partial"></div>
          <div class="dn">{{ day.d }}</div>
          <div class="dt">
            <div class="tin">&#9650; {{ rec['time_in'] | fmt_time }}</div>
            <div style="color:var(--muted)">out pending&hellip;</div>
          </div>
        {% elif rec.get('status') == 'holiday' %}
          <div class="dstrip s-holiday"></div>
          <div class="dn">{{ day.d }}</div>
          <div class="dt"><div class="thol">&#127958; Holiday</div></div>
        {% elif rec.get('status') == 'absent' %}
          <div class="dstrip s-absent"></div>
          <div class="dn">{{ day.d }}</div>
          <div class="dt"><div class="tabs">Absent</div></div>
        {% else %}
          <div class="dn">{{ day.d }}</div>
          {% if is_today %}<div class="dt" style="color:var(--accent);font-size:.68rem">today</div>{% endif %}
        {% endif %}
        {% if not is_future %}<span class="edit-hint">&#9998;</span>{% endif %}
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- Monthly detail table -->
  <div class="card mt-4">
    <h2 style="font-size:1.1rem;font-weight:700;margin-bottom:16px">
      &#128203; Monthly Detail &mdash; {{ month_label }}
    </h2>
    {% if month_records %}
    <table class="stbl">
      <thead>
        <tr>
          <th>Date</th><th>Day</th><th>Status</th><th>In</th><th>Out</th><th>Duration</th><th></th>
        </tr>
      </thead>
      <tbody>
        {% for row in month_records %}
        <tr>
          <td>{{ row.date }}</td>
          <td style="color:var(--muted)">{{ row.weekday }}</td>
          <td><span class="badge badge-{{ row.status_class }}">{{ row.status_label }}</span></td>
          <td>{{ row.time_in or '&mdash;' }}</td>
          <td>{{ row.time_out or '&mdash;' }}</td>
          <td>{{ row.duration or '&mdash;' }}</td>
          <td>
            {% if not row.future %}
            <button class="btn btn-ghost btn-icon"
                    onclick="openEditModal(
                      '{{ row.iso }}',
                      '{{ row.date }}',
                      '{{ row.status_raw }}',
                      '{{ row.raw_in }}',
                      '{{ row.raw_out }}',
                      '{{ row.note }}',
                      '/calendar?y={{ y }}&m={{ m }}'
                    )" title="Edit">&#9998;</button>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="text-muted" style="text-align:center;padding:20px 0">No records for this month yet.</p>
    {% endif %}
  </div>

</div>

{{ edit_modal }}

</body>
</html>
"""

# ──────────────────────────────────────────────────────────────────────────────
# Settings template
# ──────────────────────────────────────────────────────────────────────────────
SETTINGS_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AttendTrack &ndash; Settings</title>
  <style>
  {{ base_style }}
  .page-title{font-size:1.6rem;font-weight:800;margin-bottom:8px;
              background:linear-gradient(135deg,#fff,var(--accent));
              -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
  .settings-grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:24px}
  @media(max-width:640px){.settings-grid{grid-template-columns:1fr}}
  .section-title{font-size:.8rem;font-weight:700;color:var(--muted);
                 letter-spacing:.8px;text-transform:uppercase;margin-bottom:16px}
  .info-pill{display:inline-flex;align-items:center;gap:8px;background:var(--surface2);
             border:1px solid var(--border);border-radius:10px;padding:10px 16px;
             font-size:.9rem;color:var(--muted);margin-bottom:12px}
  .info-pill strong{color:var(--text)}
  </style>
</head>
<body>
{{ nav }}
<div class="container">

  {% if msg %}
  <div class="flash flash-{{ msg_type }}">{{ msg }}</div>
  {% endif %}

  <h1 class="page-title">Settings</h1>
  <p class="text-muted">Configure how AttendTrack behaves.</p>

  <div class="settings-grid">

    <!-- Timezone card -->
    <div class="card">
      <div class="section-title">&#127758; Timezone</div>
      <div class="info-pill">
        Current: <strong>{{ current_tz }}</strong>
      </div>
      <form method="post" action="/settings/save">
        <input type="hidden" name="key" value="timezone">
        <div class="field">
          <label>Select Timezone</label>
          <select name="value" id="tzSelect">
            {% for tz in timezones %}
            <option value="{{ tz }}" {% if tz == current_tz %}selected{% endif %}>{{ tz }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="field">
          <label>Or type a custom IANA timezone</label>
          <input type="text" name="custom_tz" id="customTz"
                 placeholder="e.g. America/New_York"
                 style="font-size:.9rem">
          <small style="color:var(--muted);font-size:.78rem;margin-top:4px">
            Leave blank to use the selection above.
          </small>
        </div>
        <button type="submit" class="btn btn-accent" style="width:100%">
          &#128190; Save Timezone
        </button>
      </form>
    </div>

    <!-- DB Info card -->
    <div class="card">
      <div class="section-title">&#128196; Database Info</div>
      <div class="info-pill">Total records: <strong>{{ db_count }}</strong></div><br>
      <div class="info-pill">DB file: <strong>attendance.db</strong></div>
      <p class="text-muted mt-2" style="font-size:.83rem;line-height:1.7">
        All attendance data is stored in SQLite3.<br>
        The file lives next to <code style="background:var(--surface2);padding:2px 6px;border-radius:4px">app.py</code>.<br>
        Back it up by simply copying <code style="background:var(--surface2);padding:2px 6px;border-radius:4px">attendance.db</code>.
      </p>
      <div class="mt-3">
        <div class="section-title" style="margin-top:16px">&#9888; Danger Zone</div>
        <form method="post" action="/settings/reset"
              onsubmit="return confirm('Delete ALL attendance records permanently? This cannot be undone.')">
          <button type="submit" class="btn btn-red" style="width:100%;padding:14px">
            &#128465; Wipe All Attendance Data
          </button>
        </form>
      </div>
    </div>

  </div>
</div>
</body>
</html>
"""


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    mark_past_absent()

    today  = today_str()
    record = get_record(today)
    now    = now_local()

    if not record:
        status = "none"
    elif record["status"] == "holiday":
        status = "holiday"
    elif record["time_in"] and record["time_out"]:
        status = "done"
    elif record["time_in"]:
        status = "in"
    else:
        status = "none"

    status_map = {
        "none":    ("no-record", "No Record"),
        "in":      ("partial",   "Clocked In"),
        "done":    ("present",   "Present"),
        "holiday": ("holiday",   "Holiday"),
    }
    status_class, status_label = status_map[status]
    stats    = compute_stats()
    msg      = request.args.get("msg", "")
    msg_type = request.args.get("type", "info")

    return render_template_string(
        HOME_TEMPLATE,
        base_style=Markup(BASE_STYLE),
        nav=Markup(nav_html("today")),
        edit_modal=Markup(EDIT_MODAL),
        today_fmt=now.strftime("%B %d, %Y"),
        today_full=now.strftime("%A, %B %d %Y"),
        weekday=now.strftime("%A"),
        cur_time=now.strftime("%H:%M:%S"),
        timezone=get_setting("timezone", "UTC"),
        today=today,
        record=record,
        status=status,
        status_class=status_class,
        status_label=status_label,
        stats=stats,
        msg=msg,
        msg_type=msg_type,
    )


@app.route("/mark", methods=["POST"])
def mark():
    action = request.form.get("action")
    today  = today_str()
    now    = now_local()
    record = get_record(today)

    mark_past_absent()

    if action == "in":
        if record and record["time_in"]:
            return redirect(url_for("index", msg="Already clocked in today!", type="warning"))
        if record and record["status"] == "holiday":
            return redirect(url_for("index", msg="Today is marked as a holiday.", type="warning"))
        ts = now.isoformat(timespec="seconds")
        upsert_record(today, "partial", time_in=ts)
        return redirect(url_for("index",
            msg=f"Clocked in at {now.strftime('%I:%M %p')}", type="success"))

    elif action == "out":
        if not record or not record["time_in"]:
            return redirect(url_for("index", msg="You haven't clocked in yet.", type="warning"))
        if record["time_out"]:
            return redirect(url_for("index", msg="Already clocked out today!", type="warning"))
        ts  = now.isoformat(timespec="seconds")
        dur = hours_between(record["time_in"], ts)
        upsert_record(today, "present", time_in=record["time_in"], time_out=ts)
        return redirect(url_for("index",
            msg=f"Clocked out at {now.strftime('%I:%M %p')} \u00b7 {dur}", type="success"))

    elif action == "holiday":
        if record and record["time_in"]:
            return redirect(url_for("index",
                msg="Already clocked in — cannot mark as holiday.", type="warning"))
        upsert_record(today, "holiday", note="Holiday")
        return redirect(url_for("index", msg="Today marked as Holiday", type="success"))

    return redirect(url_for("index"))


@app.route("/unmark_holiday", methods=["POST"])
def unmark_holiday():
    today = today_str()
    r = get_record(today)
    if r and r["status"] == "holiday":
        delete_record(today)
    return redirect(url_for("index",
        msg="Holiday removed — day is now a work day.", type="info"))


@app.route("/entry/edit", methods=["POST"])
def entry_edit():
    day      = request.form.get("date", "").strip()
    status   = request.form.get("status", "absent")
    time_in  = request.form.get("time_in", "").strip()   # HH:MM from <input type="time">
    time_out = request.form.get("time_out", "").strip()
    note     = request.form.get("note", "").strip()
    redir    = request.form.get("redirect", "/")

    if not day:
        return redirect(redir)

    def hhmm_to_iso(day_str: str, hhmm: str) -> str | None:
        """Convert 'HH:MM' + date string to a full ISO timestamp with tz offset."""
        if not hhmm:
            return None
        try:
            tz  = get_tz()
            dt  = datetime.strptime(f"{day_str} {hhmm}", "%Y-%m-%d %H:%M")
            dt  = dt.replace(tzinfo=tz)
            return dt.isoformat(timespec="seconds")
        except Exception:
            return None

    ti_iso  = hhmm_to_iso(day, time_in)  if time_in  else None
    to_iso  = hhmm_to_iso(day, time_out) if time_out else None

    if status == "holiday":
        upsert_record(day, "holiday", note=note or "Holiday")
    elif status == "absent":
        upsert_record(day, "absent")
    else:
        # present or partial
        actual_status = "present" if (ti_iso and to_iso) else ("partial" if ti_iso else "absent")
        upsert_record(day, actual_status, time_in=ti_iso, time_out=to_iso)

    return redirect(redir + ("&" if "?" in redir else "?") + "msg=Entry+updated&type=success")


@app.route("/entry/delete", methods=["POST"])
def entry_delete():
    day   = request.form.get("date", "").strip()
    redir = request.form.get("redirect", "/")
    if day:
        delete_record(day)
    return redirect(redir + ("&" if "?" in redir else "?") + "msg=Entry+deleted&type=info")


@app.route("/calendar")
def calendar_view():
    mark_past_absent()

    today_date = now_local().date()
    today_iso  = today_date.isoformat()

    try:
        y = int(request.args.get("y", today_date.year))
        m = int(request.args.get("m", today_date.month))
    except ValueError:
        y, m = today_date.year, today_date.month

    y = max(2020, min(y, 2099))
    m = max(1,    min(m, 12))

    first_day        = date(y, m, 1)
    _, days_in_month = cal_mod.monthrange(y, m)
    start_wd         = (first_day.weekday() + 1) % 7   # Sun=0

    days = []
    for d in range(1, days_in_month + 1):
        dt = date(y, m, d)
        days.append({
            "d":     d,
            "iso":   dt.isoformat(),
            "label": dt.strftime("%A, %d %b %Y"),
        })

    prev_y, prev_m = (y - 1, 12) if m == 1  else (y, m - 1)
    next_y, next_m = (y + 1, 1)  if m == 12 else (y, m + 1)
    month_label    = first_day.strftime("%B %Y")

    # Fetch all records for this month at once
    rows = get_db().execute(
        "SELECT * FROM attendance WHERE date LIKE ?",
        (f"{y:04d}-{m:02d}-%",)
    ).fetchall()
    recs = {r["date"]: dict(r) for r in rows}

    # Monthly detail table
    month_records = []
    for d in range(1, days_in_month + 1):
        dt  = date(y, m, d)
        key = dt.isoformat()
        rec = recs.get(key, {})
        is_future = key > today_iso

        if not rec and not is_future:
            continue  # no data and past – skip (absent backfill handles it via mark_past_absent)
        if not rec and is_future:
            # show future blank days in table? skip.
            continue

        st = rec.get("status", "")
        if st == "holiday":
            sc, sl = "holiday", "Holiday"
            ti = to_ = dur = None
        elif st == "absent":
            sc, sl = "absent", "Absent"
            ti = to_ = dur = None
        elif rec.get("time_in") and rec.get("time_out"):
            sc, sl = "present", "Present"
            ti  = fmt_time(rec["time_in"])
            to_ = fmt_time(rec["time_out"])
            dur = hours_between(rec["time_in"], rec["time_out"])
        elif rec.get("time_in"):
            sc, sl = "partial", "Partial"
            ti  = fmt_time(rec["time_in"])
            to_ = None; dur = None
        else:
            continue

        month_records.append({
            "iso":         key,
            "date":        dt.strftime("%d %b %Y"),
            "weekday":     dt.strftime("%a"),
            "status_class":sc,
            "status_label":sl,
            "status_raw":  st,
            "time_in":     ti,
            "time_out":    to_,
            "raw_in":      rec.get("time_in",""),
            "raw_out":     rec.get("time_out",""),
            "note":        rec.get("note",""),
            "duration":    dur,
            "future":      is_future,
        })

    msg      = request.args.get("msg", "")
    msg_type = request.args.get("type", "info")

    return render_template_string(
        CALENDAR_TEMPLATE,
        base_style=Markup(BASE_STYLE),
        nav=Markup(nav_html("calendar")),
        edit_modal=Markup(EDIT_MODAL),
        recs=recs,
        days=days,
        today_str=today_iso,
        y=y, m=m,
        start_weekday=start_wd,
        month_label=month_label,
        prev_y=prev_y, prev_m=prev_m,
        next_y=next_y, next_m=next_m,
        month_records=month_records,
        msg=msg,
        msg_type=msg_type,
    )


@app.route("/settings", methods=["GET"])
def settings():
    msg      = request.args.get("msg", "")
    msg_type = request.args.get("type", "info")
    db_count = get_db().execute("SELECT COUNT(*) AS c FROM attendance").fetchone()["c"]

    return render_template_string(
        SETTINGS_TEMPLATE,
        base_style=Markup(BASE_STYLE),
        nav=Markup(nav_html("settings")),
        current_tz=get_setting("timezone", "UTC"),
        timezones=COMMON_TIMEZONES,
        db_count=db_count,
        msg=msg,
        msg_type=msg_type,
    )


@app.route("/settings/save", methods=["POST"])
def settings_save():
    key       = request.form.get("key", "").strip()
    value     = request.form.get("value", "").strip()
    custom_tz = request.form.get("custom_tz", "").strip()

    if key == "timezone":
        tz_to_save = custom_tz if custom_tz else value
        # Validate
        try:
            ZoneInfo(tz_to_save)
        except ZoneInfoNotFoundError:
            return redirect(url_for("settings",
                msg=f"Invalid timezone: {tz_to_save}", type="warning"))
        set_setting("timezone", tz_to_save)
        return redirect(url_for("settings",
            msg=f"Timezone updated to {tz_to_save}", type="success"))

    return redirect(url_for("settings", msg="Unknown setting.", type="warning"))


@app.route("/settings/reset", methods=["POST"])
def settings_reset():
    get_db().execute("DELETE FROM attendance")
    get_db().commit()
    return redirect(url_for("settings",
        msg="All attendance data wiped.", type="info"))


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
