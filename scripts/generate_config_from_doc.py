#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app_config.loader import resolve_interest_profile_path
from app_config.onboarding import build_config_from_document, load_document_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an editable monitor config from a user document")
    parser.add_argument("--input", required=True, help="Path to user document (.txt/.md/.docx)")
    parser.add_argument("--output", required=True, help="Path to generated config JSON")
    parser.add_argument("--template", default="config.template.json", help="Base config template JSON")
    parser.add_argument("--user-name", default=None, help="Override config.user.name")
    parser.add_argument("--email", default=None, help="Override email.recipient")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    template_path = Path(args.template)
    if not template_path.is_absolute():
        template_path = REPO_ROOT / template_path

    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.is_absolute():
        input_path = Path.cwd() / input_path
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path

    with open(template_path, "r", encoding="utf-8") as f:
        template = json.load(f)

    document_text = load_document_text(str(input_path))
    config = build_config_from_document(
        template=template,
        document_text=document_text,
        config_path=str(output_path),
        user_name=args.user_name,
        email_recipient=args.email,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")

    profile_path = resolve_interest_profile_path(config_path=str(output_path))
    print(f"Generated config: {output_path}")
    print(f"Generated profile: {profile_path}")
    print("The generated config contains runtime settings only.")
    print("A confirmed sibling interest_profile.json was generated as the runtime source of truth.")
    print("You can edit that interest_profile.json before starting the container.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
