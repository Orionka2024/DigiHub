import json
import os
import argparse
import getpass
import hashlib
import secrets

def hash_password(password: str) -> str:
    """Create a pbkdf2_hmac password hash (format: salt:hash)"""
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}:{key.hex()}"

USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)
    print(f"Saved {len(users)} users to {USERS_FILE}")

def main():
    parser = argparse.ArgumentParser(description="Manage KVK_v2 Allowed Users")
    parser.add_argument("action", choices=["add", "list", "remove", "export"], help="Action to perform")
    parser.add_argument("--username", help="Username to add/remove")
    args = parser.parse_args()

    users = load_users()

    if args.action == "list":
        print(f"Current users ({len(users)}):")
        for u in users.keys():
            print(f"- {u}")
            
    elif args.action == "add":
        username = args.username or input("Enter username: ")
        password = getpass.getpass(f"Enter password for {username}: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match!")
            return
            
        users[username] = hash_password(password)
        save_users(users)
        print(f"User {username} added/updated successfully.")
        
    elif args.action == "remove":
        username = args.username or input("Enter username to remove: ")
        if username in users:
            del users[username]
            save_users(users)
            print(f"User {username} removed.")
        else:
            print(f"User {username} not found.")
            
    elif args.action == "export":
        # Export as ALLOWED_USERS env var string
        if not users:
            print("No users found.")
            return
        
        env_string = ",".join([f"{u}:{pwd}" for u, pwd in users.items()])
        print("\nSet this as your ALLOWED_USERS environment variable in Vercel:\n")
        print(f"ALLOWED_USERS='{env_string}'\n")

if __name__ == "__main__":
    main()
