from playwright.sync_api import sync_playwright
import json
import sqlite3
import os


DB_PATH       = "/chats/chat_insta.db"
USER_DATA_DIR = "./insta_profile"
STATUS_PATH   = "/credentials/status.json"
INBOX_URL     = "https://instagram.com/direct/inbox"


def verify():
    st = False
    with open(STATUS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
        if data.get("platform") == "Instagram" and data.get("status") == "logged":
            st = True
    return st


def find_all(target=10):
    # -------- config --------
    MAX_SCROLLS   = 15
    SCROLL_PIXELS = 1000
    SCROLL_WAIT   = 1000
    IDLE_WAIT     = 1500

    names = []

    # -------- browser + scrape --------
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
        )
        try:
            page = context.new_page()
            page.goto(INBOX_URL, wait_until="domcontentloaded")

            try:
                page.locator('button:has-text("Not Now")').click(timeout=5000)
            except Exception:
                pass

            page.wait_for_selector('span[title]', timeout=30_000)
            page.locator('span[title]').first.hover()

            # Helper for collecting — nested so we don't repeat ourselves
            seen = set()

            def collect():
                for span in page.locator('span[title]').all():
                    t = span.get_attribute('title')
                    if t and t.strip() and t.strip() not in seen:
                        seen.add(t.strip())
                        names.append(t.strip())

            collect()
            print(f"[find_all] initially visible: {len(names)}")

            scrolls = 0
            while len(names) < target and scrolls < MAX_SCROLLS:
                page.mouse.wheel(0, SCROLL_PIXELS)
                page.wait_for_timeout(SCROLL_WAIT)

                before = len(names)
                collect()
                scrolls += 1
                print(f"[find_all] scroll {scrolls}: {len(names)} names")

                if len(names) == before:
                    page.wait_for_timeout(IDLE_WAIT)
                    collect()
                    if len(names) == before:
                        print("[find_all] no new names, stopping.")
                        break

            names = names[:target]

        finally:
            context.close()
    # <- sync_playwright() closes here

    # -------- save to DB --------
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute('''
            CREATE TABLE IF NOT EXISTS people(
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        ''')
        con.executemany(
            "INSERT OR IGNORE INTO people(name) VALUES (?)",
            [(n,) for n in names]
        )
        con.commit()
    finally:
        con.close()

    print(f"[find_all] saved {len(names)} names: {names}")
    return names


def prepare_person_tables():
    """
    Read names from `people`, and create a `chat_<name>` table for each.
    Does NOT launch a browser. Call this AFTER find_all().
    """
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS people(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        ''')
        con.commit()

        cur.execute("SELECT name FROM people")
        rows = cur.fetchall()

        for (name,) in rows:
            safe_name  = name.replace(" ", "_").replace("-", "_")
            table_name = f"chat_{safe_name}"
            cur.execute(f'''
                CREATE TABLE IF NOT EXISTS "{table_name}" (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_time    TEXT,
                    sender_date    TEXT,
                    sender_content TEXT,
                    user_time      TEXT,
                    user_date      TEXT,
                    user_content   TEXT
                )
            ''')
        con.commit()
        print(f"[prepare_person_tables] ensured {len(rows)} tables.")
    finally:
        con.close()


def open_insta(target=10):
    """
    High-level flow: scrape names, then ensure per-person tables.
    Does NOT open its own browser — find_all() owns the browser.
    """
    if not verify():
        raise RuntimeError("Not logged in. Run login('inst') first.")

    find_all(target)
    prepare_person_tables()


