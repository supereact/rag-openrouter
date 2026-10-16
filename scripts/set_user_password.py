"""Trusted, interactive operator command to set password on an existing user.

Example: python -m scripts.set_user_password --tenant local --user admin --email admin@example.com
Use a real address you control. Never put passwords in shell arguments or .env.
"""
import argparse
from getpass import getpass

from app.account_auth import hash_password, normalize_email
from app.db import db_connection


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--tenant', required=True)
    p.add_argument('--user', required=True)
    p.add_argument('--email', required=True)
    args = p.parse_args()
    email = normalize_email(args.email)
    password = getpass('New password (12–128 characters): ')
    if password != getpass('Confirm password: '):
        p.error('Passwords do not match')
    password_hash = hash_password(password)
    with db_connection() as conn:
        row = conn.execute('''SELECT u.id FROM app_users u
            JOIN tenants t ON t.id=u.tenant_id WHERE t.slug=%s AND u.username=%s''',
            (args.tenant,args.user)).fetchone()
        if not row:
            p.error('User not found')
        conn.execute('UPDATE app_users SET email=%s,password_hash=%s WHERE id=%s',
                     (email,password_hash,row[0]))
        conn.execute('UPDATE login_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL', (row[0],))
    print('Password configured. Existing API keys remain valid.')


if __name__ == '__main__':
    main()
