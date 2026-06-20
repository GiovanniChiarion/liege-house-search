#!/usr/bin/env python3
"""
CLI tool to manage users for Liège House Search.

Usage:
    python add_user.py add <email> <password> [name]
    python add_user.py list
    python add_user.py delete <email>
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import get_db, register_user


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]

    if command == 'add':
        if len(sys.argv) < 4:
            print("Usage: python add_user.py add <email> <password> [name]")
            return
        email = sys.argv[2]
        password = sys.argv[3]
        name = sys.argv[4] if len(sys.argv) > 4 else ''
        
        user_id = register_user(email, password, name)
        if user_id:
            print(f"✅ User created: {email} (ID: {user_id})")
        else:
            print(f"❌ Email already exists: {email}")

    elif command == 'list':
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id, email, name, created_at FROM users ORDER BY id")
        users = cursor.fetchall()
        db.close()
        
        if not users:
            print("No users found.")
            return
        
        print(f"Users ({len(users)}):")
        print(f"{'ID':<4} {'Email':<30} {'Name':<20} {'Created'}")
        print("-" * 70)
        for u in users:
            print(f"{u['id']:<4} {u['email']:<30} {u['name'] or '-':<20} {u['created_at'][:10]}")

    elif command == 'delete':
        if len(sys.argv) < 3:
            print("Usage: python add_user.py delete <email>")
            return
        email = sys.argv[2]
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM users WHERE email = ?", (email,))
        if cursor.rowcount > 0:
            db.commit()
            print(f"✅ User deleted: {email}")
        else:
            print(f"❌ User not found: {email}")
        db.close()

    elif command == 'changepw':
        if len(sys.argv) < 4:
            print("Usage: python add_user.py changepw <email> <new_password>")
            return
        email = sys.argv[2]
        password = sys.argv[3]
        from werkzeug.security import generate_password_hash
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE users SET password_hash = ? WHERE email = ?",
                      (generate_password_hash(password), email))
        if cursor.rowcount > 0:
            db.commit()
            print(f"✅ Password changed for: {email}")
        else:
            print(f"❌ User not found: {email}")
        db.close()

    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == '__main__':
    main()
