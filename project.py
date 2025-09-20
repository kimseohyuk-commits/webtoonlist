# app.py
import streamlit as st
import sqlite3, json, os, time, uuid, re
from datetime import datetime
from streamlit_oauth import OAuth2Component
import requests
from bs4 import BeautifulSoup
from supabase import create_client, Client
import streamlit.components.v1 as components

st.set_page_config(page_title="웹툰 공유 리스트", layout="wide")

# =========================
# --- Secrets / Config
# =========================
def require_secret(path: str):
    cur = st.secrets
    for p in path.split("."):
        if p not in cur:
            st.error(f"Secrets 설정이 필요합니다: [{path}] (.streamlit/secrets.toml)")
            st.stop()
        cur = cur[p]
    return cur

GOOGLE = require_secret("google_oauth")
SUPA = require_secret("supabase")
APP = st.secrets.get("app", {})  # admin_email 등

# =========================
# --- DB (SQLite for shares data)
# =========================
DB_FILE = "shares.db"
def db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shares (
            id TEXT PRIMARY KEY,
            owner_email TEXT,
            owner_name TEXT,
            title TEXT,
            data_json TEXT,
            is_public INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    return conn

# =========================
# --- Supabase (likes/views/comments)
# =========================
def supa() -> Client:
    return create_client(SUPA["url"], SUPA["anon_key"])

def get_like_count(share_id: str) -> int:
    sb = supa()
    res = sb.table("likes").select("share_id", count="exact").eq("share_id", share_id).execute()
    return res.count or 0

def has_liked(share_id: str, email: str) -> bool:
    sb = supa()
    res = sb.table("likes").select("*").eq("share_id", share_id).eq("email", email).limit(1).execute()
    return len(res.data or []) > 0

def toggle_like(share_id: str, email: str):
    sb = supa()
    if has_liked(share_id, email):
        sb.table("likes").delete().eq("share_id", share_id).eq("email", email).execute()
    else:
        sb.table("likes").insert({"share_id": share_id, "email": email}).execute()

def add_view_once(share_id: str):
    key = f"__viewed_{share_id}"
    if st.session_state.get(key): return
    st.session_state[key] = True
    sb = supa()
    sb.table("views").insert({"share_id": share_id}).execute()

def get_view_count(share_id: str) -> int:
    sb = supa()
    res = sb.table("views").select("share_id", count="exact").eq("share_id", share_id).execute()
    return res.count or 0

def list_comments(share_id: str, limit=100):
    sb = supa()
    res = sb.table("comments").select("*").eq("share_id", share_id).order("created_at", desc=True).limit(limit).execute()
    return res.data or []

def add_comment(share_id: str, email: str, name: str, text: str):
    if not text.strip(): return
    sb = supa()
    sb.table("comments").insert({
        "share_id": share_id,
        "email": email or None,
        "name": name or None,
        "text": text.strip()
    }).execute()

# =========================
# --- OAuth (Google)
# =========================
from streamlit_oauth import OAuth2Component

def google_oauth_button():
    # 순서대로: client_id, client_secret, authorize_endpoint, token_endpoint,
    #           refresh_token_endpoint, revoke_token_endpoint
    oauth = OAuth2Component(
        GOOGLE["client_id"],
        GOOGLE["client_secret"],
        "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
        "https://oauth2.googleapis.com/token",
        None,
        
    )
    return oauth, GOOGLE["redirect_uri"]

def oauth_authorize_button(oauth, label: str, redirect_uri: str, key: str):
    """
    여러 버전 호환:
    - 어떤 버전은 scope를 '문자열'로, 어떤 버전은 list로 받음.
    먼저 문자열로 시도 → 실패하면 list로 재시도.
    """
    scope_str = "openid email profile"
    scope_list = ["openid", "email", "profile"]

    # 0) 0.1.14 스타일: 위치 인자 + 문자열 scope
    try:
        return oauth.authorize_button(label, redirect_uri, scope_str, key, True, {"prompt": "select_account"})
    except TypeError:
        pass

    # 1) 키워드 인자 + 문자열 scope
    try:
        return oauth.authorize_button(
            label,
            redirect_uri=redirect_uri,
            scope=scope_str,
            key=key,
            use_container_width=True,
            extras_params={"prompt": "select_account"},
        )
    except TypeError:
        pass

    # 2) 키워드 인자 + 리스트 scope (일부 포크/버전)
    try:
        return oauth.authorize_button(
            label,
            redirect_uri=redirect_uri,
            scope=scope_list,
            key=key,
            use_container_width=True,
            extras_params={"prompt": "select_account"},
        )
    except TypeError as e:
        import inspect
        st.error("`authorize_button` 시그니처가 예상과 다릅니다. 아래 시그니처를 보고 맞춰 주세요.")
        st.code(str(inspect.signature(oauth.authorize_button)))
        raise e

def fetch_google_userinfo(access_token: str):
    try:
        r = requests.get("https://www.googleapis.com/oauth2/v3/userinfo",
                        headers={"Authorization": f"Bearer {access_token}"}, timeout=6)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

# =========================
# --- i18n (ko/en)
# =========================
st.session_state.setdefault("__lang", "ko")
LANG = {
    "ko": {
        "app_title": "웹툰 공유 리스트",
        "login_google": "Google로 로그인",
        "logout": "로그아웃",
        "my_list": "내 목록",
        "discover": "Discover · 공개 공유",
        "add_item": "+ 항목 추가",
        "sort": "정렬",
        "sort_recent": "최근 수정",
        "sort_az": "가나다",
        "share_title": "공유 제목",
        "public": "공개(Discover 노출)",
        "make_link": "🔗 공유 링크 만들기",
        "open": "열기",
        "title": "제목",
        "link": "링크",
        "note": "메모",
        "updated": "최근 수정",
        "share": "공유",
        "by": "작성자",
        "view": "보기",
        "copy_to_me": "📥 내 목록에 담기",
        "need_login": "로그인하세요.",
        "not_found": "존재하지 않는 공유 링크입니다.",
        "theme": "테마",
        "system": "시스템",
        "light": "라이트",
        "dark": "다크",
        "like": "좋아요",
        "likes": "좋아요",
        "views": "조회수",
        "comment": "댓글",
        "add_comment": "댓글 남기기",
        "placeholder_comment": "응원/후기를 적어주세요",
        "save_changes": "변경사항 저장",
        "edit_mode": "편집 모드",
        "preview": "미리보기",
        "create_share_success": "공유 링크가 생성됐어요!",
    },
    "en": {
        "app_title": "Webtoon Share List",
        "login_google": "Login with Google",
        "logout": "Log out",
        "my_list": "My List",
        "discover": "Discover · Public Shares",
        "add_item": "+ Add item",
        "sort": "Sort",
        "sort_recent": "Recently updated",
        "sort_az": "A–Z",
        "share_title": "Share title",
        "public": "Public (show in Discover)",
        "make_link": "🔗 Create share link",
        "open": "Open",
        "title": "Title",
        "link": "Link",
        "note": "Note",
        "updated": "Updated",
        "share": "Share",
        "by": "by",
        "view": "View",
        "copy_to_me": "📥 Save to my list",
        "need_login": "Please sign in.",
        "not_found": "Share link not found.",
        "theme": "Theme",
        "system": "System",
        "light": "Light",
        "dark": "Dark",
        "like": "Like",
        "likes": "Likes",
        "views": "Views",
        "comment": "Comments",
        "add_comment": "Add a comment",
        "placeholder_comment": "Leave a message",
        "save_changes": "Save changes",
        "edit_mode": "Edit mode",
        "preview": "Preview",
        "create_share_success": "Share link created!",
    }
}
def t(key): return LANG[st.session_state["__lang"]].get(key, key)

# =========================
# --- Session Defaults
# =========================
st.session_state.setdefault("user", None)       # {"email","name","picture"}
st.session_state.setdefault("my_list", [])      # [{title,link,note,updated_at}]
st.session_state.setdefault("sort_mode", "최근 수정")
st.session_state.setdefault("__theme", "시스템")  # 시스템/라이트/다크
st.session_state.setdefault("__discover_cache_at", 0.0)

# =========================
# --- Util
# =========================
def now_iso(): return datetime.now().isoformat(timespec="seconds")

def norm_item(i):
    i.setdefault("title","")
    i.setdefault("link","")
    i.setdefault("note","")
    i.setdefault("updated_at", now_iso())
    return i

def save_to_db(share_id, owner_email, owner_name, title, data_list, is_public: bool):
    conn = db()
    payload = json.dumps([norm_item(x) for x in data_list], ensure_ascii=False)
    tnow = now_iso()
    if share_id:
        conn.execute("UPDATE shares SET title=?, data_json=?, is_public=?, updated_at=? WHERE id=?",
                    (title, payload, 1 if is_public else 0, tnow, share_id))
    else:
        share_id = uuid.uuid4().hex[:12]
        conn.execute("""INSERT INTO shares(id, owner_email, owner_name, title, data_json, is_public, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?)""",
                    (share_id, owner_email, owner_name, title, payload, 1 if is_public else 0, tnow, tnow))
    conn.commit()
    return share_id

def load_share(share_id):
    conn = db()
    cur = conn.execute("SELECT id, owner_email, owner_name, title, data_json, is_public, created_at, updated_at FROM shares WHERE id=?", (share_id,))
    row = cur.fetchone()
    if not row: return None
    return {
        "id": row[0],
        "owner_email": row[1],
        "owner_name": row[2],
        "title": row[3],
        "data": json.loads(row[4] or "[]"),
        "is_public": bool(row[5]),
        "created_at": row[6],
        "updated_at": row[7],
    }

def discover_public(limit=100):
    conn = db()
    cur = conn.execute("""
        SELECT id, owner_name, title, updated_at
        FROM shares WHERE is_public=1
        ORDER BY updated_at DESC
        LIMIT ?
    """, (limit,))
    return [{"id":r[0], "owner_name":r[1], "title":r[2], "updated_at":r[3]} for r in cur.fetchall()]

def sort_list(lst, mode):
    if mode in ("최근 수정","Recently updated"):
        lst.sort(key=lambda x: x.get("updated_at",""), reverse=True)
    else:
        lst.sort(key=lambda x: (x.get("title") or "").lower())

def touch_item(it): it["updated_at"] = now_iso()

def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if url and not (url.startswith("http://") or url.startswith("https://")):
        url = "http://" + url
    return url

@st.cache_data(show_spinner=False, ttl=60*60)
def fetch_og_thumb(url: str, timeout=4.0):
    try:
        if not url: return ""
        headers = {"User-Agent": "Mozilla/5.0 (WebtoonShare/1.0)", "Accept-Language":"ko-KR,ko;q=0.9,en-US;q=0.8"}
        r = requests.get(url, headers=headers, timeout=timeout)
        if r.status_code != 200: return ""
        soup = BeautifulSoup(r.text, "html.parser")
        tag = soup.select_one('meta[property="og:image"], meta[name="twitter:image"]')
        img = (tag.get("content") if tag else "") or ""
        if img.startswith("//"): img = "https:" + img
        return img
    except Exception:
        return ""

def can_edit_share(data) -> bool:
    user = st.session_state.get("user")
    admin = APP.get("admin_email")
    if not user: return False
    return (user.get("email") == data.get("owner_email")) or (admin and user.get("email") == admin)

# =========================
# --- Styling / Theme & Float Buttons
# =========================
st.markdown("""
<style>
:root{
--card:#ffffff; --border:#e5e7eb; --muted:#6b7280; --text:#0f172a; --shadow:0 1px 3px rgba(0,0,0,.04);
}
:root[data-theme="dark"]{
--card:#0f172a; --border:#1f2937; --muted:#9ca3af; --text:#e5e7eb; --shadow:0 1px 3px rgba(0,0,0,.35);
}
@media (prefers-color-scheme: dark){
:root:not([data-theme="light"]):not([data-theme="dark"]){
    --card:#0f172a; --border:#1f2937; --muted:#9ca3af; --text:#e5e7eb; --shadow:0 1px 3px rgba(0,0,0,.35);
}
}
.block-container { padding-top:.6rem; padding-bottom:.6rem; color:var(--text); }
.item-card{ border:1px solid var(--border); border-radius:10px; padding:8px 10px; margin-bottom:8px; background:var(--card); box-shadow:var(--shadow); }
.item-row{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.item-small{ font-size:.8rem; color:var(--muted); }
.floatWrap{ position:fixed; right:16px; bottom:16px; z-index:9999; display:flex; flex-direction:column; gap:8px }
.floatBtn{ background:var(--card); color:var(--text); border:1px solid var(--border); border-radius:999px; padding:.5rem .8rem; box-shadow:var(--shadow); cursor:pointer }
.floatBtn:hover{ filter:brightness(1.05); }
</style>
""", unsafe_allow_html=True)

def theme_toggle():
    # 언어/테마/로그인 바
    top = st.container()
    with top:
        c1,c2,c3,c4 = st.columns([3,2,3,2])
        with c1:
            st.markdown(f"### {t('app_title')}")
        with c2:
            lang_opt = st.selectbox("Language", ["한국어","English"], index=0 if st.session_state["__lang"]=="ko" else 1)
            st.session_state["__lang"] = "ko" if lang_opt=="한국어" else "en"
        with c3:
            theme = st.selectbox(t("theme"), [t("system"), t("light"), t("dark")], index={"시스템":0,"System":0,"라이트":1,"Light":1,"다크":2,"Dark":2}[st.session_state["__theme"]])
            st.session_state["__theme"] = "시스템" if theme in ("시스템","System") else ("라이트" if theme in ("라이트","Light") else "다크")
        with c4:
            if st.session_state["user"]:
                u = st.session_state["user"]
                st.write(f"👤 {u.get('name','')} ({u.get('email','')})")
                if st.button(t("logout")):
                    st.session_state["user"] = None
                    st.experimental_set_query_params()
                    st.rerun()
            else:
                oauth, redirect_uri = google_oauth_button()
                result = oauth_authorize_button(oauth, t("login_google"), redirect_uri, "google_btn")

                if result and "token" in result:
                    token = result["token"]
                    info = fetch_google_userinfo(token["access_token"])
                    if info:
                        st.session_state["user"] = {
                            "email": info.get("email"),
                            "name": info.get("name") or info.get("given_name") or "",
                            "picture": info.get("picture"),
                        }
                        st.success("Login success!")
                        st.rerun()

    # 테마 적용
    components.html(f"""
    <script>
    const rt=document.documentElement; const m="{st.session_state['__theme']}";
    if(m==="다크"||m==="Dark") rt.setAttribute("data-theme","dark");
    else if(m==="라이트"||m==="Light") rt.setAttribute("data-theme","light");
    else rt.removeAttribute("data-theme");
    </script>
    """, height=0)

def float_scroll_buttons():
    components.html("""
    <div class="floatWrap">
    <button class="floatBtn" onclick="parent.window.scrollTo({top:0,behavior:'smooth'})">↑ Top</button>
    <button class="floatBtn" onclick="parent.window.scrollTo({top:parent.document.body.scrollHeight,behavior:'smooth'})">↓ Bottom</button>
    </div>
    """, height=0)

# =========================
# --- Login Bar + Theme + Float Buttons
# =========================
theme_toggle()
float_scroll_buttons()

# =========================
# --- My List Page
# =========================
st.session_state.setdefault("my_list", [])
def page_my_list():
    st.subheader(t("my_list"))
    c1,c2,c3,c4 = st.columns([2,2,3,3])
    with c1:
        if st.button(t("add_item")):
            st.session_state["my_list"].append(norm_item({"title":"","link":"","note":""}))
            st.rerun()
    with c2:
        st.session_state["sort_mode"] = st.selectbox(t("sort"), [t("sort_recent"), t("sort_az")], index=0 if st.session_state["sort_mode"] in ("최근 수정","Recently updated") else 1)
    with c3:
        share_title = st.text_input(t("share_title"), value="내가 좋아하는 웹툰" if st.session_state["__lang"]=="ko" else "My favorite webtoons")
    with c4:
        pub = st.toggle(t("public"), value=True)
    st.divider()

    lst = st.session_state["my_list"]
    sort_list(lst, st.session_state["sort_mode"])
    trash = []
    for i, it in enumerate(lst):
        st.markdown('<div class="item-card">', unsafe_allow_html=True)
        r1,r2,r3,r4,r5 = st.columns([3,4,3,1,1])
        with r1:
            new_title = st.text_input(t("title"), value=it["title"], key=f"t_{i}")
            if new_title != it["title"]:
                it["title"] = new_title; touch_item(it)
        with r2:
            new_link = st.text_input(t("link"), value=it["link"], key=f"l_{i}", placeholder="https://...")
            if new_link != it["link"]:
                it["link"] = normalize_link(new_link); touch_item(it)
        with r3:
            new_note = st.text_input(t("note"), value=it["note"], key=f"n_{i}")
            if new_note != it["note"]:
                it["note"] = new_note; touch_item(it)
        with r4:
            if it["link"]: st.link_button(t("open"), it["link"])
            else: st.caption("—")
        with r5:
            if st.button("🗑", key=f"d_{i}"): trash.append(i)
        st.caption(f"{t('updated')}: {it['updated_at']}")
        st.markdown('</div>', unsafe_allow_html=True)
    for idx in reversed(trash): st.session_state["my_list"].pop(idx)

    st.divider()
    if st.session_state["user"]:
        if st.button(t("make_link"), use_container_width=True):
            u = st.session_state["user"]
            sid = save_to_db(
                share_id=None,
                owner_email=u["email"],
                owner_name=u["name"],
                title=share_title.strip() or ("내가 좋아하는 웹툰" if st.session_state["__lang"]=="ko" else "My favorite webtoons"),
                data_list=st.session_state["my_list"],
                is_public=pub,
            )
            base = GOOGLE.get("redirect_uri", "http://localhost:8501")
            share_url = f"{base}?share={sid}"
            st.success(t("create_share_success"))
            st.code(share_url)
    else:
        st.info(t("need_login"))

# =========================
# --- Share View (Read / Edit if owner/admin) + Like/View/Comments
# =========================
def page_share_view(share_id: str):
    data = load_share(share_id)
    if not data:
        st.error(t("not_found")); return

    add_view_once(share_id)

    st.subheader(f'{t("share")}: {data["title"]}')
    st.caption(f'{t("by")} {data.get("owner_name","?")} · {data.get("updated_at","")}')
    like_col, view_col, edit_col = st.columns([1,1,2])

    with like_col:
        lc = get_like_count(share_id)
        user = st.session_state.get("user")
        liked = user and has_liked(share_id, user.get("email"))
        label = f'❤️ {t("likes")} {lc}' if liked else f'🤍 {t("likes")} {lc}'
        if user and st.button(label, key="like_btn"):
            toggle_like(share_id, user.get("email")); st.rerun()
        elif not user:
            st.caption(f'🤍 {t("likes")} {lc}')
    with view_col:
        vc = get_view_count(share_id)
        st.caption(f'👁 {t("views")} {vc}')
    with edit_col:
        editable = can_edit_share(data)
        if editable:
            st.toggle(t("edit_mode"), key="__share_edit", value=bool(st.session_state.get("__share_edit")))
        else:
            st.caption("")

    st.divider()

    # 본문
    items = data["data"]
    changed = False
    for i, it in enumerate(items):
        st.markdown('<div class="item-card">', unsafe_allow_html=True)
        c1,c2,c3,c4 = st.columns([4,3,3,2])
        if st.session_state.get("__share_edit", False) and editable:
            new_title = st.text_input(t("title"), value=it.get("title",""), key=f"e_t_{i}")
            new_link  = st.text_input(t("link"), value=it.get("link",""), key=f"e_l_{i}", placeholder="https://...")
            new_note  = st.text_input(t("note"), value=it.get("note",""), key=f"e_n_{i}")
            if new_title != it.get("title") or new_link != it.get("link") or new_note != it.get("note"):
                items[i]["title"] = new_title
                items[i]["link"] = normalize_link(new_link)
                items[i]["note"] = new_note
                items[i]["updated_at"] = now_iso()
                changed = True
            with c4:
                if st.button("🗑", key=f"e_d_{i}"):
                    items.pop(i); changed = True; st.rerun()
        else:
            with c1:
                st.write(f"**{it.get('title','(No title)')}**")
                if it.get("note"): st.caption(it["note"])
            with c2:
                if it.get("link"): st.link_button(t("open"), it["link"])
                else: st.caption("—")
            with c3:
                thumb = fetch_og_thumb(it.get("link",""))
                if thumb: st.image(thumb, width=100, caption=t("preview"))
            with c4:
                st.caption(f'{t("updated")}: {it.get("updated_at","")}')
        st.markdown('</div>', unsafe_allow_html=True)

    if st.session_state.get("__share_edit", False) and editable:
        st.divider()
        new_title = st.text_input(t("share_title"), value=data["title"], key="__share_title_edit")
        new_public = st.toggle(t("public"), value=bool(data.get("is_public")), key="__share_public_edit")
        if st.button(t("save_changes")):
            sid = save_to_db(
                share_id=data["id"],
                owner_email=data["owner_email"],
                owner_name=data["owner_name"],
                title=new_title.strip() or data["title"],
                data_list=items,
                is_public=new_public
            )
            st.success("Saved!")
            st.experimental_set_query_params(share=sid)
            st.rerun()

    # 댓글
    st.divider()
    st.markdown(f"#### {t('comment')}")
    if st.session_state.get("user"):
        txt = st.text_input(t("add_comment"), key="__c_new", placeholder=t("placeholder_comment"))
        if st.button("➤", key="__c_send") and txt.strip():
            u = st.session_state["user"]
            add_comment(data["id"], u.get("email"), u.get("name"), txt.strip())
            st.rerun()
    else:
        st.info(t("need_login"))

    for cm in list_comments(data["id"], limit=100):
        st.markdown('<div class="item-card">', unsafe_allow_html=True)
        st.write(f"**{cm.get('name') or cm.get('email') or 'Guest'}** · {cm['created_at']}")
        st.write(cm["text"])
        st.markdown('</div>', unsafe_allow_html=True)

    # 내 목록 담기
    st.divider()
    if st.session_state["user"]:
        if st.button(t("copy_to_me"), use_container_width=True):
            exist = {x["title"] for x in st.session_state["my_list"]}
            for it in items:
                if it["title"] in exist: continue
                st.session_state["my_list"].append(norm_item({"title": it["title"], "link": it["link"], "note": it["note"]}))
            st.success("Imported!")
    else:
        st.info(t("need_login"))

# =========================
# --- Discover Page
# =========================
def page_discover():
    st.subheader(t("discover"))
    items = discover_public(limit=100)
    if not items:
        st.caption("—")
        return
    for it in items:
        st.markdown('<div class="item-card">', unsafe_allow_html=True)
        c1,c2 = st.columns([6,2])
        with c1:
            st.write(f"**{it['title']}**")
            st.caption(f"{t('by')} {it['owner_name']} · {it['updated_at']}")
        with c2:
            base = GOOGLE.get("redirect_uri", "http://localhost:8501")
            url = f"{base}?share={it['id']}"
            st.link_button(t("view"), url, use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)

# =========================
# --- Router
# =========================
# 전날 체크박스 초기화 같은 기능은 '요일 편성'이 없어서 생략.
# (필요하면 이전 코드와 결합 가능)

# Query param: share=...
params = st.experimental_get_query_params()
if "share" in params:
    page_share_view(params["share"][0])
else:
    tabs = st.tabs([f"📚 {t('my_list')}", f"🌏 {t('discover')}"])
    with tabs[0]:
        page_my_list()
    with tabs[1]:
        if time.time() - st.session_state["__discover_cache_at"] > 5:
            st.session_state["__discover_cache_at"] = time.time()
        page_discover()