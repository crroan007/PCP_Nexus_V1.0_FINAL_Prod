import sqlite3
import os

DB_PATH = r'C:\ProgramData\PCP-Automation\data\nexus.db'

def clear_database():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM jobs")
        conn.commit()
        print("Database 'jobs' table cleared successfully.")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    clear_database()
