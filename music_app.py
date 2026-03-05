import streamlit as st
import os
import psycopg2
import random
import hashlib
import re
from datetime import datetime
from psycopg2.extras import RealDictCursor

st.set_page_config(
    page_title="My Music Database",
    page_icon="🎧",
    initial_sidebar_state="expanded"
)

DATABASE_URL = os.getenv("DATABASE_URL")

@st.cache_resource
def get_connection():
    return psycopg2.connect(DATABASE_URL)

def db_execute(query, params=None, fetch=False):

    conn = get_connection()
    cur = conn.cursor()

    cur.execute(query, params or ())

    if fetch:
        result = cur.fetchall()
    else:
        conn.commit()
        result = None

    cur.close()

    return result

def parse_modulations(text):
    if not text:
        return []

    result = []
    parts = text.split(",")

    for p in parts:
        p = p.strip().replace("+", "")
        if p.lstrip("-").isdigit():
            result.append(int(p))

    return result

def row_to_music_dict(row):

    return {
        "id": row.get("id"),
        "username": row.get("username"),
        "title": row["title"],
        "artist": row["artist"],
        "genre": row["genre"],
        "themes": row["themes"].split(",") if row["themes"] else [],
        "rating": row["rating"],
        "comment": row["comment"],
        "date_added": row["date_added"],
        "key": row["key"],
        "bpm": row["bpm"],
        "vocal_min": row["vocal_min"],
        "vocal_max": row["vocal_max"],
        "modulations": parse_modulations(row["modulations"]),
        "chorus_key": row["chorus_key"],
        "chorus_chords_raw": row["chorus_chords_raw"],
        "chorus_chords_roman":
            row["chorus_chords_roman"].split(",")
            if row["chorus_chords_roman"] else []
    }

# ======================
# 🗄 PostgreSQL初期化
# ======================

def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS music (
        id SERIAL PRIMARY KEY,
        username TEXT,
        title TEXT,
        artist TEXT,
        genre TEXT,
        themes TEXT,
        rating INTEGER,
        comment TEXT,
        date_added TEXT,
        key TEXT,
        bpm TEXT,
        vocal_min TEXT,
        vocal_max TEXT,
        modulations TEXT,
        chorus_key TEXT,
        chorus_chords_raw TEXT,
        chorus_chords_roman TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password TEXT,
        is_public BOOLEAN DEFAULT TRUE
    )
    """)

    c.execute("""
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT TRUE
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS likes (
        id SERIAL PRIMARY KEY,
        song_id INTEGER,
        username TEXT,
        UNIQUE(song_id, username)
    )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_music_title ON music(title)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_music_artist ON music(artist)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_music_user ON music(username)")

    conn.commit()

init_db()

# ======================
# 🔐 ユーザー管理
# ======================

def load_users():
    rows = db_execute(
        "SELECT username, password FROM users",
        fetch=True
    )
    return {r[0]: r[1] for r in rows}

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


# ======================
# 🔐 マルチユーザーモード処理
# ======================

if "user" not in st.session_state:
    st.session_state.user = None

users = load_users()

# ---------- 未ログイン ----------
if st.session_state.user is None:

    st.title("🔐 ログイン / 新規登録")

    tab1, tab2 = st.tabs(["ログイン", "新規登録"])

    # ---- ログイン ----
    with tab1:
        login_user = st.text_input("ユーザー名")
        login_pass = st.text_input("パスワード", type="password")

        if st.button("ログイン"):
            if login_user in users:
                if users[login_user] == hash_password(login_pass):
                    st.session_state.user = login_user
                    if "music_data" in st.session_state:
                        del st.session_state.music_data
                    st.success("ログイン成功！")
                    st.rerun()
                else:
                    st.error("パスワードが違います")
            else:
                st.error("ユーザーが存在しません")

    # ---- 新規登録 ----
    with tab2:
        new_user = st.text_input("新しいユーザー名")
        new_pass = st.text_input("新しいパスワード", type="password")

        if st.button("登録"):
            if username and password:
                try:
                    db_execute(
                        """
                        INSERT INTO users (username, password)
                        VALUES (%s, %s)
                        ON CONFLICT (username) DO NOTHING
                        """,
                        (username, password)
                    )
        
                    # 登録できたか確認
                    result = db_execute(
                        "SELECT username FROM users WHERE username = %s",
                        (username,),
                        fetch=True
                    )
        
                    if result:
                        st.success("登録成功！")
                    else:
                        st.error("そのユーザー名は既に存在します")
        
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

    st.stop()

# ---------- ログイン後 ----------
st.sidebar.write(f"👤 {st.session_state.user}")

# ===== 公開設定 =====
row = db_execute(
    "SELECT is_public FROM users WHERE username = %s",
    (st.session_state.user,),
    fetch=True
)

current_public = row[0][0]

new_public = st.sidebar.checkbox("公開アカウントにする", value=current_public)

if new_public != current_public:
    db_execute(
        "UPDATE users SET is_public = %s WHERE username = %s",
        (new_public, st.session_state.user)
    )
    st.sidebar.success("公開設定を更新しました")

if st.sidebar.button("ログアウト"):
    st.session_state.user = None
    if "music_data" in st.session_state:
        del st.session_state.music_data
    st.rerun()



# ======================
# データ処理
# ======================
def load_music():
    conn = get_connection()
    c = conn.cursor(cursor_factory=RealDictCursor)

    c.execute("SELECT * FROM music WHERE username = %s", (st.session_state.user,))
    rows = c.fetchall()

    result = []
    for row in rows:
        result.append(row_to_music_dict(row))

    return result

def save_music(data):

    db_execute(
        "DELETE FROM music WHERE username = %s",
        (st.session_state.user,)
    )

    for m in data:

        db_execute("""
        INSERT INTO music (
            username,
            title, artist, genre, themes, rating, comment,
            date_added, key, bpm, vocal_min, vocal_max,
            modulations, chorus_key, chorus_chords_raw, chorus_chords_roman
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            st.session_state.user,
            m["title"],
            m["artist"],
            m["genre"],
            ",".join(m.get("themes", [])),
            m["rating"],
            m["comment"],
            m["date_added"],
            m["key"],
            m["bpm"],
            m["vocal_min"],
            m["vocal_max"],
            ",".join(map(str, m["modulations"])),
            m["chorus_key"],
            m["chorus_chords_raw"],
            ",".join(m["chorus_chords_roman"])
        ))

# ⭐ Streamlit用データ管理
if "music_data" not in st.session_state:
    st.session_state.music_data = load_music()

data = st.session_state.music_data

def load_public_music_all():
    conn = get_connection()
    c = conn.cursor(cursor_factory=RealDictCursor)

    c.execute("""
        SELECT m.*, COUNT(l.id) as like_count
        FROM music m
        JOIN users u ON m.username = u.username
        LEFT JOIN likes l ON m.id = l.song_id
        WHERE u.is_public = TRUE
        GROUP BY m.id
        ORDER BY m.title, m.artist, like_count DESC
    """, (st.session_state.user,))

    rows = c.fetchall()

    result = []

    for row in rows:
        music = row_to_music_dict(row)
        music["like_count"] = row["like_count"]
        result.append(music)

    return result

def load_public_music_grouped():
    public_songs = load_public_music_all()

    grouped = {}

    for song in public_songs:
        key = (song["title"], song["artist"])

        if key not in grouped:
            grouped[key] = []

        grouped[key].append(song)

    # いいね順に並び替え
    for key in grouped:
        grouped[key] = sorted(
            grouped[key],
            key=lambda x: x["like_count"],
            reverse=True
        )

    return grouped

def group_versions_remove_duplicates(versions):
    """
    theme / rating / date_added を除いた
    全フィールドが同じものを1つにまとめる
    """

    unique_map = {}

    for v in versions:

        # 🔥 比較対象キー（除外3項目）
        compare_key = (
            v.get("title"),
            v.get("artist"),
            v.get("genre"),
            v.get("comment"),
            v.get("key"),
            v.get("bpm"),
            v.get("vocal_min"),
            v.get("vocal_max"),
            tuple(sorted(v.get("modulations", []))),
            v.get("chorus_key"),
            v.get("chorus_chords_raw"),
            tuple(v.get("chorus_chords_roman", [])),
        )

        if compare_key not in unique_map:
            unique_map[compare_key] = {
                "data": v,
                "like_count": v["like_count"],
                "count": 1
            }
        else:
            unique_map[compare_key]["like_count"] += v["like_count"]
            unique_map[compare_key]["count"] += 1

    result = sorted(
        unique_map.values(),
        key=lambda x: x["count"],
        reverse=True
    )

    return result

# ======================
# ⭐ キャッシュ（大量データ高速化）
# ======================

@st.cache_data
def get_all_artists(data):
    return sorted(set(m["artist"] for m in data))

@st.cache_data
def get_all_genres(data):
    return sorted(set(m["genre"] for m in data if m.get("genre")))

@st.cache_data
def get_year_dict(data):
    year_dict = {}

    for m in data:
        date = m.get("date_added", "")
        year = date.split("-")[0] if date else "不明"

        if year not in year_dict:
            year_dict[year] = []
        year_dict[year].append(m)

    return year_dict

@st.cache_data
def search_public_music(artist_query="", title_query="", limit=50):

    conn = get_connection()
    c = conn.cursor(cursor_factory=RealDictCursor)

    query = """
        SELECT m.*, COUNT(l.id) as like_count
        FROM music m
        JOIN users u ON m.username = u.username
        LEFT JOIN likes l ON m.id = l.song_id
        WHERE u.is_public = TRUE
    """

    params = []

    if artist_query:
        query += " AND m.artist ILIKE %s"
        params.append(f"%{artist_query}%")

    if title_query:
        query += " AND m.title ILIKE %s"
        params.append(f"%{title_query}%")

    query += """
        GROUP BY m.id
        LIMIT %s
    """

    params.append(limit)

    c.execute(query, tuple(params))
    rows = c.fetchall()

    result = []

    for row in rows:
        music = row_to_music_dict(row)
        music["like_count"] = row["like_count"]
        result.append(music)

    return result



def save_and_refresh():
    save_music(data)
    st.session_state.music_data = data

    # ⭐ キャッシュ削除（超重要）
    st.cache_data.clear()

    st.rerun()

def is_duplicate_song(title, artist):
    title = title.strip().lower()
    artist = artist.strip().lower()

    for m in data:
        if m["title"].strip().lower() == title and m["artist"].strip().lower() == artist:
            return True
    return False

def find_my_song(title, artist):
    title = title.strip().lower()
    artist = artist.strip().lower()

    for i, m in enumerate(data):
        if m["title"].strip().lower() == title and m["artist"].strip().lower() == artist:
            return i
    return None


def has_missing_info(my_song, public_song):
    """
    自分の曲に不足していて、
    公開曲にはある情報があるか判定
    """

    fields = [
        "key", "bpm", "vocal_min", "vocal_max",
        "chorus_key", "chorus_chords_raw"
    ]

    for f in fields:
        if (not my_song.get(f)) and public_song.get(f):
            return True

    # 転調
    if not my_song.get("modulations") and public_song.get("modulations"):
        return True

    # ローマ数字
    if not my_song.get("chorus_chords_roman") and public_song.get("chorus_chords_roman"):
        return True

    return False

def classify_public_song(public_song):

    my_index = find_my_song(public_song["title"], public_song["artist"])

    if my_index is None:
        return "none"

    my_song = data[my_index]

    # 🔥 代表バージョン取得
    best_version = public_song

    if best_version is None:
        return "full"

    if has_missing_info(my_song, best_version):
        return "partial"

    return "full"

def compare_field(label, field, public_song, my_song, my_index):

    pub_val = public_song.get(field)
    my_val = my_song.get(field)

    col1, col2, col3 = st.columns([3,1,3])

    with col1:
        st.write(f"🌍 {label}: {pub_val if pub_val else '-'}")

    with col3:
        st.write(f"👤 現在: {my_val if my_val else '-'}")

    # 値が違う場合のみボタン表示
    if (pub_val or "") != (my_val or ""):

        with col2:
            if st.button("上書き", key=f"replace_{field}_{my_index}"):

                data[my_index][field] = pub_val
                st.session_state.msg = f"{label} を更新しました"
                save_and_refresh()

def compare_list_field(label, field, public_song, my_song, my_index, is_mod=False):

    pub_val = public_song.get(field) or []
    my_val = my_song.get(field) or []

    # 🔥 ここ重要：必ずリスト化保証
    if not isinstance(pub_val, list):
        pub_val = []
    if not isinstance(my_val, list):
        my_val = []

    # 転調は順序無視
    if is_mod:
        pub_val = sorted(pub_val)
        my_val = sorted(my_val)

    col1, col2, col3 = st.columns([3,1,3])

    with col1:
        st.write(f"🌍 {label}: {', '.join(map(str,pub_val)) if pub_val else '-'}")

    with col3:
        st.write(f"👤 現在: {', '.join(map(str,my_val)) if my_val else '-'}")

    # 完全一致なら何もしない
    if pub_val == my_val:
        return

    with col2:
        if st.button("上書き", key=f"replace_{field}_{my_index}"):

            data[my_index][field] = pub_val
            st.session_state.msg = f"{label} を更新しました"
            save_and_refresh()


# ======================
# 代表曲を決める関数              
# ======================
def get_best_public_version_from_versions(versions):
    if not versions:
        return None
    return max(versions, key=lambda x: x["like_count"])

# ======================
# 🎤 音名 → 数値変換（音域検索用）
# ======================
NOTE_MAP = {
    "C":0, "C#":1, "Db":1,
    "D":2, "D#":3, "Eb":3,
    "E":4,
    "F":5, "F#":6, "Gb":6,
    "G":7, "G#":8, "Ab":8,
    "A":9, "A#":10, "Bb":10,
    "B":11
}



# ======================
# 🎹 Keyバリデーション（複数・♯♭対応版）
# ======================

def is_valid_single_key(k):
    """
    例：
    C
    Cm
    F#
    Bb
    G#m
    E♭m
    などを許可
    """
    k = k.strip().replace("♯", "#").replace("♭", "b")

    pattern = r"^[A-G](#|b)?m?$"
    return re.match(pattern, k) is not None


def is_valid_key(key_str):
    """
    C, G, Am
    C → D → E♭m
    C, Dm, F#
    など複数入力OK
    """
    if not key_str.strip():
        return True

    # 区切り対応（→ , スペース）
    parts = re.split(r"[,\s→]+", key_str)

    for p in parts:
        if p.strip() == "":
            continue
        if not is_valid_single_key(p):
            return False

    return True

def note_to_midi(note):
    """
    C4 → 60 みたいな数値に変換
    変換できなければ None
    """
    if not note:
        return None

    note = note.strip().replace("♯","#").replace("♭","b")

    # 例：C#4 → 音名=C# オクターブ=4
    name = note[:-1]
    octave = note[-1]

    if name not in NOTE_MAP or not octave.isdigit():
        return None

    return NOTE_MAP[name] + (int(octave)+1)*12

# ==========================
# 🎼 実コード → ローマ数字変換
# ==========================

DEGREE_MAP = {
    0:"I", 1:"♭II", 2:"II", 3:"♭III",
    4:"III", 5:"IV", 6:"#IV",
    7:"V", 8:"♭VI", 9:"VI",
    10:"♭VII", 11:"VII"
}

def parse_chord(chord):
    chord = chord.strip().replace("♯","#").replace("♭","b")

    root = chord[0]
    if len(chord) >= 2 and chord[1] in ["#", "b"]:
        root = chord[:2]
        rest = chord[2:]
    else:
        rest = chord[1:]

    # コードタイプ判定
    if rest.startswith("dim"):
        ctype = "dim"
    elif rest.startswith("aug"):
        ctype = "aug"
    elif rest.startswith("m") and not rest.startswith("maj"):
        ctype = "m"
    else:
        ctype = "maj"

    return root, ctype


def chord_to_degree(chord, key):
    if not chord or not key:
        return ""

    root, ctype = parse_chord(chord)
    
    if root not in NOTE_MAP or key not in NOTE_MAP:
        return chord

    interval = (NOTE_MAP[root] - NOTE_MAP[key]) % 12
    degree = DEGREE_MAP[interval]

    if ctype == "dim":
        degree = degree + "°"
    elif ctype == "aug":
        degree = degree + "+"


    return degree


def convert_progression(raw_text, key):
    """
    "F G G#dim Am" → ['IV','V','#V°','vi']
    """
    if not raw_text.strip() or not key:
        return []
    
    chords = raw_text.replace(",", " ").split()
    result = []

    for c in chords:
        deg = chord_to_degree(c, key)
        if deg:
            result.append(deg)

    return result


def progression_to_text(prog):
    if not prog:
        return ""
    return " → ".join(prog)

# 🎼 転調を12半音に正規化（NEW）
def normalize_mod(mod):
    return mod % 12

def roman_match(song_prog, query_prog):
    """
    曲の進行に、検索進行が順番通り含まれるか
    例：
    曲   [IV,V,iii,vi]
    検索 [V,vi] → True
    """
    if not song_prog:
        return False

    if not query_prog:
        return True

    i = 0
    for chord in song_prog:
        if chord == query_prog[i]:
            i += 1
            if i == len(query_prog):
                return True
    return False

def validate_song_input(
    title, artist, key,
    bpm, vocal_min, vocal_max,
    modulation_input, date_added
):

    errors = []

    # ======================
    # 必須チェック
    # ======================
    if not title.strip():
        errors.append("曲名は必須です")

    if not artist.strip():
        errors.append("アーティスト名は必須です")

    # ======================
    # BPMチェック
    # ======================
    if bpm.strip():
        if not bpm.isdigit():
            errors.append("BPMは数字で入力してください")
        else:
            bpm_val = int(bpm)
            if bpm_val < 1 or bpm_val > 300:
                errors.append("BPMは1〜300の範囲で入力してください")

    # ======================
    # Keyチェック
    # ======================
    if key.strip():
        if not is_valid_key(key):
            errors.append("Keyは A〜G + #/♭ + m 形式で入力してください（例：C, F#m, Bb）")

    # ======================
    # 音域チェック
    # ======================
    if vocal_min:
        if note_to_midi(vocal_min) is None:
            errors.append("最低音の形式が正しくありません（例：C3）")

    if vocal_max:
        if note_to_midi(vocal_max) is None:
            errors.append("最高音の形式が正しくありません（例：A4）")

    if vocal_min and vocal_max:
        min_midi = note_to_midi(vocal_min)
        max_midi = note_to_midi(vocal_max)
        if min_midi and max_midi and min_midi > max_midi:
            errors.append("最低音が最高音より高くなっています")

    # ======================
    # 転調チェック
    # ======================
    if modulation_input.strip():
        parts = modulation_input.split(",")
        for p in parts:
            p = p.strip().replace("+", "")
            if not p.lstrip("-").isdigit():
                errors.append("転調は半音数字で入力してください（例：+2, -3）")
                break

    # ======================
    # 日付チェック
    # ======================
    if date_added.strip():
        try:
            datetime.strptime(date_added, "%Y-%m-%d")
        except:
            errors.append("日付は YYYY-MM-DD 形式で入力してください")

    return errors
    

# ======================
# 🎹 ローマ数字キーボード（2段＋拡張）
# ======================
def roman_keyboard(session_key):
    if session_key not in st.session_state:
        st.session_state[session_key] = ""

    # ---------- 基本操作 ----------
    def add_degree(deg):
        if st.session_state[session_key] == "":
            st.session_state[session_key] = deg
        else:
            st.session_state[session_key] += " " + deg

    def add_suffix(suffix):
        parts = st.session_state[session_key].split()
        if len(parts) == 0:
            return
        parts[-1] = parts[-1] + suffix
        st.session_state[session_key] = " ".join(parts)

    def add_space():
        st.session_state[session_key] += " "

    def delete_last():
        parts = st.session_state[session_key].split()
        st.session_state[session_key] = " ".join(parts[:-1])

    def clear_all():
        st.session_state[session_key] = ""

    st.caption("🎹 クリック入力")

    # ===== 1段目 =====
    row1 = ["I","♭II","II","♭III","III","IV","#IV","V"]
    cols = st.columns(len(row1))
    for i,b in enumerate(row1):
        if cols[i].button(b, key=f"{session_key}_r1_{b}"):
            add_degree(b)

    # ===== 2段目 =====
    row2 = ["#V","♭VI","VI","♭VII","VII","°","+"]
    cols = st.columns(len(row2))
    for i,b in enumerate(row2):
        if b == "°":
            if cols[i].button("°", key=f"{session_key}_dim"):
                add_suffix("°")
        elif b == "+":
            if cols[i].button("＋", key=f"{session_key}_aug"):
                add_suffix("+")
        else:
            if cols[i].button(b, key=f"{session_key}_r2_{b}"):
                add_degree(b)

    # ===== 操作キー =====
    col1, col2, col3 = st.columns(3)

    if col1.button("space", key=f"{session_key}_space"):
        add_space()

    if col2.button("delete", key=f"{session_key}_delete"):
        delete_last()

    if col3.button("clear", key=f"{session_key}_clear"):
        clear_all()
#==================
# いいね数取得
#==================
def get_like_count(song_id):

    result = db_execute(
        "SELECT COUNT(*) FROM likes WHERE song_id = %s",
        (song_id,),
        fetch=True
    )

    return result[0][0]

#==================
# いいね切り替え
#==================
def toggle_like(song_id):

    exists = db_execute(
        """
        SELECT 1 FROM likes
        WHERE song_id = %s AND username = %s
        """,
        (song_id, st.session_state.user),
        fetch=True
    )

    if exists:
        db_execute(
            """
            DELETE FROM likes
            WHERE song_id = %s AND username = %s
            """,
            (song_id, st.session_state.user)
        )
    else:
        db_execute(
            """
            INSERT INTO likes (song_id, username)
            VALUES (%s, %s)
            """,
            (song_id, st.session_state.user)
        )

# ======================
# ⭐ 通知メッセージ管理（追加）
# ======================
def show_message():
    if "msg" in st.session_state:
        st.success(st.session_state.msg)
        del st.session_state.msg

# ======================
# 共通UI
# ======================
def show_music_card(music, index):
    st.subheader(f"🎵 {music['title']}")
    st.write(f"**Artist:** {music['artist']}")
    st.write(f"**Genre:** {music['genre']}")
    # ⭐ これを追加
    if music.get("themes"):
        st.write("🏷 Themes:", ", ".join(music["themes"]))

    # ⭐ 新情報表示（未入力なら表示しない）
    
    # 🎼 転調情報（NEW）
    mods = music.get("modulations", [])

    if len(mods) > 0:
        mod_text = ", ".join([f"{'+' if m>0 else ''}{m}" for m in mods])
        st.write(f"🔁 転調: {mod_text}")


    roman = music.get("chorus_chords_roman", [])
    raw = music.get("chorus_chords_raw", "")

    if music.get("chorus_key"):
        st.write(f"🎼 サビKey: {music['chorus_key']}")

    if roman:
        st.write("🎹 サビ進行:", progression_to_text(roman))


    if raw:
        st.write("🎸 実コード:", raw)



    
    if music.get("key"):
        st.write(f"🎹 Key: {music['key']}")
    if music.get("bpm"):
        st.write(f"⏱ BPM: {music['bpm']}")
    if music.get("date_added"):
        st.write(f"❤️ 好きになった日: {music['date_added']}")
    if music.get("vocal_min") or music.get("vocal_max"):
        st.write(f"🎤 Vocal Range: {music.get('vocal_min','?')} ～ {music.get('vocal_max','?')}")




    st.write("★" * int(music["rating"]))
    st.write(music["comment"])

    col1, col2 = st.columns(2)

    if col1.button("✏ 編集", key=f"edit{index}"):
        st.session_state.edit_index = index
        st.rerun()

    if col2.button("🗑 削除", key=f"del{index}"):

        # ⭐ 詳細ページからの削除対策（超重要）
        if "detail_index" in st.session_state:
            del st.session_state.detail_index

        if "edit_index" in st.session_state:
            del st.session_state.edit_index

        data.pop(index)
        st.session_state.msg = "削除しました！"
        save_and_refresh()

# ======================
# 🌍 公開曲カード表示
# ======================
def show_public_song_card(title, artist, versions):

    # 🔥 重複削除
    grouped_versions = group_versions_remove_duplicates(versions)

    # 🔥 公開1位（like合算後の1位）
    best_version = grouped_versions[0]["data"] if grouped_versions else None

    with st.expander(
        f"🎵 {title} - {artist}（{len(grouped_versions)} Version）",
        expanded=False
    ):

        # ==========================
        # 👤 自分の登録状況表示
        # ==========================
        if best_version:
            show_my_status_in_card(title, artist, best_version)

        # ==========================
        # 🥇 横並び比較（復活）
        # ==========================
        if best_version:
            show_side_by_side_compare(title, artist, best_version)
        
        # ==========================
        # Version一覧
        # ==========================
        with st.expander("別バージョン", expanded=False):
            for i, item in enumerate(grouped_versions, start=1):
    
                v = item["data"]
                total_like = item["like_count"]
                same_count = item["count"]
    
                col1, col2 = st.columns([4,1])
    
                if st.button(
                    f"Version {i}（{same_count}人登録）",
                    key=f"pub_ver_{title}_{artist}_{i}"
                ):
                    st.session_state.public_detail_data = v
                    st.rerun()

                
# ======================
# 👤 自分の登録状況表示
# ======================
def show_my_status_in_card(title, artist, best_version):

    my_index = find_my_song(title, artist)

    if my_index is None:
        st.info("👤 あなたはまだこの曲を登録していません")
    
        if st.button("📥 この公開曲を自分の曲として登録する",
                     key=f"copy_public_{title}_{artist}"):
    
            new_song = {
                "title": best_version["title"],
                "artist": best_version["artist"],
                "genre": best_version.get("genre"),
                "themes": best_version.get("themes", []),
                "rating": 0,  # 初期値（好き度は仮に3）
                "comment": "",
                "date_added": datetime.now().strftime("%Y-%m-%d"),
                "key": best_version.get("key"),
                "bpm": best_version.get("bpm"),
                "vocal_min": best_version.get("vocal_min"),
                "vocal_max": best_version.get("vocal_max"),
                "modulations": best_version.get("modulations", []),
                "chorus_key": best_version.get("chorus_key"),
                "chorus_chords_raw": best_version.get("chorus_chords_raw"),
                "chorus_chords_roman": best_version.get("chorus_chords_roman", []),
            }
    
            data.append(new_song)
    
            st.session_state.msg = "公開曲を自分のデータに登録しました！"
            save_and_refresh()
    
        return

    my_song = data[my_index]

    if has_missing_info(my_song, best_version):
        st.warning("🟡 あなたの曲は一部情報が不足しています")
    else:
        st.success("🟢 あなたはこの曲を登録済みです")

    if st.button("👤 自分の曲を見る", key=f"my_jump_{title}_{artist}"):
        st.session_state.prev_menu = "🌍 公開曲を見る"
        st.session_state.detail_index = my_index
        st.rerun()

# ======================
# 🥇 公開1位 vs 自分 横並び比較
# ======================
def show_side_by_side_compare(title, artist, best_version):

    my_index = find_my_song(title, artist)

    if my_index is None:
        return

    my_song = data[my_index]

    st.divider()
    st.markdown("### 🥇 公開1位 vs 👤 あなた")

    # ===== 単一フィールド =====
    compare_field("Key", "key", best_version, my_song, my_index)
    compare_field("BPM", "bpm", best_version, my_song, my_index)
    compare_field("最低音", "vocal_min", best_version, my_song, my_index)
    compare_field("最高音", "vocal_max", best_version, my_song, my_index)
    compare_field("サビKey", "chorus_key", best_version, my_song, my_index)
    compare_field("実コード", "chorus_chords_raw", best_version, my_song, my_index)

    # ===== リスト系 =====
    compare_list_field(
        "転調",
        "modulations",
        best_version,
        my_song,
        my_index,
        is_mod=True
    )

    compare_list_field(
        "ローマ数字",
        "chorus_chords_roman",
        best_version,
        my_song,
        my_index
    )

    # ===== 一括追加 =====
    if has_missing_info(my_song, best_version):

        st.divider()

        if st.button("📥 不足分を一括追加する", key=f"bulk_add_{title}_{artist}"):

            fields = [
                "key", "bpm", "vocal_min", "vocal_max",
                "chorus_key",
                "chorus_chords_raw",
                "chorus_chords_roman",
                "modulations"
            ]

            for f in fields:
                if not my_song.get(f) and best_version.get(f):
                    data[my_index][f] = best_version.get(f)

            st.session_state.msg = "不足分を一括追加しました！"
            save_and_refresh()

    # ===== 完全上書き =====
    st.divider()

    if st.button("🔥 公開1位で完全上書きする", key=f"bulk_replace_{title}_{artist}"):

        fields = [
            "key", "bpm", "vocal_min", "vocal_max",
            "chorus_key",
            "chorus_chords_raw",
            "chorus_chords_roman",
            "modulations"
        ]

        for f in fields:
            data[my_index][f] = best_version.get(f)

        st.session_state.msg = "公開1位の内容で完全上書きしました！"
        save_and_refresh()

def edit_form(music, index):
    st.header("✏ 曲を編集")

    # ======================
    # 必須項目
    # ======================
    st.subheader("必須項目")

    title = st.text_input("曲名 *", music["title"])
    artist = st.text_input("アーティスト *", music["artist"])
    rating = st.slider("お気に入り度 *", 0, 5, int(music["rating"]))

    # ======================
    # ⭐ 折りたたみ詳細入力
    # ======================
    with st.expander("▼ 詳細入力（任意）", expanded=False):

        genre_input = st.text_input("ジャンル", music.get("genre") or "")

        # themesを文字列に変換
        themes_str = ", ".join(music.get("themes", []))
        themes_input = st.text_input("テーマ(カンマ区切り)", themes_str)

        key = st.text_input("Key", music.get("key", ""))
        bpm = st.text_input("BPM", music.get("bpm", ""))

        st.write("🎤 ボーカル音域")
        vocal_min = st.text_input("最低音", music.get("vocal_min", ""))
        vocal_max = st.text_input("最高音", music.get("vocal_max", ""))

        st.divider()
        st.subheader("🎼 楽曲分析")

        # 既存データ → 文字列化
        mods_str = ", ".join(
            [f"{'+' if m>0 else ''}{m}" for m in music.get("modulations", [])]
        )

        modulation_input = st.text_input(
            "🔁 転調（例：+2, -3, +5）",
            mods_str
        )

        chorus_key = st.text_input(
            "サビのキー（ローマ数字変換用）＊マイナーキー未対応",
            music.get("chorus_key", "")
        )

        

        raw_chords_str = music.get("chorus_chords_raw", "")

        chorus_chords_raw = st.text_input(
            "実コード進行（例：F G E Am）",
            raw_chords_str
        )
                





        date_added = st.text_input(
            "好きになった日 (YYYY-MM-DD)",
            music.get("date_added", datetime.now().strftime("%Y-%m-%d"))
        )

        comment = st.text_area("コメント", music.get("comment", ""))

    # ======================
    # 保存ボタン
    # ======================
    if st.button("保存"):

        # 必須チェック
        errors = validate_song_input(
            title, artist, key,
            bpm, vocal_min, vocal_max,
            modulation_input,
            date_added
        )
        
        if errors:
            for e in errors:
                st.error(e)
            st.stop()

        raw = chorus_chords_raw.strip()
        roman = convert_progression(raw, chorus_key)

        # 更新処理
        data[index] = {
            "title": title,
            "artist": artist,
            "genre": genre_input.strip() if genre_input.strip() else None,
            "themes": [t.strip() for t in themes_input.split(",") if t.strip()],
            "rating": rating,
            "comment": comment,
            "date_added": date_added,
            "key": key,
            "bpm": bpm,
            "vocal_min": vocal_min,
            "vocal_max": vocal_max,
            "modulations": parse_modulations(modulation_input),
            "chorus_key": chorus_key,
            "chorus_chords_raw": raw,
            "chorus_chords_roman": roman,
        }


        del st.session_state.edit_index
        st.session_state.msg = "更新しました！"
        save_and_refresh()


# ======================
# ⭐ 曲詳細ページ（NEW）
# ======================
def show_detail_page(index):
    # ⭐⭐ 追加：存在しないindex対策（超重要）
    if index >= len(data):
        # detail_indexが残っていたら削除
        if "detail_index" in st.session_state:
            del st.session_state.detail_index

        # 安全な画面へ移動
        jump_to_menu("🏠 ホーム")
        return
    # ⭐⭐ ここまで追加

    music = data[index]

    st.header("🎧 曲詳細")
    show_music_card(music, index)

    if st.button("← 戻る"):
        if "prev_menu" in st.session_state:
            prev = st.session_state.prev_menu
            request_restore(prev)
            del st.session_state.prev_menu

            del st.session_state.detail_index   # ← 先に削除！！
            jump_to_menu(prev)                  # ← rerunはこれだけ

# ======================
# 🌍 公開曲詳細ページ
# ======================
def show_public_detail_page(_):

    target = st.session_state.get("public_detail_data")

    if target is None:
        jump_to_menu("🌍 公開曲を見る")
        return

    st.header("🌍 公開曲詳細")

    st.subheader(f"🎵 {target['title']}")
    st.write(f"🎤 アーティスト: {target['artist']}")

    # ===== 全情報表示（除外3項目） =====

    if target.get("genre"):
        st.write("🎼 Genre:", target["genre"])

    if target.get("themes"):
        st.write("🏷 Themes:", ", ".join(target["themes"]))

    if target.get("key"):
        st.write("🎹 Key:", target["key"])

    if target.get("bpm"):
        st.write("⏱ BPM:", target["bpm"])

    if target.get("vocal_min") or target.get("vocal_max"):
        st.write(
            "🎤 Vocal Range:",
            f"{target.get('vocal_min','?')} ～ {target.get('vocal_max','?')}"
        )

    mods = target.get("modulations") or []

    if isinstance(mods, list) and len(mods) > 0:
        mod_text = ", ".join(
            [f"{'+' if int(m)>0 else ''}{int(m)}" for m in mods]
        )
        st.write("🔁 転調:", mod_text)

    if target.get("chorus_key"):
        st.write("🎼 サビKey:", target["chorus_key"])

    if target.get("chorus_chords_roman"):
        st.write(
            "🎹 サビ進行:",
            progression_to_text(target["chorus_chords_roman"])
        )

    if target.get("chorus_chords_raw"):
        st.write("🎸 実コード:", target["chorus_chords_raw"])

    if target.get("comment"):
        st.write("💬 コメント:", target["comment"])

    st.divider()

    # ======================
    # 👤 自分の曲と比較
    # ======================
    
    my_index = find_my_song(target["title"], target["artist"])

    if my_index is None:

        st.subheader("💾 この曲を保存")
    
        if st.button("📥 このVersionを自分の曲として保存"):
    
            new_song = {
                "title": target["title"],
                "artist": target["artist"],
                "genre": target.get("genre"),
                "themes": target.get("themes"),
                "rating": 0,  # 初期値（好き度は仮に0）
                "date_added": datetime.now().strftime("%Y-%m-%d"),
                "key": target.get("key"),
                "bpm": target.get("bpm"),
                "vocal_min": target.get("vocal_min"),
                "vocal_max": target.get("vocal_max"),
                "modulations": target.get("modulations"),
                "chorus_key": target.get("chorus_key"),
                "chorus_chords_raw": target.get("chorus_chords_raw"),
                "chorus_chords_roman": target.get("chorus_chords_roman"),
                "comment": "",
            }
    
            data.append(new_song)
    
            st.session_state.msg = "曲を保存しました！"
            save_and_refresh()
    
    if my_index is not None:
    
        my_song = data[my_index]
    
        st.subheader("👤 あなたの登録曲と比較")
    
        fields = [
            ("Genre","genre"),
            ("Themes","themes"),
            ("Key","key"),
            ("BPM","bpm"),
            ("最低音","vocal_min"),
            ("最高音","vocal_max"),
            ("サビKey","chorus_key"),
            ("実コード","chorus_chords_raw"),
            ("ローマ数字","chorus_chords_roman"),
            ("転調","modulations"),
        ]
    
        for label, field in fields:
    
            col1, col2, col3 = st.columns([2,2,1])
    
            public_val = target.get(field)
            my_val = my_song.get(field)
    
            if isinstance(public_val, list):
                public_val = ", ".join(map(str, public_val))
            if isinstance(my_val, list):
                my_val = ", ".join(map(str, my_val))
    
            with col1:
                st.write(f"**{label}**")
    
            with col2:
                st.write(f"公開: {public_val}")
                st.write(f"自分: {my_val}")
    
            with col3:
                if public_val and public_val != my_val:
                    if st.button("上書き", key=f"overwrite_{field}"):
    
                        data[my_index][field] = target.get(field)
    
                        st.session_state.msg = f"{label}を上書きしました"
                        save_and_refresh()

        if has_missing_info(my_song, target):
    
            if st.button("📥 このVersionの不足分を追加"):
        
                fields = [
                    "genre","themes","key","bpm",
                    "vocal_min","vocal_max",
                    "chorus_key",
                    "chorus_chords_raw",
                    "chorus_chords_roman",
                    "modulations"
                ]
        
                for f in fields:
                    if not my_song.get(f) and target.get(f):
                        data[my_index][f] = target.get(f)
        
                st.session_state.msg = "不足分を追加しました"
                save_and_refresh()
    
        if st.button("🔥 このVersionで完全上書き"):
    
            fields = [
                "genre","themes","key","bpm",
                "vocal_min","vocal_max",
                "chorus_key",
                "chorus_chords_raw",
                "chorus_chords_roman",
                "modulations"
            ]
        
            for f in fields:
                data[my_index][f] = target.get(f)
        
            st.session_state.msg = "このVersionで完全上書きしました"
            save_and_refresh()
        
        if st.button("← 戻る"):
            del st.session_state.public_detail_data
            jump_to_menu("🌍 公開曲を見る")

# ======================
# ⭐ メニュー遷移システム（超重要）
# ======================
def jump_to_menu(menu_name):
    st.session_state.next_menu = menu_name
    st.rerun()


# ======================
# ⭐ 画面状態保存（超重要）
# ======================
def save_search_state():
    st.session_state.search_state = {
        "keyword": st.session_state.get("search_keyword", ""),
        "key_filter": st.session_state.get("search_key", ""),
        "genre_filter": st.session_state.get("search_genre", ""),   # ⭐追加
        "theme_filter": st.session_state.get("search_theme", ""),   # ⭐追加
        "bpm_min": st.session_state.get("search_bpm_min", 0),
        "bpm_max": st.session_state.get("search_bpm_max", 300),
        "vocal_mode": st.session_state.get("search_vocal_mode", "歌える曲検索"),
        "vocal_min": st.session_state.get("search_vocal_min", ""),
        "vocal_max": st.session_state.get("search_vocal_max", ""),
        "mod_mode": st.session_state.get("search_mod_mode", "指定なし"),
        "mod_value": st.session_state.get("search_mod_value", ""),
        "roman_query": st.session_state.get("search_roman", ""),
    }


def restore_search_state():
    if "search_state" in st.session_state:
        s = st.session_state.search_state
        st.session_state.search_keyword = s["keyword"]
        st.session_state.search_key = s["key_filter"]
        st.session_state.search_genre = s.get("genre_filter", "")   # ⭐追加
        st.session_state.search_theme = s.get("theme_filter", "")   # ⭐追加
        st.session_state.search_bpm_min = s["bpm_min"]
        st.session_state.search_bpm_max = s["bpm_max"]
        st.session_state.search_vocal_mode = s.get("vocal_mode", "歌える曲検索")
        st.session_state.search_vocal_min = s.get("vocal_min", "")
        st.session_state.search_vocal_max = s.get("vocal_max", "")
        st.session_state.search_mod_mode = s.get("mod_mode", "指定なし")
        st.session_state.search_mod_value = s.get("mod_value", "")
        st.session_state.search_roman = s.get("roman_query", "")





def save_artist_state():
    st.session_state.artist_state = {
        "artist": st.session_state.get("artist_select", "")
    }

def restore_artist_state():
    if "artist_state" in st.session_state:
        st.session_state.artist_select = st.session_state.artist_state["artist"]

def save_genre_state():
    st.session_state.genre_state = {
        "genre": st.session_state.get("genre_select", "")
    }

def restore_genre_state():
    if "genre_state" in st.session_state:
        st.session_state.genre_select = st.session_state.genre_state["genre"]


# ⭐ 復元フラグ管理
def request_restore(page):
    st.session_state.restore_page = page

def should_restore(page):
    return st.session_state.get("restore_page") == page

def done_restore():
    if "restore_page" in st.session_state:
        del st.session_state.restore_page

# ======================
# 画面
# ======================
st.title("🎧 My Music Database")

show_message()   # ← これを追加！！


# ⭐ 予約されたmenuジャンプがあれば先に反映
if "next_menu" in st.session_state:
    st.session_state.menu = st.session_state.next_menu
    del st.session_state.next_menu


menu = st.sidebar.selectbox(
    "メニュー",
    ["🏠 ホーム", "曲追加", "アーティスト一覧", "ジャンル一覧", "検索", "年別まとめ", "🌍 公開曲を見る"],
    key="menu"
)

# ======================
# ⭐ 画面分岐（最重要）
# ======================

# ① 編集画面が最優先
if "edit_index" in st.session_state:
    edit_form(data[st.session_state.edit_index], st.session_state.edit_index)

    if st.button("← 戻る"):
        del st.session_state.edit_index
        st.rerun()

    st.stop()


# ② 詳細画面
if "detail_index" in st.session_state:
    show_detail_page(st.session_state.detail_index)
    st.stop()

# 🌍 公開曲詳細画面
if "public_detail_data" in st.session_state:
    show_public_detail_page(None)
    st.stop()

# ======================
# 🏠 ホーム
# ======================
if menu == "🏠 ホーム":
    st.header("🎧 My Music Dashboard")

    if len(data) == 0:
        st.info("まだ曲が登録されていません")
        st.stop()

    # ===== 統計 =====
    col1, col2, col3 = st.columns(3)

    col1.metric("登録曲数", len(data))
    col2.metric("アーティスト数", len(set(m["artist"] for m in data)))
    col3.metric("ジャンル数", len(set(m["genre"] for m in data if m["genre"])))

    st.divider()

    # ===== 最近追加した曲 =====
    st.subheader("🆕 最近追加した曲")

    sorted_by_date = sorted(
        data,
        key=lambda x: x.get("date_added",""),
        reverse=True
    )

    for m in sorted_by_date[:5]:
        index = data.index(m)
        if st.button(f"🎵 {m['title']} - {m['artist']} {'★'*int(m['rating'])}", key=f"home_{index}"):
            st.session_state.prev_menu = st.session_state.menu
            st.session_state.detail_index = index
            st.rerun()

    st.divider()

    # ===== 高評価曲 =====
    st.subheader("⭐ お気に入りトップ")

    favs = sorted(data, key=lambda x: x["rating"], reverse=True)[:5]

    for m in favs:
        index = data.index(m)
        if st.button(f"⭐ {m['title']} - {m['artist']} {'★'*int(m['rating'])}", key=f"fav_{index}"):
            st.session_state.prev_menu = st.session_state.menu
            st.session_state.detail_index = index
            st.rerun()

    
    st.divider()

    # ======================
    # 🎲 ランダム再発見（統合版）
    # ======================
    st.subheader("🎲 ランダム再発見")

    if "random_pick" not in st.session_state:
        st.session_state.random_pick = None

    col1, col2 = st.columns([1,3])

    if col1.button("🎲 選ぶ"):
        st.session_state.random_pick = random.choice(data)

    if st.session_state.random_pick:
        m = st.session_state.random_pick
        st.markdown(f"### 🎵 {m['title']}")
        st.write(f"**Artist:** {m['artist']}")
        st.write("★" * int(m["rating"]))

        if m.get("comment"):
            st.write(m["comment"])

        if st.button("詳細を見る"):
            index = data.index(m)
            st.session_state.prev_menu = st.session_state.menu
            st.session_state.detail_index = index
            st.rerun()
    

# ======================
# 曲追加（改良版）
# ======================
if menu == "曲追加":
    st.header("🎧 曲を追加")

    st.subheader("必須項目")

    title = st.text_input("曲名 *")
    artist = st.text_input("アーティスト *")
    rating = st.slider("お気に入り度 *", 0, 5)

    # ⭐ 折りたたみ詳細入力
    with st.expander("▼ 詳細入力（任意）"):
        genre_input = st.text_input("ジャンル")
        themes_input = st.text_input("テーマ(カンマ区切り)")
        
        key = st.text_input("Key（例:Cm, F#）")
        bpm = st.text_input("BPM")

        st.write("🎤 ボーカル音域")
        vocal_min = st.text_input("最低音（例：C3）")
        vocal_max = st.text_input("最高音（例：A4）")

        st.divider()
        st.subheader("🎼 楽曲分析")

        st.write("🔁 転調（複数可）")
        modulation_input = st.text_input(
            "例：+2, -3, +5",
            help="半音単位で入力。カンマ区切り"
        )

        chorus_key = st.text_input(
            "サビのキー（ローマ数字変換用）",
            help="ここに入力したキーでコード進行をディグリーネーム変換します"
        )

        chorus_chords_raw = st.text_input(
            "実コード進行（例：F G E Am）",
            help="スペース区切りでOK"
        )


        comment = st.text_area("コメント")


    # ======================
    # 追加ボタン
    # ======================
    if st.button("追加"):

        # 必須チェック
        errors = validate_song_input(
            title, artist, key,
            bpm, vocal_min, vocal_max,
            modulation_input,
            datetime.now().strftime("%Y-%m-%d")
        )
        
        if errors:
            for e in errors:
                st.error(e)
            st.stop()

        # 重複チェック
        if is_duplicate_song(title, artist):
            st.error("この曲は既に登録されています！")
            st.stop()

        raw = chorus_chords_raw.strip()
        roman = convert_progression(raw, chorus_key)

        # 登録データ作成
        new_music = {
            "title": title,
            "artist": artist,
            "genre": genre_input.strip() if genre_input.strip() else None,
            "themes": [t.strip() for t in themes_input.split(",") if t.strip()],
            "rating": rating,
            "comment": comment,
            "date_added": datetime.now().strftime("%Y-%m-%d"),
            "key": key,
            "bpm": bpm,
            "vocal_min": vocal_min,
            "vocal_max": vocal_max,
            "modulations": parse_modulations(modulation_input),
            "chorus_key": chorus_key,
            "chorus_chords_raw": raw,
            "chorus_chords_roman": roman,
        }


        data.append(new_music)
        st.session_state.msg = "追加しました！"
        save_and_refresh()



# ======================
# アーティスト一覧
# ======================
elif menu == "アーティスト一覧":
    if should_restore("アーティスト一覧"):
        restore_artist_state()
        done_restore()

    st.header("🎤 アーティスト一覧")

    if len(data) == 0:
        st.info("曲がまだありません")
        st.stop()

    artists = get_all_artists(data)
    selected_artist = st.selectbox("アーティスト選択", artists, key="artist_select")


    artist_songs = [m for m in data if m["artist"] == selected_artist]

    for m in artist_songs:
        index = data.index(m)
        if st.button(f"🎵 {m['title']} {'★'*int(m['rating'])}", key=f"artist_{index}"):
            save_artist_state()   # ⭐追加
            st.session_state.prev_menu = st.session_state.menu
            st.session_state.detail_index = index
            st.rerun()

# ======================
# ジャンル一覧（NEW）
# ======================
elif menu == "ジャンル一覧":
    if should_restore("ジャンル一覧"):
        restore_genre_state()
        done_restore()

    st.header("🎼 ジャンル一覧")

    if len(data) == 0:
        st.info("曲がまだありません")
        st.stop()

    # 空ジャンル除外 + 重複削除
    genres = get_all_genres(data)


    if len(genres) == 0:
        st.info("ジャンルが登録されていません")
        st.stop()

    selected_genre = st.selectbox("ジャンル選択", genres, key="genre_select")

    genre_songs = [m for m in data if m["genre"] == selected_genre]

    st.write(f"🎧 {len(genre_songs)} 曲")

    for m in genre_songs:
        index = data.index(m)
        if st.button(f"🎵 {m['title']} {'★'*int(m['rating'])}", key=f"genre_{index}"):

            save_genre_state()  # ⭐状態保存
            st.session_state.prev_menu = st.session_state.menu
            st.session_state.detail_index = index
            st.rerun()


# ======================
# 検索（強化版）
# ======================
elif menu == "検索":
    if should_restore("検索"):
        restore_search_state()
        done_restore()

    # ⭐ 初回だけ検索初期値セット（ここ追加！！）
    if "search_bpm_min" not in st.session_state:
        st.session_state.search_bpm_min = 0
    if "search_bpm_max" not in st.session_state:
        st.session_state.search_bpm_max = 300
    if "search_keyword" not in st.session_state:
        st.session_state.search_keyword = ""
    if "search_key" not in st.session_state:
        st.session_state.search_key = ""
    if "search_genre" not in st.session_state:
        st.session_state.search_genre = ""
    if "search_theme" not in st.session_state:
        st.session_state.search_theme = ""
    if "search_rating" not in st.session_state:
        st.session_state.search_rating = 0
    if "search_vocal_mode" not in st.session_state:
        st.session_state.search_vocal_mode = "歌える曲検索"
    if "search_vocal_min" not in st.session_state:
        st.session_state.search_vocal_min = ""
    if "search_vocal_max" not in st.session_state:
        st.session_state.search_vocal_max = ""
    if "search_mod_mode" not in st.session_state:
        st.session_state.search_mod_mode = "指定なし"
    if "search_mod_value" not in st.session_state:
        st.session_state.search_mod_value = ""
    if "search_roman" not in st.session_state:
        st.session_state.search_roman = ""




    # ======================
    # 🔎 タイトル + 並び替え横並び
    # ======================
    col_title, col_sort = st.columns([3,2])

    with col_title:
        st.header("🔎 曲検索")

    with col_sort:
        sort_option = st.selectbox(
            "並び替え",
            [
                "新しい順",
                "星評価順",
                "ボーカル最高音順",
                "楽曲名50音順",
                "アーティスト名50音順"
            ],
            key="search_sort",
            label_visibility="collapsed"  # ← ラベル非表示でコンパクト化
        )


    st.subheader("キーワード検索")
    keyword = st.text_input("曲名 or アーティスト", key="search_keyword")

    st.subheader("🎛 フィルター")

    # ==============================
    # 🎛 折りたたみフィルター
    # ==============================
    genre_filter = st.session_state.search_genre
    theme_filter = st.session_state.search_theme
    rating_min = st.session_state.search_rating
    key_filter = st.session_state.search_key
    bpm_min = st.session_state.search_bpm_min
    bpm_max = st.session_state.search_bpm_max
    vocal_mode = st.session_state.search_vocal_mode
    vocal_min_filter = st.session_state.search_vocal_min
    vocal_max_filter = st.session_state.search_vocal_max


    with st.expander("🎛 詳細フィルター", expanded=False):

        # =====================================================
        # 🟦 タグ・評価
        # =====================================================
        with st.expander("🏷 タグ・評価", expanded=False):

            col1, col2, col3 = st.columns(3)

            with col1:
                genre_filter = st.text_input("🎼 ジャンル", key="search_genre")

            with col2:
                theme_filter = st.text_input("🏷 テーマ", key="search_theme")

            with col3:
                rating_min = st.slider("⭐ 評価以上", 0, 5, key="search_rating")

        # =====================================================
        # 🟩 楽曲情報
        # =====================================================
        with st.expander("🎵 楽曲情報", expanded=False):

            col1, col2 = st.columns(2)

            with col1:
                key_filter = st.text_input("🎹 Key", key="search_key")

            with col2:
                st.write("⏱ BPM")
                bpm_min = st.number_input("最小", 0, 300, key="search_bpm_min")
                bpm_max = st.number_input("最大", 0, 300, key="search_bpm_max")

        # =====================================================
        # 🟥 ボーカル音域
        # =====================================================
        with st.expander("🎤 ボーカル音域", expanded=False):

            vocal_mode = st.radio(
                "音域検索モード",
                ["歌える曲検索", "音域一致検索"],
                horizontal=True,
                key="search_vocal_mode"
            )

            col1, col2 = st.columns(2)

            with col1:
                vocal_min_filter = st.text_input("最低音", key="search_vocal_min")

            with col2:
                vocal_max_filter = st.text_input("最高音", key="search_vocal_max")

        # =====================================================
        # 🔁 転調フィルター（NEW）
        # =====================================================
        with st.expander("🔁 転調", expanded=False):

            mod_mode = st.radio(
                "転調フィルター",
                ["指定なし", "転調あり", "転調なし"],
                horizontal=True,
                key="search_mod_mode"
            )

            mod_value = st.text_input(
                "含む転調量（例：+2, -3）",
                key="search_mod_value",
                help="その転調を含む曲だけ表示"
            )

        # =====================================================
        # 🎹 ローマ数字進行検索（NEW）
        # =====================================================
        with st.expander("🎹 サビ進行（ローマ数字）", expanded=False):

            st.caption("クリック or 手入力どちらでもOK")

            roman_keyboard("search_roman")

            roman_query = st.text_input(
                "含む進行",
                key="search_roman"
            )



    # ---------- 検索処理 ----------
    results = []

    for m in data:

        # キーワード検索
        if keyword:
            if keyword.lower() not in m["title"].lower() and keyword.lower() not in m["artist"].lower():
                continue

        # Key検索
        if key_filter:
            if key_filter.lower() not in m.get("key", "").lower():
                continue

        # Genre検索 ⭐追加
        if genre_filter:
            if genre_filter.lower() not in m.get("genre", "").lower():
                continue

        # Theme検索 ⭐追加（配列対応）
        if theme_filter:
            themes = [t.lower() for t in m.get("themes", [])]

            # どれにも一致しなければ除外
            if not any(theme_filter.lower() in t for t in themes):
                continue


        # BPM範囲検索（修正版）
        bpm_value = m.get("bpm", "")

        # BPMフィルターが使われているか判定
        bpm_filter_used = (bpm_min > 0 or bpm_max < 300)

        if bpm_filter_used:
            # BPM未入力は除外
            if not bpm_value.isdigit():
                continue

            bpm_value = int(bpm_value)

            if bpm_value < bpm_min or bpm_value > bpm_max:
                continue

        # 🎤 音域検索（完全版）
        if vocal_min_filter or vocal_max_filter:

            song_min = note_to_midi(m.get("vocal_min"))
            song_max = note_to_midi(m.get("vocal_max"))

            if song_min is None or song_max is None:
                continue

            filter_min = note_to_midi(vocal_min_filter)
            filter_max = note_to_midi(vocal_max_filter)

            # =====================================
            # 🎤 モード① 歌える曲検索（←本当の意味）
            # 自分の声域に収まる曲
            # =====================================
            if vocal_mode == "歌える曲検索":

                # 最低音チェック
                if filter_min is not None and song_min < filter_min:
                    continue

                # 最高音チェック
                if filter_max is not None and song_max > filter_max:
                    continue

            # =====================================
            # 🎤 モード② 音域一致検索（NEW）
            # 最低音・最高音の完全一致
            # =====================================
            else:

                # 最低音一致（入力されている場合のみ）
                if filter_min is not None and song_min != filter_min:
                    continue

                # 最高音一致（入力されている場合のみ）
                if filter_max is not None and song_max != filter_max:
                    continue

        # =====================================
        # 🔁 転調フィルター（NEW）
        # =====================================
        mods = m.get("modulations", [])

        # --- 転調あり/なし ---
        if mod_mode == "転調あり" and len(mods) == 0:
            continue

        if mod_mode == "転調なし" and len(mods) > 0:
            continue

        # --- 転調量指定（12半音同値対応版） ---
        if mod_value.strip():

            target_mods = parse_modulations(mod_value)

            # 検索側を正規化
            target_mods_norm = [normalize_mod(t) for t in target_mods]

            # 曲側を正規化
            song_mods_norm = [normalize_mod(m) for m in mods]

            # 1つも一致しなければ除外
            if not any(t in song_mods_norm for t in target_mods_norm):
                continue
    
        # ⭐ 評価フィルター追加
        if m["rating"] < rating_min:
            continue

        # =====================================
        # 🎹 ローマ数字進行検索（NEW）
        # =====================================
        if roman_query.strip():

            query_prog = roman_query.replace(",", " ").split()
            song_prog = m.get("chorus_chords_roman", [])

            if not roman_match(song_prog, query_prog):
                continue


        results.append(m)

    # ======================
    # ⭐ 並び替え処理
    # ======================

    def vocal_high_note(song):
        return note_to_midi(song.get("vocal_max")) or -1

    if sort_option == "新しい順":
        results = sorted(results, key=lambda x: x.get("date_added",""), reverse=True)

    elif sort_option == "星評価順":
        results = sorted(results, key=lambda x: x["rating"], reverse=True)

    elif sort_option == "ボーカル最高音順":
        results = sorted(results, key=vocal_high_note, reverse=True)

    elif sort_option == "楽曲名50音順":
        results = sorted(results, key=lambda x: x["title"])

    elif sort_option == "アーティスト名50音順":
        results = sorted(results, key=lambda x: x["artist"])


    # ---------- 表示 ----------
    st.divider()

    if len(results) == 0:
        st.info("該当する曲がありません")
    else:
        st.write(f"{len(results)} 件ヒット")

        for m in results:
            index = data.index(m)
            if st.button(f"🏆 {m['title']} - {m['artist']} {'★'*int(m['rating'])}", key=f"rank_{index}"):
                save_search_state()  # ⭐追加！！
                st.session_state.prev_menu = st.session_state.menu
                st.session_state.detail_index = index
                st.rerun()


# ======================
# 年別まとめ
# ======================
elif menu == "年別まとめ":
    st.header("📅 好きになった年まとめ")

    if len(data) == 0:
        st.info("曲がまだありません")
        st.stop()

    
    # ⭐ キャッシュ版を使用
    year_dict = get_year_dict(data)

    # 年の新しい順に表示
    for year in sorted(year_dict.keys(), reverse=True):
        st.subheader(f"📅 {year}年")

        songs = year_dict[year]
        for m in songs:
            index = data.index(m)
            if st.button(f"🎵 {m['title']} - {m['artist']} {'★'*int(m['rating'])}", key=f"year_{year}_{index}"):
                st.session_state.prev_menu = st.session_state.menu
                st.session_state.detail_index = index
                st.rerun()

        st.divider()





elif menu == "🌍 公開曲を見る":

    st.header("🌍 公開曲検索")

    # -----------------------------
    # 初期化
    # -----------------------------
    if "public_search_result" not in st.session_state:
        st.session_state.public_search_result = []

    if "public_search_done" not in st.session_state:
        st.session_state.public_search_done = False

    if "public_artist_query" not in st.session_state:
        st.session_state.public_artist_query = ""

    if "public_title_query" not in st.session_state:
        st.session_state.public_title_query = ""


    # -----------------------------
    # 入力欄（保存付き）
    # -----------------------------
    artist_query = st.text_input(
        "アーティスト名",
        value=st.session_state.public_artist_query
    )

    title_query = st.text_input(
        "曲名",
        value=st.session_state.public_title_query
    )


    # -----------------------------
    # 検索ボタン
    # -----------------------------
    if st.button("🔍 検索"):

        st.session_state.public_artist_query = artist_query
        st.session_state.public_title_query = title_query

        results = search_public_music(
            artist_query=artist_query,
            title_query=title_query,
            limit=50
        )

        st.session_state.public_search_result = results
        st.session_state.public_search_done = True


    # -----------------------------
    # 未検索
    # -----------------------------
    if not st.session_state.public_search_done:
        st.info("検索ボタンを押してください")


    results = st.session_state.public_search_result

    if not results:
        st.warning("該当曲なし")
        st.stop()


    # -----------------------------
    # グループ化
    # -----------------------------
    grouped = {}

    for row in results:
        key = (row["title"], row["artist"])
        grouped.setdefault(key, []).append(row)

    for (title, artist), versions in grouped.items():
        show_public_song_card(title, artist, versions)
            
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8501))

    st.write("")  # 何もしない（Render用ダミー）


















