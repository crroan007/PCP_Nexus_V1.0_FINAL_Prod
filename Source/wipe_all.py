"""Nuclear wipe — clears ALL data for clean test. Preserves config.json."""
import sqlite3, os, shutil

base = "C:/ProgramData/PCP-Automation"
db = os.path.join(base, "pcp_automation.db")

# 1. Wipe DB tables
conn = sqlite3.connect(db)
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
for t in [r[0] for r in cur.fetchall()]:
    cur.execute("DELETE FROM " + t)
    print("  DB:", t, "wiped")
conn.commit()
conn.close()

# 2. Clear dirs (preserve config.json and db)
skip = {"pcp_automation.db", "config.json"}
for f in os.listdir(base):
    if f in skip:
        continue
    fp = os.path.join(base, f)
    if os.path.isfile(fp):
        os.remove(fp)
        print("  Removed:", f)
    elif os.path.isdir(fp):
        for sub in os.listdir(fp):
            sp = os.path.join(fp, sub)
            try:
                if os.path.isfile(sp): os.remove(sp)
                elif os.path.isdir(sp): shutil.rmtree(sp)
            except Exception:
                pass
        print("  Cleared:", f + "/")

# 3. Output
out = os.path.expanduser("~/Documents/Output")
if os.path.isdir(out):
    c = 0
    for f in os.listdir(out):
        try:
            os.remove(os.path.join(out, f))
            c += 1
        except Exception:
            pass
    print("  Output:", c, "removed")

print("=== CLEAN SLATE (config preserved) ===")
