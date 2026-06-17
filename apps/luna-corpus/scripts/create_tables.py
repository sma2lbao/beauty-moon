"""Script to create database tables."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load .env file
load_dotenv(project_root / ".env")

from app.db.database import engine
from app.db.models import Base


def create_tables():
    """Create all database tables."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")


def drop_tables():
    """Drop all database tables (use with caution!)."""
    confirm = input("Are you sure you want to drop all tables? Type 'yes' to confirm: ")
    if confirm.lower() == "yes":
        print("Dropping database tables...")
        Base.metadata.drop_all(bind=engine)
        print("Tables dropped successfully!")
    else:
        print("Cancelled.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Database table management")
    parser.add_argument(
        "action",
        choices=["create", "drop"],
        help="Action to perform",
    )
    args = parser.parse_args()

    if args.action == "create":
        create_tables()
    elif args.action == "drop":
        drop_tables()
