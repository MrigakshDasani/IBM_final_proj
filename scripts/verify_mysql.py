import os
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).resolve().parent.parent / "backend"
sys.path.append(str(backend_path))

from app import create_app
from models import db, User

def verify():
    print("Attempting to verify MySQL connection and table creation...")
    app = create_app()
    with app.app_context():
        try:
            # Check if User table exists and we can query it
            user_count = User.query.count()
            print(f"Connection successful! User count: {user_count}")
            print("Tables verified.")
        except Exception as e:
            print(f"Verification failed: {e}")
            sys.exit(1)

if __name__ == "__main__":
    verify()
