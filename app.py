"""
Personal Attendance Tracker - Single File Flask App
----------------------------------------------------
Routes:
  /          -> Attendance action page (mark in/out, mark holiday)
  /calendar  -> Calendar view of all attendance records

Data is stored in attendance.json next to this file.
Timezone is set via TIMEZONE constant below.
"""

import json
import os
import calendar as cal_mod
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, redirect, render_template_string, request, url_for

# ---------------------------------------------------------------------------
# Config – edit TIMEZONE to match your local zone if needed
# ---------------------------------------------------------------------------
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "attendance.json")
TIMEZONE  = "Asia/Karachi"   # UTC+5

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def now_local() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


def today_str() -> str:
    return now_local().date().isoformat()


def fmt_time(iso: str) -> str:
    """ISO timestamp -> '09:05 AM'"""
    return datetime.fromisoformat(iso).strftime("%I:%M %p")


def hours_between(t_in: str, t_out: str) -> str:
    a = datetime.fromisoformat(t_in)
    b = datetime.fromisoformat(t_out)
    mins = int((b - a).total_seconds() // 60)
    h, m = divmod(mins, 60)
    return f"{h}h {m:02d}m"


def mark_past_absent(data: dict) -> None:
    """Backfill every un-recorded past work day with 'absent'."""
    if not data:
        return
    today     = now_local().date()
    yesterday = today - timedelta(days=1)
    first     = date.fromisoformat(min(data.keys()))
    cursor    = first
    while cursor <= yesterday:
        key = cursor.isoformat()
        if key not in data:
            data[key] = {"status": "absent"}
        cursor += timedelta(days=1)


def compute_stats(data: dict) -> dict:
    present = absent = holidays = 0
    total_mins = 0
    for rec in data.values():
        st = rec.get("status", "")
        if st == "holiday":
            holidays += 1
        elif st == "absent":
            absent += 1
        elif rec.get("in") and rec.get("out"):
            present += 1
            a = datetime.fromisoformat(rec["in"])
            b = datetime.fromisoformat(rec["out"])
            total_mins += int((b - a).total_seconds() // 60)
    h, m = divmod(total_mins, 60)
    return {
        "present":     present,
        "absent":      absent,
        "holidays":    holidays,
        "total_hours": f"{h}h {m:02d}m",
    }


# ---------------------------------------------------------------------------
# Jinja2 custom filters
# ---------------------------------------------------------------------------
@app.template_filter("fmt_time")
def jinja_fmt_time(iso: str) -> str:
    return fmt_time(iso)


@app.template_filter("hours_between")
def jinja_hours_between(t_in: str, t_out: str) -> str:
    return hours_between(t_in, t_out)


# ---------------------------------------------------------------------------
# Shared CSS
# ---------------------------------------------------------------------------
BASE_STYLE = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg:        #0d0f14;
  --surface:   #13161e;
  --surface2:  #1a1e2a;
  --border:    #252a38;
  --accent:    #6c63ff;
  --ag:        rgba(108,99,255,.35);
  --green:     #22d3a5;
  --gg:        rgba(34,211,165,.25);
  --red:       #ff5f6d;
  --rg:        rgba(255,95,109,.25);
  --amber:     #f5a623;
  --amg:       rgba(245,166,35,.25);
  --text:      #e8eaf0;
  --muted:     #6b7280;
  --r:         16px;
}
body { font-family:'Inter',sans-serif; background:var(--bg); color:var(--text); min-height:100vh; line-height:1.6; }
/* nav */
nav { display:flex; align-items:center; justify-content:space-between; padding:18px 32px;
      background:var(--surface); border-bottom:1px solid var(--border);
      position:sticky; top:0; z-index:100; backdrop-filter:blur(12px); }
.brand { font-size:1.2rem; font-weight:800;
         background:linear-gradient(135deg,var(--accent),var(--green));
         -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }
.nav-links a { color:var(--muted); text-decoration:none; font-size:.9rem; font-weight:500;
               padding:8px 18px; border-radius:10px; transition:all .2s; margin-left:6px; }
.nav-links a:hover, .nav-links a.active { color:var(--text); background:var(--surface2); }
.nav-links a.active { border:1px solid var(--border); }
/* layout */
.container { max-width:960px; margin:0 auto; padding:40px 24px; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:var(--r); padding:28px; }
/* buttons */
.btn { display:inline-flex; align-items:center; justify-content:center; gap:8px;
       padding:14px 32px; border:none; border-radius:12px; font-family:inherit;
       font-size:1rem; font-weight:600; cursor:pointer;
       transition:all .25s cubic-bezier(.34,1.56,.64,1); text-decoration:none; }
.btn-green  { background:linear-gradient(135deg,var(--green),#10b981); color:#000; box-shadow:0 4px 24px var(--gg); }
.btn-green:hover  { transform:translateY(-2px) scale(1.02); box-shadow:0 8px 32px var(--gg); }
.btn-red    { background:linear-gradient(135deg,var(--red),#f43f5e); color:#fff; box-shadow:0 4px 24px var(--rg); }
.btn-red:hover    { transform:translateY(-2px) scale(1.02); box-shadow:0 8px 32px var(--rg); }
.btn-amber  { background:linear-gradient(135deg,var(--amber),#f59e0b); color:#000; box-shadow:0 4px 24px var(--amg); }
.btn-amber:hover  { transform:translateY(-2px) scale(1.02); box-shadow:0 8px 32px var(--amg); }
.btn-ghost  { background:var(--surface2); color:var(--muted); border:1px solid var(--border); }
.btn-ghost:hover  { color:var(--text); background:var(--border); }
.btn:active { transform:scale(.97); }
/* badges */
.badge { display:inline-block; padding:4px 12px; border-radius:99px;
         font-size:.75rem; font-weight:600; letter-spacing:.5px; text-transform:uppercase; }
.badge-present { background:rgba(34,211,165,.15); color:var(--green); border:1px solid rgba(34,211,165,.3); }
.badge-absent  { background:rgba(255,95,109,.15);  color:var(--red);   border:1px solid rgba(255,95,109,.3); }
.badge-holiday { background:rgba(245,166,35,.15);  color:var(--amber); border:1px solid rgba(245,166,35,.3); }
.badge-partial { background:rgba(108,99,255,.15);  color:var(--accent);border:1px solid rgba(108,99,255,.3); }
/* misc */
.text-muted { color:var(--muted); font-size:.9rem; }
.mt-1{margin-top:8px} .mt-2{margin-top:16px} .mt-3{margin-top:24px} .mt-4{margin-top:32px}
/* pulse dot */
.pdot { width:10px; height:10px; border-radius:50%; display:inline-block; animation:pulse 1.6s infinite; }
.pg { background:var(--green); box-shadow:0 0 8px var(--green); }
.pr { background:var(--red);   box-shadow:0 0 8px var(--red); }
@keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.5;transform:scale(1.4)} }
/* flash */
.flash { padding:14px 20px; border-radius:12px; margin-bottom:20px;
         font-weight:500; border-left:4px solid; animation:slideIn .3s ease; }
.flash-success { background:rgba(34,211,165,.1); border-color:var(--green); color:var(--green); }
.flash-info    { background:rgba(108,99,255,.1); border-color:var(--accent); color:var(--accent); }
.flash-warning { background:rgba(245,166,35,.1); border-color:var(--amber); color:var(--amber); }
@keyframes slideIn { from{opacity:0;transform:translateY(-8px)} to{opacity:1;transform:none} }
"""

# ---------------------------------------------------------------------------
# Home template
# ---------------------------------------------------------------------------
HOME_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AttendTrack &ndash; Mark Today</title>
  <style>
  {{ base_style }}
  .hero { text-align:center; padding:60px 0 40px; }
  .hero-date { font-size:1rem; color:var(--muted); letter-spacing:1px; text-transform:uppercase; margin-bottom:8px; }
  .hero-time { font-size:3.8rem; font-weight:800;
               background:linear-gradient(135deg,#fff 30%,var(--accent));
               -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text;
               letter-spacing:-2px; line-height:1.1; }
  .hero-wd { font-size:1.1rem; color:var(--muted); margin-top:6px; }
  .stat-row { display:flex; gap:16px; margin-top:32px; }
  .stat-box { flex:1; background:var(--surface2); border:1px solid var(--border); border-radius:12px; padding:18px; text-align:center; }
  .stat-val { font-size:1.8rem; font-weight:700;
              background:linear-gradient(135deg,var(--accent),var(--green));
              -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }
  .stat-lbl { color:var(--muted); font-size:.8rem; margin-top:4px; }
  .info-row { display:flex; align-items:center; justify-content:space-between;
              padding:14px 0; border-bottom:1px solid var(--border); }
  .info-row:last-child { border-bottom:none; }
  .info-key { color:var(--muted); font-size:.9rem; }
  .info-val { font-weight:600; }
  .big-btn  { width:100%; padding:22px; font-size:1.15rem; border-radius:14px; }
  @media(max-width:600px){ .stat-row{flex-wrap:wrap} .stat-box{min-width:calc(50% - 8px)} }
  </style>
</head>
<body>
<nav>
  <span class="brand">&#9201; AttendTrack</span>
  <div class="nav-links">
    <a href="/" class="active">Today</a>
    <a href="/calendar">Calendar</a>
  </div>
</nav>
<div class="container">

  {% if msg %}
  <div class="flash flash-{{ msg_type }}">{{ msg }}</div>
  {% endif %}

  <div class="hero">
    <div class="hero-date">{{ today_fmt }}</div>
    <div class="hero-time" id="ltime">{{ cur_time }}</div>
    <div class="hero-wd">{{ weekday }}</div>
  </div>

  <div class="card">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px">
      <div>
        <h2 style="font-size:1.2rem;font-weight:700">Today&#39;s Attendance</h2>
        <p class="text-muted mt-1">{{ today_full }}</p>
      </div>
      <span class="badge badge-{{ status_class }}">{{ status_label }}</span>
    </div>

    {% if record %}
      {% if record.get('status') == 'holiday' %}
        <div class="info-row">
          <span class="info-key">&#127958; Holiday</span>
          <span class="info-val">{{ record.get('note', 'Holiday') }}</span>
        </div>
      {% else %}
        {% if record.get('in') %}
        <div class="info-row">
          <span class="info-key">&#128994; Clocked In</span>
          <span class="info-val">{{ record['in'] | fmt_time }}</span>
        </div>
        {% endif %}
        {% if record.get('out') %}
        <div class="info-row">
          <span class="info-key">&#128308; Clocked Out</span>
          <span class="info-val">{{ record['out'] | fmt_time }}</span>
        </div>
        <div class="info-row">
          <span class="info-key">&#9203; Duration</span>
          <span class="info-val">{{ record['in'] | hours_between(record['out']) }}</span>
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
          Clocked in at {{ record['in'] | fmt_time }} &middot; timer running
        </p>

      {% elif status == 'done' %}
        <div style="text-align:center;padding:12px 0;color:var(--green);font-weight:600">
          &#10003; Attendance complete for today
        </div>
        <p class="text-muted" style="text-align:center;font-size:.85rem;margin-top:6px">
          {{ record['in'] | fmt_time }} &rarr; {{ record['out'] | fmt_time }}
          &nbsp;&middot;&nbsp;
          {{ record['in'] | hours_between(record['out']) }}
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
    <div class="stat-box">
      <div class="stat-val">{{ stats.present }}</div>
      <div class="stat-lbl">Days Present</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{{ stats.absent }}</div>
      <div class="stat-lbl">Days Absent</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{{ stats.holidays }}</div>
      <div class="stat-lbl">Holidays</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{{ stats.total_hours }}</div>
      <div class="stat-lbl">Total Hours</div>
    </div>
  </div>

</div>
<script>
function tick() {
  var e = document.getElementById('ltime');
  var n = new Date();
  var h = String(n.getHours()).padStart(2,'0');
  var m = String(n.getMinutes()).padStart(2,'0');
  var s = String(n.getSeconds()).padStart(2,'0');
  e.textContent = h + ':' + m + ':' + s;
}
tick(); setInterval(tick, 1000);
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Calendar template
# ---------------------------------------------------------------------------
CALENDAR_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AttendTrack &ndash; Calendar</title>
  <style>
  {{ base_style }}
  .page-hdr { display:flex; align-items:center; justify-content:space-between; margin-bottom:32px; }
  .page-title { font-size:1.6rem; font-weight:800;
                background:linear-gradient(135deg,#fff,var(--accent));
                -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }
  .m-nav { display:flex; align-items:center; gap:12px; }
  .m-lbl { font-weight:700; font-size:1.05rem; min-width:160px; text-align:center; }
  .cal-grid { display:grid; grid-template-columns:repeat(7,1fr); gap:6px; }
  .cal-dh { text-align:center; font-size:.75rem; font-weight:700; color:var(--muted);
            text-transform:uppercase; padding:8px 0; letter-spacing:.8px; }
  .cal-day { background:var(--surface); border:1px solid var(--border); border-radius:10px;
             padding:10px 8px 8px; min-height:86px; position:relative;
             transition:border-color .2s, box-shadow .2s; }
  .cal-day:hover { border-color:var(--accent); box-shadow:0 0 0 1px var(--ag); }
  .cal-day.empty { background:transparent; border-color:transparent; }
  .cal-day.empty:hover { border-color:transparent; box-shadow:none; }
  .cal-day.today-c { border-color:var(--accent); box-shadow:0 0 0 1px var(--ag), inset 0 0 20px rgba(108,99,255,.06); }
  .dn { font-size:.85rem; font-weight:700; color:var(--muted); margin-bottom:6px; }
  .today-c .dn { color:var(--accent); }
  .dstrip { position:absolute; top:0; left:0; right:0; height:3px; border-radius:10px 10px 0 0; }
  .s-present { background:var(--green); }
  .s-absent  { background:var(--red); }
  .s-holiday { background:var(--amber); }
  .s-partial { background:var(--accent); }
  .dt { font-size:.7rem; color:var(--muted); line-height:1.5; margin-top:2px; }
  .dt .tin  { color:var(--green); font-weight:600; }
  .dt .tout { color:var(--red);   font-weight:600; }
  .dt .tdur { color:var(--accent);font-weight:600; }
  .dt .thol { color:var(--amber); font-weight:600; }
  .dt .tabs { color:var(--red); }
  .legend { display:flex; gap:20px; flex-wrap:wrap; margin-bottom:24px; }
  .leg-i { display:flex; align-items:center; gap:7px; font-size:.82rem; color:var(--muted); }
  .leg-d { width:10px; height:10px; border-radius:3px; }
  .stbl { width:100%; border-collapse:collapse; margin-top:10px; font-size:.88rem; }
  .stbl th { color:var(--muted); font-weight:600; padding:10px 12px;
             border-bottom:1px solid var(--border); text-align:left;
             font-size:.78rem; text-transform:uppercase; letter-spacing:.6px; }
  .stbl td { padding:12px; border-bottom:1px solid var(--border); vertical-align:middle; }
  .stbl tr:last-child td { border-bottom:none; }
  .stbl tr:hover td { background:rgba(255,255,255,.02); }
  @media(max-width:600px){
    .cal-day{min-height:60px;padding:6px 4px 4px} .dt{display:none}
    .page-hdr{flex-direction:column;gap:16px;align-items:flex-start}
  }
  </style>
</head>
<body>
<nav>
  <span class="brand">&#9201; AttendTrack</span>
  <div class="nav-links">
    <a href="/">Today</a>
    <a href="/calendar" class="active">Calendar</a>
  </div>
</nav>
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
      {% set key = day.iso %}
      {% set rec = data.get(key, {}) %}
      {% set is_today = (key == today_str) %}
      <div class="cal-day {% if is_today %}today-c{% endif %}">
        {% if rec.get('in') and rec.get('out') %}
          <div class="dstrip s-present"></div>
          <div class="dn">{{ day.d }}</div>
          <div class="dt">
            <div class="tin">&#9650; {{ rec['in'] | fmt_time }}</div>
            <div class="tout">&#9660; {{ rec['out'] | fmt_time }}</div>
            <div class="tdur">{{ rec['in'] | hours_between(rec['out']) }}</div>
          </div>
        {% elif rec.get('in') and not rec.get('out') %}
          <div class="dstrip s-partial"></div>
          <div class="dn">{{ day.d }}</div>
          <div class="dt">
            <div class="tin">&#9650; {{ rec['in'] | fmt_time }}</div>
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
          {% if is_today %}
          <div class="dt" style="color:var(--accent);font-size:.68rem">today</div>
          {% endif %}
        {% endif %}
      </div>
      {% endfor %}
    </div>
  </div>

  <div class="card mt-4">
    <h2 style="font-size:1.1rem;font-weight:700;margin-bottom:16px">
      &#128203; Monthly Detail &mdash; {{ month_label }}
    </h2>
    {% if month_records %}
    <table class="stbl">
      <thead>
        <tr>
          <th>Date</th><th>Day</th><th>Status</th><th>In</th><th>Out</th><th>Duration</th>
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
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <p class="text-muted" style="text-align:center;padding:20px 0">
      No records for this month yet.
    </p>
    {% endif %}
  </div>

</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    data = load_data()
    mark_past_absent(data)
    save_data(data)

    today  = today_str()
    record = data.get(today)
    now    = now_local()

    if not record:
        status = "none"
    elif record.get("status") == "holiday":
        status = "holiday"
    elif record.get("in") and record.get("out"):
        status = "done"
    elif record.get("in"):
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
    stats    = compute_stats(data)
    msg      = request.args.get("msg", "")
    msg_type = request.args.get("type", "info")

    return render_template_string(
        HOME_TEMPLATE,
        base_style=BASE_STYLE,
        today_fmt=now.strftime("%B %d, %Y"),
        today_full=now.strftime("%A, %B %d %Y"),
        weekday=now.strftime("%A"),
        cur_time=now.strftime("%H:%M:%S"),
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
    data   = load_data()
    mark_past_absent(data)

    today  = today_str()
    now    = now_local()
    record = data.get(today, {})

    if action == "in":
        if record.get("in"):
            return redirect(url_for("index", msg="Already clocked in today!", type="warning"))
        if record.get("status") == "holiday":
            return redirect(url_for("index", msg="Today is marked as a holiday.", type="warning"))
        record["in"] = now.isoformat(timespec="seconds")
        data[today]  = record
        save_data(data)
        return redirect(url_for("index", msg=f"Clocked in at {now.strftime('%I:%M %p')}", type="success"))

    elif action == "out":
        if not record.get("in"):
            return redirect(url_for("index", msg="You haven't clocked in yet.", type="warning"))
        if record.get("out"):
            return redirect(url_for("index", msg="Already clocked out today!", type="warning"))
        record["out"]    = now.isoformat(timespec="seconds")
        record["status"] = "present"
        data[today]      = record
        save_data(data)
        dur = hours_between(record["in"], record["out"])
        return redirect(url_for("index", msg=f"Clocked out at {now.strftime('%I:%M %p')} · {dur}", type="success"))

    elif action == "holiday":
        if record.get("in"):
            return redirect(url_for("index", msg="Already clocked in — cannot mark as holiday.", type="warning"))
        record["status"] = "holiday"
        record["note"]   = "Holiday"
        data[today]      = record
        save_data(data)
        return redirect(url_for("index", msg="Today marked as Holiday", type="success"))

    return redirect(url_for("index"))


@app.route("/unmark_holiday", methods=["POST"])
def unmark_holiday():
    data  = load_data()
    today = today_str()
    if data.get(today, {}).get("status") == "holiday":
        del data[today]
        save_data(data)
    return redirect(url_for("index", msg="Holiday removed — day is now a work day.", type="info"))


@app.route("/calendar")
def calendar_view():
    data  = load_data()
    mark_past_absent(data)
    save_data(data)

    today = now_local().date()
    try:
        y = int(request.args.get("y", today.year))
        m = int(request.args.get("m", today.month))
    except ValueError:
        y, m = today.year, today.month

    y = max(2020, min(y, 2099))
    m = max(1,    min(m, 12))

    first_day        = date(y, m, 1)
    _, days_in_month = cal_mod.monthrange(y, m)
    start_wd         = (first_day.weekday() + 1) % 7   # Sun=0

    days = [
        {"d": d, "iso": date(y, m, d).isoformat(), "weekday": date(y, m, d).strftime("%A")}
        for d in range(1, days_in_month + 1)
    ]

    prev_y, prev_m = (y - 1, 12) if m == 1  else (y, m - 1)
    next_y, next_m = (y + 1, 1)  if m == 12 else (y, m + 1)
    month_label    = first_day.strftime("%B %Y")

    month_records = []
    for d in range(1, days_in_month + 1):
        dt  = date(y, m, d)
        key = dt.isoformat()
        rec = data.get(key, {})
        if not rec:
            continue
        st = rec.get("status", "")
        if st == "holiday":
            sc, sl, ti, to_, dur = "holiday", "Holiday", None, None, None
        elif st == "absent":
            sc, sl, ti, to_, dur = "absent",  "Absent",  None, None, None
        elif rec.get("in") and rec.get("out"):
            sc, sl = "present", "Present"
            ti, to_, dur = fmt_time(rec["in"]), fmt_time(rec["out"]), hours_between(rec["in"], rec["out"])
        elif rec.get("in"):
            sc, sl = "partial", "Partial"
            ti, to_, dur = fmt_time(rec["in"]), None, None
        else:
            continue
        month_records.append({
            "date":         dt.strftime("%d %b %Y"),
            "weekday":      dt.strftime("%a"),
            "status_class": sc,
            "status_label": sl,
            "time_in":      ti,
            "time_out":     to_,
            "duration":     dur,
        })

    return render_template_string(
        CALENDAR_TEMPLATE,
        base_style=BASE_STYLE,
        data=data,
        days=days,
        today_str=today.isoformat(),
        start_weekday=start_wd,
        month_label=month_label,
        prev_y=prev_y, prev_m=prev_m,
        next_y=next_y, next_m=next_m,
        month_records=month_records,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)
