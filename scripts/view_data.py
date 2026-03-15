import pymysql
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env
root = Path(__file__).resolve().parent.parent
load_dotenv(root / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "anpr_db")

def view_data():
    try:
        connection = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            cursorclass=pymysql.cursors.DictCursor
        )
        
        with connection.cursor() as cursor:
            # 1. View Users
            print("\n" + "="*50)
            print(" REGISTERED USERS ".center(50, "="))
            print("="*50)
            cursor.execute("SELECT id, username, email, role, is_active FROM users")
            users = cursor.fetchall()
            if not users:
                print("No users found.")
            for u in users:
                print(f"ID: {u['id']} | {u['username']} ({u['role']}) | {u['email']}")

            # 2. View Plate Records (with JOIN)
            print("\n" + "="*50)
            print(" RECENT PLATE DETECTIONS (JOINed with Users) ".center(50, "="))
            print("="*50)
            query = """
                SELECT p.timestamp, p.plate_text, p.yolo_confidence, u.username, u.email
                FROM plate_records p
                JOIN users u ON p.user_email = u.email
                ORDER BY p.timestamp DESC
                LIMIT 20
            """
            cursor.execute(query)
            records = cursor.fetchall()
            if not records:
                print("No plate records found.")
            for r in records:
                print(f"[{r['timestamp']}] {r['plate_text']} | User: {r['username']} ({r['email']})")
            
        connection.close()
    except Exception as e:
        print(f"Error connecting to MySQL: {e}")

if __name__ == "__main__":
    view_data()
