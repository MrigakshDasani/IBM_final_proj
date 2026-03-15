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

def reset_database():
    try:
        connection = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        
        with connection.cursor() as cursor:
            print("Dropping existing tables to apply new schema...")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("DROP TABLE IF EXISTS plate_records;")
            cursor.execute("DROP TABLE IF EXISTS users;")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
            print("Tables dropped successfully.")
            
        connection.commit()
        connection.close()
    except Exception as e:
        print(f"Error resetting database: {e}")

if __name__ == "__main__":
    reset_database()
