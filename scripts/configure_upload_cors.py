"""Preview/update only this app's direct-upload CORS rule on the private bucket."""
import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit

RULE_ID = 'RAGDirectUploads'


def configure(origins: list[str], *, apply: bool = False) -> None:
    from app import object_storage
    if not object_storage.enabled():
        raise ValueError('Select the explicit Neon environment first')
    allowed = []
    for origin in origins:
        origin = origin.rstrip('/')
        url = urlsplit(origin)
        if (url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password
                or url.path or url.query or url.fragment or '*' in origin or '\\' in origin
                or any(char.isspace() for char in origin)
                or (url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'))):
            raise ValueError('Specify exact HTTPS origins; HTTP is allowed only for loopback')
        url.port
        if origin not in allowed:
            allowed.append(origin)
    if not allowed:
        raise ValueError('At least one exact frontend origin is required')
    name = object_storage.bucket('upload')
    try:
        previous = object_storage.client().get_bucket_cors(Bucket=name).get('CORSRules', [])
    except Exception as exc:
        if getattr(exc, 'response', {}).get('Error', {}).get('Code') != 'NoSuchCORSConfiguration':
            raise object_storage.StorageUnavailable('Could not inspect upload CORS') from None
        previous = []
    rules = [rule for rule in previous if rule.get('ID') != RULE_ID]
    rules.append({'ID': RULE_ID, 'AllowedOrigins': allowed, 'AllowedMethods': ['POST'],
                  'AllowedHeaders': ['content-type'], 'ExposeHeaders': ['ETag'], 'MaxAgeSeconds': 300})
    print('Direct-upload CORS origins: ' + ', '.join(allowed))
    if any('*' in rule.get('AllowedOrigins', []) for rule in rules[:-1]):
        print('NOTICE: an existing wildcard rule remains; these origins do not restrict that rule.')
    if apply:
        object_storage.call('put_bucket_cors', Bucket=name, CORSConfiguration={'CORSRules': rules})
        actual = object_storage.call('get_bucket_cors', Bucket=name).get('CORSRules', [])
        if rules[-1] not in actual:
            raise object_storage.StorageUnavailable('Upload CORS rule did not persist')
        print('PASS: direct-upload CORS rule applied; other rules and bucket privacy preserved')
    else:
        print('Preview only. Add --apply to update the upload rule; no bucket access levels change.')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', action='append', required=True)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        if args.env_file:
            from scripts.run_neon import environment
            os.environ.update(environment(args.env_file))
        configure(args.origin, apply=args.apply)
        return 0
    except Exception as exc:
        context = getattr(exc, '__context__', None)
        code = getattr(context, 'response', {}).get('Error', {}).get('Code', '')
        known = {'AccessDenied','InvalidRequest','InvalidArgument','MalformedXML','NoSuchBucket',
                 'NotImplemented','SignatureDoesNotMatch','AuthorizationHeaderMalformed'}
        reason = ', provider code ' + code if code in known else ''
        print(f'FAIL: upload CORS setup ({type(exc).__name__}{reason}); request details withheld')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
