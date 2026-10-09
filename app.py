"""TikTok Affiliate Tracker - Streamlit app.

Run:  streamlit run app.py
Data is stored locally in tracker.db (SQLite).
"""
import sqlite3
from datetime import date, timedelta

import pandas as pd
import streamlit as st

DB_PATH = "tracker.db"

STATUSES = ["Idea", "Ready to Shoot", "Shot", "Editing", "Ready to Post", "Posted"]
SOURCES = ["Friend's Stock", "Brand/Sample", "Self-Purchased"]
BRAND_STATUSES = ["New Contact", "Negotiating", "Deal", "Sample Sent", "Content Made", "Done"]

CONTENT_COLS = {
    "title": "TEXT", "product": "TEXT", "source": "TEXT", "commission_pct": "REAL",
    "status": "TEXT", "shoot_date": "TEXT", "post_date": "TEXT", "hook": "TEXT",
    "video_link": "TEXT", "edit_minutes": "REAL", "views": "INTEGER",
    "cart_clicks": "INTEGER", "units_sold": "INTEGER", "commission_earned": "REAL",
    "notes": "TEXT",
}
BRAND_COLS = {
    "name": "TEXT", "contact": "TEXT", "product": "TEXT", "status": "TEXT",
    "fee": "TEXT", "deadline": "TEXT", "notes": "TEXT",
}
DATE_COLS = {"content": ["shoot_date", "post_date"], "brands": ["deadline"]}
TABLE_COLS = {"content": CONTENT_COLS, "brands": BRAND_COLS}

CHECKLIST = [
    "Friday: pick products and hooks for the weekend shoot",
    "Saturday-Sunday: shoot the day's products",
    "Sunday night: 15-minute results review",
    "Research 5 new hooks",
]

# ---------- database ----------

def conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    with conn() as c:
        for table, cols in TABLE_COLS.items():
            defs = ", ".join(f"{k} {v}" for k, v in cols.items())
            c.execute(f"CREATE TABLE IF NOT EXISTS {table} (id INTEGER PRIMARY KEY AUTOINCREMENT, {defs})")
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")


def get_setting(key, default):
    with conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(key, value):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


def _to_date(x):
    if x is None or pd.isna(x):
        return None
    return x


def load(table):
    with conn() as c:
        df = pd.read_sql(f"SELECT * FROM {table} ORDER BY id DESC", c)
    df = df.drop(columns=["id"])
    for col in DATE_COLS[table]:
        df[col] = pd.to_datetime(df[col], errors="coerce").dt.date.apply(_to_date)
    return df


def save(table, df):
    cols = list(TABLE_COLS[table].keys())
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            out[col] = None
    for col in DATE_COLS[table]:
        out[col] = out[col].apply(lambda d: d.isoformat() if isinstance(d, date) else None)
    out = out[cols].iloc[::-1]  # keep newest-first order stable across saves
    with conn() as c:
        c.execute(f"DELETE FROM {table}")
        out.to_sql(table, c, if_exists="append", index=False)


def insert(table, row: dict):
    row = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in row.items()}
    keys = list(row.keys())
    with conn() as c:
        c.execute(
            f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join('?' for _ in keys)})",
            [row[k] for k in keys],
        )


# ---------- helpers ----------

def week_bounds(today=None):
    today = today or date.today()
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def num(series):
    return pd.to_numeric(series, errors="coerce").fillna(0)


def rupiah(n):
    return "Rp" + f"{int(n):,}".replace(",", ".")


CSS = """
<style>
.block-container {max-width: 1100px; padding-top: 1.5rem;}
@media (max-width: 640px) {
  .block-container {padding: 1rem 0.75rem 3rem;}
  h1 {font-size: 1.6rem !important;}
}
div[data-testid="stMetric"] {
  background: #E8EEEB; border-radius: 10px; padding: 0.7rem 0.9rem;
}
button[role="tab"] {font-size: 1rem;}
</style>
"""

# ---------- app ----------

st.set_page_config(page_title="Affiliate Tracker", page_icon="🎬", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)
init_db()

st.title("Affiliate Tracker")

tab_home, tab_add, tab_content, tab_brands, tab_settings = st.tabs(
    ["📊 Week", "➕ Add", "🎬 Content", "🤝 Brands", "⚙️ Settings"]
)

# ----- Week dashboard -----
with tab_home:
    target = int(get_setting("weekly_target", 6))
    wk_start, wk_end = week_bounds()
    df = load("content")

    posted = df[df["status"] == "Posted"]
    in_week = posted["post_date"].map(
        lambda d: isinstance(d, date) and wk_start <= d <= wk_end).astype(bool)
    this_week = posted[in_week]

    st.caption(f"Week of {wk_start:%d %b} - {wk_end:%d %b %Y}")
    count = len(this_week)
    st.progress(min(count / target, 1.0) if target else 0.0,
                text=f"{count} of {target} videos posted this week")
    if target and count >= target:
        st.success("Weekly target reached.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Views", f"{int(num(this_week['views']).sum()):,}")
    c2.metric("Units sold", f"{int(num(this_week['units_sold']).sum()):,}")
    c3.metric("Commission", rupiah(num(this_week["commission_earned"]).sum()))
    c4.metric("Ready to post", int((df["status"] == "Ready to Post").sum()))

    st.subheader("Pipeline")
    pipe = df["status"].value_counts().reindex(STATUSES, fill_value=0)
    st.bar_chart(pipe)

    st.subheader("This week's checklist")
    for i, label in enumerate(CHECKLIST):
        key = f"chk:{wk_start}:{i}"
        stored = get_setting(key, "0") == "1"
        checked = st.checkbox(label, value=stored, key=key)
        if checked != stored:
            set_setting(key, "1" if checked else "0")

    st.subheader("Hooks that sell")
    hooks = posted[posted["hook"].fillna("").str.strip() != ""]
    if hooks.empty:
        st.info("Post a few videos with a hook filled in, and your best hooks show up here.")
    else:
        top = (hooks.assign(views=num(hooks["views"]), units_sold=num(hooks["units_sold"]),
                            commission_earned=num(hooks["commission_earned"]))
               .groupby("hook")[["views", "units_sold", "commission_earned"]].sum()
               .sort_values("commission_earned", ascending=False).head(5))
        st.dataframe(top, width="stretch")

    edit = num(df[df["status"].isin(["Ready to Post", "Posted"])]["edit_minutes"])
    edit = edit[edit > 0]
    if not edit.empty:
        st.caption(f"Average edit time: {edit.mean():.0f} minutes per video ({len(edit)} logged).")

# ----- Add content -----
with tab_add:
    st.subheader("New video")
    with st.form("add_content", clear_on_submit=True):
        title = st.text_input("Video title")
        product = st.text_input("Product")
        a, b = st.columns(2)
        source = a.selectbox("Product source", SOURCES)
        commission = b.number_input("Commission %", min_value=0.0, max_value=100.0, step=0.5)
        status = st.selectbox("Status", STATUSES)
        d1, d2 = st.columns(2)
        shoot = d1.date_input("Shoot date", value=None)
        post = d2.date_input("Post date", value=None)
        hook = st.text_input("Hook")
        notes = st.text_area("Notes", height=80)
        if st.form_submit_button("Save video", type="primary", width="stretch"):
            if not (title.strip() or product.strip()):
                st.error("Add a title or a product name first.")
            else:
                insert("content", {
                    "title": title.strip(), "product": product.strip(), "source": source,
                    "commission_pct": commission, "status": status,
                    "shoot_date": shoot, "post_date": post, "hook": hook.strip(),
                    "notes": notes.strip(),
                })
                st.success("Saved. Find it in the Content tab.")

# ----- Content table -----
with tab_content:
    df = load("content")
    picked = st.multiselect("Filter by status", STATUSES, default=[], placeholder="All statuses")
    view = df[df["status"].isin(picked)] if picked else df

    if df.empty:
        st.info("No videos yet. Add your first one in the Add tab.")
    else:
        st.caption("Tap a cell to edit. Log results about 3 days after posting, then save.")
        edited = st.data_editor(
            view, key="content_editor", hide_index=True, width="stretch",
            num_rows="fixed",
            column_order=["title", "product", "status", "post_date", "views", "cart_clicks",
                          "units_sold", "commission_earned", "hook", "source", "commission_pct",
                          "shoot_date", "edit_minutes", "video_link", "notes"],
            column_config={
                "title": st.column_config.TextColumn("Title", width="medium"),
                "product": st.column_config.TextColumn("Product", width="medium"),
                "source": st.column_config.SelectboxColumn("Source", options=SOURCES),
                "commission_pct": st.column_config.NumberColumn("Comm %", min_value=0, max_value=100),
                "status": st.column_config.SelectboxColumn("Status", options=STATUSES, required=True),
                "shoot_date": st.column_config.DateColumn("Shoot date"),
                "post_date": st.column_config.DateColumn("Post date"),
                "hook": st.column_config.TextColumn("Hook", width="medium"),
                "video_link": st.column_config.LinkColumn("Video link"),
                "edit_minutes": st.column_config.NumberColumn("Edit (min)", min_value=0),
                "views": st.column_config.NumberColumn("Views", min_value=0),
                "cart_clicks": st.column_config.NumberColumn("Cart clicks", min_value=0),
                "units_sold": st.column_config.NumberColumn("Sold", min_value=0),
                "commission_earned": st.column_config.NumberColumn("Commission (Rp)", min_value=0),
                "notes": st.column_config.TextColumn("Notes", width="large"),
            },
        )
        if st.button("Save changes", type="primary", width="stretch", key="save_content"):
            merged = df.copy()
            merged.loc[edited.index] = edited
            save("content", merged)
            st.toast("Changes saved")
            st.rerun()

        with st.expander("Delete videos"):
            options = {f"{i}: {r['title'] or r['product']}": i for i, r in df.iterrows()}
            doomed = st.multiselect("Select videos to delete", list(options.keys()))
            if st.button("Delete selected", key="del_content") and doomed:
                save("content", df.drop(index=[options[k] for k in doomed]))
                st.rerun()

# ----- Brands -----
with tab_brands:
    st.subheader("Brands and shops")
    with st.expander("Add a brand", expanded=False):
        with st.form("add_brand", clear_on_submit=True):
            name = st.text_input("Brand name")
            contact = st.text_input("Contact (WhatsApp / email / IG)")
            product = st.text_input("Product")
            a, b = st.columns(2)
            bstatus = a.selectbox("Status", BRAND_STATUSES)
            fee = b.text_input("Commission / fee")
            deadline = st.date_input("Deadline", value=None)
            bnotes = st.text_area("Notes", height=70)
            if st.form_submit_button("Save brand", type="primary", width="stretch"):
                if not name.strip():
                    st.error("Brand name is required.")
                else:
                    insert("brands", {"name": name.strip(), "contact": contact.strip(),
                                      "product": product.strip(), "status": bstatus,
                                      "fee": fee.strip(), "deadline": deadline,
                                      "notes": bnotes.strip()})
                    st.success("Brand saved.")
                    st.rerun()

    bdf = load("brands")
    if bdf.empty:
        st.info("When a brand reaches out or you pitch one, track it here.")
    else:
        bedit = st.data_editor(
            bdf, key="brand_editor", hide_index=True, width="stretch", num_rows="fixed",
            column_config={
                "name": st.column_config.TextColumn("Brand", width="medium"),
                "contact": st.column_config.TextColumn("Contact", width="medium"),
                "product": st.column_config.TextColumn("Product", width="medium"),
                "status": st.column_config.SelectboxColumn("Status", options=BRAND_STATUSES),
                "fee": st.column_config.TextColumn("Fee"),
                "deadline": st.column_config.DateColumn("Deadline"),
                "notes": st.column_config.TextColumn("Notes", width="large"),
            },
        )
        if st.button("Save brand changes", type="primary", width="stretch", key="save_brands"):
            merged = bdf.copy()
            merged.loc[bedit.index] = bedit
            save("brands", merged)
            st.toast("Changes saved")
            st.rerun()

# ----- Settings -----
with tab_settings:
    st.subheader("Weekly target")
    new_target = st.number_input("Videos to post per week", min_value=1, max_value=50,
                                 value=int(get_setting("weekly_target", 6)))
    if st.button("Save target", type="primary", width="stretch"):
        set_setting("weekly_target", new_target)
        st.toast("Target saved")
        st.rerun()
    st.caption("Suggested ramp: 6-8 videos in weeks 1-2, then 10 once editing keeps up.")

    st.subheader("Backup")
    cdf = load("content")
    st.download_button("Download content (CSV)", cdf.to_csv(index=False).encode("utf-8"),
                       file_name="content_backup.csv", mime="text/csv", width="stretch")
    bdf = load("brands")
    st.download_button("Download brands (CSV)", bdf.to_csv(index=False).encode("utf-8"),
                       file_name="brands_backup.csv", mime="text/csv", width="stretch")
