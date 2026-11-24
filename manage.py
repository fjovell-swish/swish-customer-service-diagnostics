#!/usr/bin/env python
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    # The repo's .env (git-ignored, see .env.example) for local runs. What the environment
    # already sets wins, and the image has no .env, so deployed commands only see their own.
    load_dotenv(Path(__file__).resolve().parent / ".env")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
