"""TikTok Affiliate Tracker - Streamlit app (simple, personalised, with calendar).

Run:  streamlit run app.py
Data is stored locally in tracker.db (SQLite). Works with your existing tracker.db.
Needs a recent Streamlit:  pip install -U streamlit
"""
import calendar
import html
import sqlite3
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
import streamlit as st

DB_PATH = "tracker.db"

STATUSES = ["Idea", "Ready to Shoot", "Shot", "Editing", "Ready to Post", "Posted"]
SHOT_DONE = ["Shot", "Editing", "Ready to Post", "Posted"]
SOURCES = ["Dini's Stock", "Brand/Sample", "Self-Purchased"]
BRAND_STATUSES = ["New Contact", "Negotiating", "Deal", "Sample Sent", "Content Made", "Done"]
PLAN_ACTIVITIES = ["Pick up & shoot", "Shoot", "Edit", "Post"]

CONTENT_COLS = {
    "title": "TEXT", "product": "TEXT", "source": "TEXT", "commission_pct": "REAL",
    "status": "TEXT", "shoot_date": "TEXT", "post_date": "TEXT", "hook": "TEXT",
    "video_link": "TEXT", "edit_minutes": "REAL", "views": "INTEGER",
    "cart_clicks": "INTEGER", "units_sold": "INTEGER", "commission_earned": "REAL",
    "notes": "TEXT", "location": "TEXT",
}
BRAND_COLS = {
    "name": "TEXT", "contact": "TEXT", "product": "TEXT", "status": "TEXT",
    "fee": "TEXT", "deadline": "TEXT", "notes": "TEXT",
}
PLAN_COLS = {
    "plan_date": "TEXT", "activity": "TEXT", "location": "TEXT", "start_time": "TEXT",
    "target": "INTEGER", "products": "TEXT", "notes": "TEXT",
}
DATE_COLS = {"content": ["shoot_date", "post_date"], "brands": ["deadline"], "plans": ["plan_date"]}
TABLE_COLS = {"content": CONTENT_COLS, "brands": BRAND_COLS, "plans": PLAN_COLS}

# Friday is a free day. The work happens on the weekend.
CHECKLIST = [
    "Saturday: pick up products at Dini's",
    "Saturday and Sunday: shoot the products",
    "Sunday night: 15-minute results review",
    "Research 5 new hooks",
]

ICON = {"plan": "📍", "shoot": "🎥", "post": "📤", "posted": "✅", "brand": "🤝"}
KIND_LABEL = {"plan": "Day plan", "shoot": "Shoot", "post": "Post (planned)",
              "posted": "Posted", "brand": "Brand deadline"}
KIND_ORDER = {"plan": 0, "shoot": 1, "post": 2, "posted": 3, "brand": 4}
PAGE_SIZE = 15

# ---------- database ----------


def conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with conn() as c:
        for table, cols in TABLE_COLS.items():
            defs = ", ".join(f"{k} {v}" for k, v in cols.items())
            c.execute(f"CREATE TABLE IF NOT EXISTS {table} "
                      f"(id INTEGER PRIMARY KEY AUTOINCREMENT, {defs})")
            existing = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            for k, v in cols.items():
                if k not in existing:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {k} {v}")
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")


def get_setting(key, default):
    with conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(key, value):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


def parse_date(x):
    if not x:
        return None
    try:
        return date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def rows(table):
    with conn() as c:
        c.row_factory = sqlite3.Row
        data = [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY id DESC")]
    for r in data:
        for col in DATE_COLS[table]:
            r[col] = parse_date(r.get(col))
        if table == "content" and r.get("source") == "Friend's Stock":
            r["source"] = "Dini's Stock"
    return data


def _iso(values):
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in values.items()}


def insert(table, values):
    values = _iso(values)
    keys = list(values)
    with conn() as c:
        c.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
                  [values[k] for k in keys])


def update(table, rid, values):
    values = _iso(values)
    sets = ", ".join(f"{k}=?" for k in values)
    with conn() as c:
        c.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*values.values(), rid])


def delete(table, rid):
    with conn() as c:
        c.execute(f"DELETE FROM {table} WHERE id=?", (rid,))


# ---------- helpers ----------


def n(x):
    try:
        if x is None or x != x or x == "":
            return 0
        return float(x)
    except (TypeError, ValueError):
        return 0


def rupiah(x):
    return "Rp" + f"{int(n(x)):,}".replace(",", ".")


def name_of(r):
    return r.get("title") or r.get("product") or r.get("name") or "Untitled"


def week_bounds(today=None):
    today = today or date.today()
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def next_status(current, options):
    if current in options and options.index(current) < len(options) - 1:
        return options[options.index(current) + 1]
    return None


def split_lines(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def location_options(videos, plans):
    seen = [x.strip() for x in get_setting("locations", "Dini's place, Home").split(",") if x.strip()]
    for r in [*plans, *videos]:
        loc = (r.get("location") or "").strip()
        if loc and loc not in seen:
            seen.append(loc)
    return seen


def loc_index(opts, value):
    return opts.index(value) if value in opts else None


def build_events(videos, brands, plans):
    ev = []
    for p in plans:
        if p["plan_date"]:
            label = p["activity"] or "Plan"
            if p["location"]:
                label += f" @ {p['location']}"
            ev.append({"date": p["plan_date"], "kind": "plan", "label": label})
    for v in videos:
        if v["shoot_date"]:
            ev.append({"date": v["shoot_date"], "kind": "shoot", "label": name_of(v)})
        if v["post_date"]:
            kind = "posted" if v["status"] == "Posted" else "post"
            ev.append({"date": v["post_date"], "kind": kind, "label": name_of(v)})
    for b in brands:
        if b["deadline"]:
            ev.append({"date": b["deadline"], "kind": "brand", "label": name_of(b)})
    return sorted(ev, key=lambda e: KIND_ORDER[e["kind"]])


def plan_progress(plan, videos):
    """Returns (done, label) for shoot/post plans, or None for others."""
    d = plan["plan_date"]
    if plan["activity"] in ("Pick up & shoot", "Shoot"):
        done = sum(1 for v in videos if v["shoot_date"] == d and v["status"] in SHOT_DONE)
        return done, "shot"
    if plan["activity"] == "Post":
        done = sum(1 for v in videos if v["post_date"] == d and v["status"] == "Posted")
        return done, "posted"
    return None


def show_plan_summary(p, videos):
    head = f"**{p['activity']}**" + (f" at **{p['location']}**" if p["location"] else "")
    if p["start_time"]:
        head += f", {p['start_time']}"
    st.markdown(head)
    prog = plan_progress(p, videos)
    target = int(n(p["target"])) or 1
    if prog:
        st.progress(min(prog[0] / target, 1.0), text=f"{prog[0]} of {target} {prog[1]}")
    else:
        st.caption(f"Target: {target} videos")
    items = split_lines(p["products"])
    if items:
        st.caption("Products: " + ", ".join(items))
    if p["notes"]:
        st.caption(p["notes"])


def month_grid_html(year, month, by_day):
    today = date.today()
    head = "".join(f"<div class='dow'>{d}</div>" for d in
                   ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    cells = []
    for d in calendar.Calendar(firstweekday=0).itermonthdates(year, month):
        cls = "day"
        if d.month != month:
            cls += " other"
        elif d.weekday() >= 5:
            cls += " wkend"
        if d == today:
            cls += " today"
        items = by_day.get(d, [])
        chips = "".join(
            f"<div class='chip {e['kind']}'><span class='t'>{ICON[e['kind']]} "
            f"{html.escape(e['label'])}</span></div>" for e in items[:3])
        more = f"<div class='more'>+{len(items) - 3} more</div>" if len(items) > 3 else ""
        cells.append(f"<div class='{cls}'><div class='num'>{d.day}</div>{chips}{more}</div>")
    return f"<div class='cal'>{head}{''.join(cells)}</div>"


CSS = """
<style>
.block-container {max-width: 1000px; padding-top: 1.5rem;}
h1 {font-size: 1.8rem !important;}
button[role="tab"] {font-size: 1rem;}
div[data-testid="stMetric"] {
  background: rgba(128,128,128,.12); border-radius: 10px; padding: .7rem .9rem;
}
.cal {display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px;}
.dow {text-align: center; font-size: .75rem; opacity: .6; padding: 2px 0;}
.day {min-height: 92px; border: 1px solid rgba(128,128,128,.3); border-radius: 8px;
      padding: 4px; overflow: hidden; min-width: 0;}
.day.wkend {background: rgba(13,148,136,.09);}
.day.other {opacity: .35;}
.day.today {border: 2px solid #3b82f6;}
.num {font-size: .78rem; font-weight: 600; margin-bottom: 2px;}
.chip {font-size: .68rem; color: #fff; border-radius: 4px; padding: 1px 4px; margin-top: 2px;
       white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
.chip.plan {background: #0d9488;}
.chip.shoot {background: #3b82f6;}
.chip.post {background: #d97706;}
.chip.posted {background: #059669;}
.chip.brand {background: #9333ea;}
.more {font-size: .65rem; opacity: .7; margin-top: 2px;}
.legend {font-size: .85rem; opacity: .85; margin: .5rem 0 1rem;}
.legend span {margin-right: 1rem; white-space: nowrap;}
@media (max-width: 640px) {
  .block-container {padding: 1rem .6rem 3rem;}
  h1 {font-size: 1.5rem !important;}
  .day {min-height: 46px; padding: 2px;}
  .chip {display: inline-block; width: 9px; height: 9px; padding: 0; border-radius: 50%;
         margin: 1px;}
  .chip .t, .more {display: none;}
}
</style>
"""

# ---------- callbacks ----------


def advance_video(rid, new_status, has_post_date):
    vals = {"status": new_status}
    if new_status == "Posted" and not has_post_date:
        vals["post_date"] = date.today()
    update("content", rid, vals)


def advance_brand(rid, new_status):
    update("brands", rid, {"status": new_status})


def shift_month(k):
    first = st.session_state.cal_month
    target = first + timedelta(days=32) if k > 0 else first - timedelta(days=1)
    st.session_state.cal_month = target.replace(day=1)


def go_today():
    st.session_state.cal_month = date.today().replace(day=1)
    st.session_state.sel_day = date.today()


# ---------- app ----------

st.set_page_config(page_title="Affiliate Tracker", page_icon="♡", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)
init_db()

st.session_state.setdefault("cal_month", date.today().replace(day=1))
st.session_state.setdefault("vid_limit", PAGE_SIZE)

videos = rows("content")
brands = rows("brands")
plans = rows("plans")
events = build_events(videos, brands, plans)
locs = location_options(videos, plans)
default_target = int(get_setting("day_target", 3))
today = date.today()


def plan_fields(key, p):
    """Plan form fields (call inside st.form). Returns the values as a dict."""
    act = p.get("activity") or PLAN_ACTIVITIES[0]
    activity = st.radio("What's the plan?", PLAN_ACTIVITIES, horizontal=True,
                        index=PLAN_ACTIVITIES.index(act) if act in PLAN_ACTIVITIES else 0,
                        key=f"{key}_act")
    location = st.selectbox("Where will you take the content?", locs,
                            index=loc_index(locs, p.get("location")), accept_new_options=True,
                            placeholder="Choose a place or type a new one", key=f"{key}_loc")
    c1, c2 = st.columns(2)
    start = c1.text_input("Time (optional)", p.get("start_time") or "", placeholder="e.g. 10:00",
                          key=f"{key}_time")
    target = c2.number_input("Target videos", 1, 50, int(n(p.get("target")) or default_target),
                             key=f"{key}_tg")
    products = st.text_area("Products (one per line)", p.get("products") or "", height=90,
                            placeholder="e.g. Dini's serum\nDini's tote bag", key=f"{key}_pr")
    notes = st.text_input("Notes (optional)", p.get("notes") or "", key=f"{key}_nt")
    return {"activity": activity, "location": (location or "").strip(), "start_time": start.strip(),
            "target": target, "products": products.strip(), "notes": notes.strip()}


st.title("🎬 Affiliate Tracker")

tab_home, tab_cal, tab_videos, tab_brands, tab_settings = st.tabs(
    ["Home", "Calendar", "Videos", "Brands", "Settings"])

# =====================================================================
# HOME
# =====================================================================
with tab_home:
    target = int(get_setting("weekly_target", 6))
    wk_start, wk_end = week_bounds()
    this_week = [v for v in videos
                 if v["status"] == "Posted" and v["post_date"] and wk_start <= v["post_date"] <= wk_end]

    st.subheader("This week")
    st.caption(f"{wk_start:%d %b} - {wk_end:%d %b %Y}")
    st.progress(min(len(this_week) / target, 1.0) if target else 0.0,
                text=f"{len(this_week)} of {target} videos posted")
    if target and len(this_week) >= target:
        st.success("Weekly target reached. 🎉")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Views", f"{int(sum(n(v['views']) for v in this_week)):,}")
    m2.metric("Units sold", f"{int(sum(n(v['units_sold']) for v in this_week)):,}")
    m3.metric("Commission", rupiah(sum(n(v["commission_earned"]) for v in this_week)))
    m4.metric("Ready to post", sum(1 for v in videos if v["status"] == "Ready to Post"))

    st.subheader("This weekend")
    for offset, label in [(5, "Saturday"), (6, "Sunday")]:
        d = wk_start + timedelta(days=offset)
        day_plans = [p for p in plans if p["plan_date"] == d]
        with st.container(border=True):
            st.markdown(f"**{label}, {d:%d %b}**")
            if day_plans:
                for p in day_plans:
                    show_plan_summary(p, videos)
            else:
                st.caption("No plan yet. Add where you'll shoot and how many videos in the Calendar tab.")

    overdue = [v for v in videos if v["status"] != "Posted" and v["post_date"] and v["post_date"] < today]
    need_results = [v for v in videos if v["status"] == "Posted" and v["post_date"]
                    and v["post_date"] <= today - timedelta(days=3) and n(v["views"]) == 0]
    if overdue:
        st.warning(f"{len(overdue)} video(s) are past their planned post date: "
                   + ", ".join(name_of(v) for v in overdue[:3]) + ("..." if len(overdue) > 3 else ""))
    if need_results:
        st.info(f"{len(need_results)} posted video(s) need results (views, sales): "
                + ", ".join(name_of(v) for v in need_results[:3]) + ("..." if len(need_results) > 3 else "")
                + ". Add them in the Videos tab.")

    st.subheader("Coming up (next 7 days)")
    upcoming = sorted((e for e in events if today <= e["date"] <= today + timedelta(days=7)),
                      key=lambda e: (e["date"], KIND_ORDER[e["kind"]]))
    if upcoming:
        for e in upcoming:
            when = "Today" if e["date"] == today else f"{e['date']:%a %d %b}"
            st.markdown(f"{ICON[e['kind']]} **{when}** - {e['label']} "
                        f"<span style='opacity:.6'>({KIND_LABEL[e['kind']]})</span>",
                        unsafe_allow_html=True)
    else:
        st.caption("Nothing scheduled. Plan your shoots and posts in the Calendar tab.")

    with st.expander("Weekly checklist"):
        for i, label in enumerate(CHECKLIST):
            key = f"chk:{wk_start}:{i}"
            stored = get_setting(key, "0") == "1"
            checked = st.checkbox(label, value=stored, key=key)
            if checked != stored:
                set_setting(key, "1" if checked else "0")

    with st.expander("Pipeline"):
        counts = pd.Series({s: sum(1 for v in videos if v["status"] == s) for s in STATUSES})
        st.bar_chart(counts)

    with st.expander("Hooks that sell"):
        agg = defaultdict(lambda: [0, 0, 0])
        for v in videos:
            hook = (v["hook"] or "").strip()
            if v["status"] == "Posted" and hook:
                agg[hook][0] += n(v["views"])
                agg[hook][1] += n(v["units_sold"])
                agg[hook][2] += n(v["commission_earned"])
        if not agg:
            st.caption("Post a few videos with a hook filled in, and your best hooks show up here.")
        else:
            top = pd.DataFrame(agg, index=["Views", "Units sold", "Commission (Rp)"]).T
            st.dataframe(top.sort_values("Commission (Rp)", ascending=False).head(5).astype(int),
                         width="stretch")

# =====================================================================
# CALENDAR
# =====================================================================
with tab_cal:
    year, month = st.session_state.cal_month.year, st.session_state.cal_month.month

    b1, b2, b3, b4 = st.columns([1, 1, 3, 1], vertical_alignment="center")
    b1.button("◀ Prev", on_click=shift_month, args=(-1,), width="stretch")
    b2.button("Today", on_click=go_today, width="stretch")
    b3.markdown(f"<h3 style='text-align:center;margin:0'>{calendar.month_name[month]} {year}</h3>",
                unsafe_allow_html=True)
    b4.button("Next ▶", on_click=shift_month, args=(1,), width="stretch")

    by_day = defaultdict(list)
    for e in events:
        by_day[e["date"]].append(e)

    st.markdown(month_grid_html(year, month, by_day), unsafe_allow_html=True)
    st.markdown(
        "<div class='legend'><span>📍 Day plan</span><span>🎥 Shoot</span><span>📤 Planned post</span>"
        "<span>✅ Posted</span><span>🤝 Brand deadline</span><span>Shaded = weekend</span></div>",
        unsafe_allow_html=True)

    st.subheader("Day details")
    sel = st.date_input("Pick a day", value=today, key="sel_day", format="DD/MM/YYYY")

    day_plans = [p for p in plans if p["plan_date"] == sel]
    other_events = [e for e in by_day.get(sel, []) if e["kind"] != "plan"]
    if not day_plans and not other_events:
        st.caption("Nothing planned for this day yet.")

    for p in day_plans:
        pid = p["id"]
        with st.container(border=True):
            show_plan_summary(p, videos)
            with st.expander("Edit this plan"):
                with st.form(f"plan_edit_{pid}"):
                    vals = plan_fields(f"pe{pid}", p)
                    confirm = st.checkbox("Yes, delete this plan", key=f"pdel{pid}")
                    sc, dc = st.columns(2)
                    saved = sc.form_submit_button("Save changes", type="primary", width="stretch")
                    deleted = dc.form_submit_button("Delete", width="stretch")
                if saved:
                    update("plans", pid, vals)
                    st.rerun()
                if deleted:
                    if confirm:
                        delete("plans", pid)
                        st.rerun()
                    else:
                        st.error("Tick the box first to confirm the delete.")

    for e in other_events:
        st.markdown(f"{ICON[e['kind']]} **{e['label']}** "
                    f"<span style='opacity:.6'>({KIND_LABEL[e['kind']]})</span>",
                    unsafe_allow_html=True)

    with st.expander(f"📍 Plan {sel:%A %d %b}", expanded=not day_plans and sel.weekday() >= 5):
        with st.form("plan_add", clear_on_submit=True):
            first_activity = "Pick up & shoot" if sel.weekday() >= 5 else "Post"
            vals = plan_fields(f"padd_{sel.isoformat()}", {"activity": first_activity})
            make = st.checkbox("Create a video for each product", value=True, key="padd_make")
            if st.form_submit_button("Save plan", type="primary", width="stretch"):
                insert("plans", {"plan_date": sel, **vals})
                if make and vals["activity"] in ("Pick up & shoot", "Shoot"):
                    for line in split_lines(vals["products"]):
                        insert("content", {
                            "product": line, "status": "Ready to Shoot", "shoot_date": sel,
                            "location": vals["location"],
                            "source": "Dini's Stock" if vals["activity"] == "Pick up & shoot" else None,
                        })
                st.rerun()

    unposted = {v["id"]: name_of(v) for v in videos if v["status"] != "Posted"}
    with st.expander("Add an existing video to this day"):
        if not unposted:
            st.caption("No unposted videos yet. Create some with the plan above or in the Videos tab.")
        else:
            with st.form("cal_move", clear_on_submit=True):
                what = st.radio("On this day I will", ["Shoot it", "Post it"], horizontal=True)
                pick = st.selectbox("Video", list(unposted), format_func=lambda i: unposted[i])
                if st.form_submit_button("Add to this day", type="primary", width="stretch"):
                    update("content", pick, {"shoot_date" if what == "Shoot it" else "post_date": sel})
                    st.rerun()

# =====================================================================
# VIDEOS
# =====================================================================
with tab_videos:
    with st.expander("➕ New video"):
        with st.form("add_video", clear_on_submit=True):
            title = st.text_input("Title")
            product = st.text_input("Product")
            s1, s2 = st.columns(2)
            status = s1.selectbox("Status", STATUSES)
            source = s2.selectbox("Product source", SOURCES)
            location = st.selectbox("Where will you shoot it?", locs, index=None,
                                    accept_new_options=True, placeholder="Choose a place or type a new one",
                                    key="new_loc")
            d1, d2 = st.columns(2)
            shoot = d1.date_input("Shoot date", value=None, key="new_shoot")
            post = d2.date_input("Post date", value=None, key="new_post")
            hook = st.text_input("Hook (the first line of the video)")
            if st.form_submit_button("Save video", type="primary", width="stretch"):
                if not (title.strip() or product.strip()):
                    st.error("Add a title or a product name.")
                else:
                    insert("content", {
                        "title": title.strip(), "product": product.strip(), "status": status,
                        "source": source, "location": (location or "").strip(),
                        "shoot_date": shoot, "post_date": post, "hook": hook.strip(),
                    })
                    st.rerun()

    f1, f2 = st.columns([3, 2])
    search = f2.text_input("Search", placeholder="Title or product", label_visibility="collapsed")
    pick_status = f1.pills("Status", ["All"] + STATUSES, default="All", label_visibility="collapsed")

    shown = videos
    if pick_status and pick_status != "All":
        shown = [v for v in shown if v["status"] == pick_status]
    if search.strip():
        q = search.strip().lower()
        shown = [v for v in shown if q in (v["title"] or "").lower() or q in (v["product"] or "").lower()]

    if not videos:
        st.info("No videos yet. Add your first one above.")
    elif not shown:
        st.caption("No videos match this filter.")

    for v in shown[:st.session_state.vid_limit]:
        vid = v["id"]
        with st.container(border=True):
            top, side = st.columns([4, 2], vertical_alignment="center")
            top.markdown(f"**{name_of(v)}**")
            meta = []
            if v["title"] and v["product"]:
                meta.append(v["product"])
            if v["shoot_date"]:
                meta.append(f"Shoot {v['shoot_date']:%d %b}")
            if v["location"]:
                meta.append(f"📍 {v['location']}")
            if v["post_date"]:
                meta.append(f"Post {v['post_date']:%d %b}")
            if meta:
                top.caption("  |  ".join(meta))
            side.markdown(f":blue-badge[{v['status'] or 'Idea'}]")

            nxt = next_status(v["status"], STATUSES)
            if nxt:
                side.button(f"Mark as {nxt}", key=f"adv_v{vid}", on_click=advance_video,
                            args=(vid, nxt, bool(v["post_date"])), width="stretch")

            with st.expander("Edit and results"):
                with st.form(f"edit_v{vid}"):
                    e_title = st.text_input("Title", v["title"] or "")
                    e_product = st.text_input("Product", v["product"] or "")
                    s1, s2 = st.columns(2)
                    e_status = s1.selectbox(
                        "Status", STATUSES,
                        index=STATUSES.index(v["status"]) if v["status"] in STATUSES else 0)
                    e_source = s2.selectbox(
                        "Product source", SOURCES,
                        index=SOURCES.index(v["source"]) if v["source"] in SOURCES else 0)
                    e_loc = st.selectbox("Where will you shoot it?", locs,
                                         index=loc_index(locs, v["location"]), accept_new_options=True,
                                         placeholder="Choose a place or type a new one", key=f"loc{vid}")
                    d1, d2 = st.columns(2)
                    e_shoot = d1.date_input("Shoot date", value=v["shoot_date"], key=f"sh{vid}")
                    e_post = d2.date_input("Post date", value=v["post_date"], key=f"po{vid}")
                    e_hook = st.text_input("Hook", v["hook"] or "")
                    e_link = st.text_input("Video link", v["video_link"] or "")
                    e_pct = st.number_input("Commission %", 0.0, 100.0, float(n(v["commission_pct"])),
                                            step=0.5, key=f"pct{vid}")
                    e_notes = st.text_area("Notes", v["notes"] or "", height=70)

                    st.markdown("**Results** (log about 3 days after posting)")
                    r1, r2, r3 = st.columns(3)
                    e_views = r1.number_input("Views", 0, value=int(n(v["views"])), step=100, key=f"vw{vid}")
                    e_clicks = r2.number_input("Cart clicks", 0, value=int(n(v["cart_clicks"])), key=f"cc{vid}")
                    e_sold = r3.number_input("Units sold", 0, value=int(n(v["units_sold"])), key=f"us{vid}")
                    r4, r5 = st.columns(2)
                    e_comm = r4.number_input("Commission earned (Rp)", 0, value=int(n(v["commission_earned"])),
                                             step=1000, key=f"ce{vid}")
                    e_edit = r5.number_input("Edit time (min)", 0, value=int(n(v["edit_minutes"])), key=f"em{vid}")

                    confirm = st.checkbox("Yes, delete this video", key=f"cd{vid}")
                    save_col, del_col = st.columns(2)
                    saved = save_col.form_submit_button("Save changes", type="primary", width="stretch")
                    deleted = del_col.form_submit_button("Delete", width="stretch")

                if saved:
                    if e_status == "Posted" and not e_post:
                        e_post = today
                    update("content", vid, {
                        "title": e_title.strip(), "product": e_product.strip(), "status": e_status,
                        "source": e_source, "location": (e_loc or "").strip(),
                        "shoot_date": e_shoot, "post_date": e_post,
                        "hook": e_hook.strip(), "video_link": e_link.strip(), "commission_pct": e_pct,
                        "notes": e_notes.strip(), "views": e_views, "cart_clicks": e_clicks,
                        "units_sold": e_sold, "commission_earned": e_comm, "edit_minutes": e_edit,
                    })
                    st.rerun()
                if deleted:
                    if confirm:
                        delete("content", vid)
                        st.rerun()
                    else:
                        st.error("Tick the box first to confirm the delete.")

    if len(shown) > st.session_state.vid_limit:
        if st.button(f"Show more ({len(shown) - st.session_state.vid_limit} left)", width="stretch"):
            st.session_state.vid_limit += PAGE_SIZE
            st.rerun()

# =====================================================================
# BRANDS
# =====================================================================
with tab_brands:
    with st.expander("➕ New brand"):
        with st.form("add_brand", clear_on_submit=True):
            name = st.text_input("Brand name")
            contact = st.text_input("Contact (WhatsApp / email / IG)")
            product = st.text_input("Product")
            a, b = st.columns(2)
            bstatus = a.selectbox("Status", BRAND_STATUSES)
            fee = b.text_input("Commission / fee")
            deadline = st.date_input("Deadline", value=None, key="new_deadline")
            if st.form_submit_button("Save brand", type="primary", width="stretch"):
                if not name.strip():
                    st.error("Brand name is required.")
                else:
                    insert("brands", {"name": name.strip(), "contact": contact.strip(),
                                      "product": product.strip(), "status": bstatus,
                                      "fee": fee.strip(), "deadline": deadline})
                    st.rerun()

    if not brands:
        st.info("When a brand reaches out or you pitch one, track it here.")

    for br in brands:
        bid = br["id"]
        with st.container(border=True):
            top, side = st.columns([4, 2], vertical_alignment="center")
            top.markdown(f"**{name_of(br)}**")
            meta = [x for x in [br["product"], br["fee"],
                                f"Due {br['deadline']:%d %b}" if br["deadline"] else None] if x]
            if meta:
                top.caption("  |  ".join(meta))
            side.markdown(f":violet-badge[{br['status'] or 'New Contact'}]")

            nxt = next_status(br["status"], BRAND_STATUSES)
            if nxt:
                side.button(f"Mark as {nxt}", key=f"adv_b{bid}", on_click=advance_brand,
                            args=(bid, nxt), width="stretch")

            with st.expander("Edit"):
                with st.form(f"edit_b{bid}"):
                    e_name = st.text_input("Brand name", br["name"] or "")
                    e_contact = st.text_input("Contact", br["contact"] or "")
                    e_product = st.text_input("Product", br["product"] or "")
                    c1, c2 = st.columns(2)
                    e_status = c1.selectbox(
                        "Status", BRAND_STATUSES,
                        index=BRAND_STATUSES.index(br["status"]) if br["status"] in BRAND_STATUSES else 0)
                    e_fee = c2.text_input("Commission / fee", br["fee"] or "")
                    e_deadline = st.date_input("Deadline", value=br["deadline"], key=f"bd{bid}")
                    e_notes = st.text_area("Notes", br["notes"] or "", height=70)
                    confirm = st.checkbox("Yes, delete this brand", key=f"cb{bid}")
                    sc, dc = st.columns(2)
                    saved = sc.form_submit_button("Save changes", type="primary", width="stretch")
                    deleted = dc.form_submit_button("Delete", width="stretch")
                if saved:
                    update("brands", bid, {"name": e_name.strip(), "contact": e_contact.strip(),
                                           "product": e_product.strip(), "status": e_status,
                                           "fee": e_fee.strip(), "deadline": e_deadline,
                                           "notes": e_notes.strip()})
                    st.rerun()
                if deleted:
                    if confirm:
                        delete("brands", bid)
                        st.rerun()
                    else:
                        st.error("Tick the box first to confirm the delete.")

# =====================================================================
# SETTINGS
# =====================================================================
with tab_settings:
    st.subheader("My targets")
    t1, t2 = st.columns(2)
    new_target = t1.number_input("Videos to post per week", min_value=1, max_value=50,
                                 value=int(get_setting("weekly_target", 6)))
    new_day_target = t2.number_input("Videos to shoot per shoot day", min_value=1, max_value=50,
                                     value=default_target)
    new_locs = st.text_input("My usual places to shoot (separate with commas)",
                             value=get_setting("locations", "Dini's place, Home"))
    if st.button("Save settings", type="primary"):
        set_setting("weekly_target", new_target)
        set_setting("day_target", new_day_target)
        set_setting("locations", new_locs)
        st.toast("Settings saved")
        st.rerun()
    st.caption("Suggested ramp: 6-8 videos in weeks 1-2, then 10 once editing keeps up.")

    st.subheader("Backup")
    c1, c2, c3 = st.columns(3)
    c1.download_button("Videos (CSV)", pd.DataFrame(videos).to_csv(index=False).encode("utf-8"),
                       file_name="content_backup.csv", mime="text/csv", width="stretch")
    c2.download_button("Brands (CSV)", pd.DataFrame(brands).to_csv(index=False).encode("utf-8"),
                       file_name="brands_backup.csv", mime="text/csv", width="stretch")
    c3.download_button("Day plans (CSV)", pd.DataFrame(plans).to_csv(index=False).encode("utf-8"),
                       file_name="plans_backup.csv", mime="text/csv", width="stretch")
