import argparse
import getpass
import os
import sys
from pathlib import Path

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError

from backend.app.core.config import METER_PHOTO_DIRECTORY
from backend.app.db.session import SessionLocal
from backend.app.services.auth import bootstrap_admin
from backend.app.services.demo_data import reset_demo_data, seed_demo_data


def bootstrap_first_admin() -> int:
    email = os.environ.get("FUEL_ADMIN_EMAIL", "").strip()
    name = os.environ.get("FUEL_ADMIN_NAME", "").strip()
    password = os.environ.get("FUEL_ADMIN_PASSWORD")
    if not email or not name:
        print(
            "Set FUEL_ADMIN_EMAIL and FUEL_ADMIN_NAME before bootstrapping.",
            file=sys.stderr,
        )
        return 2
    try:
        email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    except ValidationError:
        print("FUEL_ADMIN_EMAIL must be a valid email address.", file=sys.stderr)
        return 2
    if password is None:
        password = getpass.getpass("Initial admin password (12+ characters): ")
    if len(password) < 12:
        print(
            "The initial admin password must contain at least 12 characters.",
            file=sys.stderr,
        )
        return 2

    try:
        with SessionLocal.begin() as session:
            admin = bootstrap_admin(session, email, name, password)
    except (ValueError, IntegrityError) as error:
        print(str(error), file=sys.stderr)
        return 1

    print(f"Administrator account created for {admin.email}.")
    return 0


def seed_local_demo_data() -> int:
    try:
        with SessionLocal.begin() as session:
            seed_demo_data(session)
    except (ValueError, IntegrityError) as error:
        print(str(error), file=sys.stderr)
        return 1

    print(
        "Seeded 10 demo employees, 10 assigned demo vehicles, and "
        "30 demo fuel records."
    )
    print("Demo login: usernames Tommy1 through Tommy10; password: 123456.")
    return 0


def reset_local_demo_data() -> int:
    try:
        with SessionLocal.begin() as session:
            photo_storage_keys = reset_demo_data(session)
    except (ValueError, IntegrityError) as error:
        print(str(error), file=sys.stderr)
        return 1

    failed_cleanup = False
    for storage_key in photo_storage_keys:
        photo_path = METER_PHOTO_DIRECTORY / storage_key
        if photo_path.parent != METER_PHOTO_DIRECTORY:
            print(
                f"Refusing to remove meter photo outside the photo directory: "
                f"{storage_key!r}",
                file=sys.stderr,
            )
            failed_cleanup = True
            continue
        try:
            photo_path.unlink(missing_ok=True)
        except OSError as error:
            print(
                f"Could not remove demo meter photo {photo_path}: {error}",
                file=sys.stderr,
            )
            failed_cleanup = True

    print(
        "Replaced the local demo cohort with Tommy1 to Tommy10 and refreshed "
        "their 30 fictional fuel records."
    )
    print("All passwords are 123456. Admin and Boss accounts were preserved.")
    if failed_cleanup:
        print(
            "Some old private meter-photo files could not be removed.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Diesel Desk local administration")
    parser.add_argument(
        "command",
        choices=["bootstrap-admin", "seed-demo-data", "reset-demo-data"],
    )
    args = parser.parse_args()
    if args.command == "bootstrap-admin":
        return bootstrap_first_admin()
    if args.command == "seed-demo-data":
        return seed_local_demo_data()
    if args.command == "reset-demo-data":
        return reset_local_demo_data()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
