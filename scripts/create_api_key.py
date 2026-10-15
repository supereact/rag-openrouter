"""Trusted local operator CLI for creating tenant-scoped accounts and API keys.

Example: python -m scripts.create_api_key --tenant local --user admin --role admin
Only run on a trusted development machine. Never commit or share generated keys.
"""
import argparse
import re
from app.db import db_connection
from app.security import generate_api_key, key_digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--role", choices=("admin", "editor", "reader"), required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,49}", args.tenant):
        parser.error("tenant must be 2-50 lowercase letters, numbers, - or _")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,79}", args.user):
        parser.error("user must be 2-80 alphanumeric/._- characters")
    secret = generate_api_key()
    with db_connection() as conn:
        conn.execute("INSERT INTO tenants(slug) VALUES (%s) ON CONFLICT DO NOTHING", (args.tenant,))
        tenant_id = conn.execute("SELECT id FROM tenants WHERE slug=%s", (args.tenant,)).fetchone()[0]
        conn.execute("""INSERT INTO app_users(tenant_id, username, role)
             VALUES (%s, %s, %s) ON CONFLICT (tenant_id, username) DO NOTHING""",
             (tenant_id, args.user, args.role),
        )
        row = conn.execute("""SELECT id, role FROM app_users
            WHERE tenant_id=%s AND username=%s""", (tenant_id, args.user)).fetchone()
        if row[1] != args.role:
            raise ValueError("Existing user role differs; refusing to modify permissions")
        conn.execute("INSERT INTO api_keys(user_id,key_hash) VALUES (%s,%s)",
                     (row[0], key_digest(secret)))
    print(f"Created key for {args.tenant}/{args.user} ({args.role}).")
    print("Save this key now; only its hash is in PostgreSQL:\n" + secret)


if __name__ == "__main__":
    main()
