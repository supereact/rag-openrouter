"""Run a command against explicit Neon config without loading the local .env.

Example: python -m scripts.run_neon -- python -m uvicorn app.main:app --port 8011
Migrations: add --direct before --. The child never inherits a local DB URL.
"""
import argparse
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dotenv import dotenv_values


def environment(path: Path, *, direct: bool = False) -> dict[str, str]:
    if not path.is_file():
        raise ValueError('Pull Neon configuration into the separate .env.neon file first')
    values = {key: value for key, value in dotenv_values(path, interpolate=False).items()
              if value is not None}
    key = 'DATABASE_URL_UNPOOLED' if direct else 'DATABASE_URL'
    value = values.get(key, '')
    try:
        url = urlsplit(value)
        valid = (url.scheme in ('postgres', 'postgresql') and url.hostname
                 and url.hostname.endswith('.neon.tech') and url.username
                 and url.password and url.path not in ('', '/')
                 and parse_qs(url.query).get('sslmode', [''])[0]
                     in ('require', 'verify-ca', 'verify-full'))
        url.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f'{key} must be an explicit TLS Neon database URL')
    if direct and '-pooler.' in url.hostname:
        raise ValueError('Migrations require the direct Neon connection, not the pooler')
    result = {**os.environ, **values}
    result.update(DATABASE_URL=value, RAG_ENV_FILE=str(path.resolve()),
                  RAG_STORAGE_BACKEND='s3')
    # Use the file's region/credentials, never accidental local AWS credentials.
    for name in ('AWS_ENDPOINT_URL_S3', 'AWS_REGION', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'):
        if not values.get(name):
            raise ValueError('The selected Neon file is missing object-storage configuration')
        result[name] = values[name]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path('.env.neon'))
    parser.add_argument('--direct', action='store_true')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('Specify a command after --')
    try:
        child = environment(args.env_file, direct=args.direct)
    except ValueError as exc:
        parser.error(str(exc))
    os.execvpe(command[0], command, child)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
