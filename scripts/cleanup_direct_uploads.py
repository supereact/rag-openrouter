"""Dry-run by default: remove expired incoming objects, never accepted worker input."""
import argparse
from datetime import datetime, timedelta, timezone
import re

from app import object_storage


def cleanup(*, older_than_hours: int = 24, apply: bool = False) -> dict:
    if not object_storage.enabled():
        raise ValueError('Select the explicit Neon environment first')
    if older_than_hours < 1:
        raise ValueError('Require at least one hour, beyond the upload ticket lifetime')
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    options = dict(Bucket=object_storage.bucket('upload'), Prefix='incoming/', MaxKeys=1000)
    expired = deleted = 0
    while True:
        page = object_storage.call('list_objects_v2', **options)
        for entry in page.get('Contents', []):
            if (not re.fullmatch(r'incoming/[0-9a-f]{32}\.upload', entry['Key'])
                    or entry['LastModified'] >= cutoff):
                continue
            expired += 1
            if apply:
                object_storage.call('delete_object', Bucket=options['Bucket'], Key=entry['Key'])
                deleted += 1
        if not page.get('IsTruncated'):
            break
        token = page.get('NextContinuationToken')
        if not token or token == options.get('ContinuationToken'):
            raise RuntimeError('Storage listing did not advance')
        options['ContinuationToken'] = token
    return {'expired': expired, 'deleted': deleted}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--older-than-hours', type=int, default=24)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        counts = cleanup(older_than_hours=args.older_than_hours, apply=args.apply)
        print(f"Incoming cleanup: {counts['expired']} expired, {counts['deleted']} deleted" +
              (' (applied)' if args.apply else ' (preview only)'))
        return 0
    except Exception as exc:
        print(f'FAIL: incoming cleanup ({type(exc).__name__}); private request details withheld')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
