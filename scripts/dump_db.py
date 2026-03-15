import sqlite3
import os

db_path = "instance/anpr_dev.db"
if not os.path.exists(db_path):
    print(f"Error: {db_path} not found.")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("--- TABLES ---")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
for t in tables:
    print(f"Table: {t[0]}")

for t in ["users", "plate_records"]:
    print(f"\n--- DATA FROM {t} ---")
    try:
        cursor.execute(f"SELECT * FROM {t}")
        rows = cursor.fetchall()
        # Get column names
        names = [description[0] for description in cursor.description]
        print(" | ".join(names))
        for r in rows:
            print(" | ".join(map(str, r)))
    except Exception as e:
        print(f"Error reading {t}: {e}")

conn.close()
