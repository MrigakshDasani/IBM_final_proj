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

def setup_database():
    try:
        # Connect without database to create it
        connection = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD
        )
        
        with connection.cursor() as cursor:
            # Create database if not exists
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
            print(f"Database '{DB_NAME}' created or already exists.")
            
        connection.close()
    except Exception as e:
        print(f"Error creating database: {e}")

if __name__ == "__main__":
    setup_database()
