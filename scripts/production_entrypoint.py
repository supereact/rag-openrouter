"""Refuse to start production services until read-only preflight passes."""
import os
import sys

from scripts.check_production import main as preflight


def main() -> int:
    if len(sys.argv) < 2:
        print('A production service command is required.')
        return 2
    if preflight():
        return 1
    os.execvp(sys.argv[1], sys.argv[1:])
    return 0


if __name__ == '__main__':
    sys.exit(main())
