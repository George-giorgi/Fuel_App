import argparse
import getpass
import os
import sys
from pathlib import Path

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from backend.app.core.config import DATABASE_PATH, METER_PHOTO_DIRECTORY
from backend.app.db.base import Base
from backend.app.db.session import SessionLocal, engine
from backend.app.models import Employee, MeterPhoto
from backend.app.services.auth import bootstrap_admin
from backend.app.services.application_reset import reset_application_data
from backend.app.services.demo_data import reset_demo_data, seed_demo_data
from backend.app.services.history_cleanup import clear_history
from backend.app.services.photo_storage import (
    PhotoStorageError,
    delete_photo,
    get_photo_storage_backend,
    validate_photo_storage_configuration,
)


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
    if engine.dialect.name != "sqlite":
        print("Demo data commands are restricted to local SQLite.", file=sys.stderr)
        return 2
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
    if engine.dialect.name != "sqlite":
        print("Demo data commands are restricted to local SQLite.", file=sys.stderr)
        return 2
    if os.environ.get("FUEL_PHOTO_STORAGE", "local").strip().lower() != "local":
        print(
            "Demo data reset requires local photo storage; R2 objects are never "
            "deleted by this command.",
            file=sys.stderr,
        )
        return 2
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


def clear_local_history() -> int:
    if engine.dialect.name != "sqlite":
        print("History cleanup is restricted to local SQLite.", file=sys.stderr)
        return 2
    configured_database = engine.url.database
    if (
        configured_database is None
        or Path(configured_database).resolve() != DATABASE_PATH.resolve()
    ):
        print(
            "History cleanup is restricted to data/diesel-desk-dev.sqlite.",
            file=sys.stderr,
        )
        return 2
    if os.environ.get("FUEL_ENV", "").strip().lower() == "production":
        print("History cleanup is disabled in production.", file=sys.stderr)
        return 2
    try:
        storage_backend = get_photo_storage_backend()
    except PhotoStorageError as error:
        print(str(error), file=sys.stderr)
        return 2
    if storage_backend != "local":
        print(
            "History cleanup is restricted to local photo storage; remote "
            "photos were not changed.",
            file=sys.stderr,
        )
        return 2

    try:
        with SessionLocal.begin() as session:
            photo_storage_keys = clear_history(session)
    except SQLAlchemyError as error:
        print(f"Could not clear local history: {error}", file=sys.stderr)
        return 1

    failed_cleanup = False
    photo_keys = set(photo_storage_keys)
    if METER_PHOTO_DIRECTORY.exists():
        photo_keys.update(
            path.name
            for path in METER_PHOTO_DIRECTORY.iterdir()
            if path.is_file() or path.is_symlink()
        )
    for storage_key in sorted(photo_keys):
        try:
            delete_photo(storage_key)
        except PhotoStorageError as error:
            print(f"Could not remove local meter photo {storage_key!r}: {error}", file=sys.stderr)
            failed_cleanup = True

    print(
        "Cleared fuel, meter, photo, QR-session, correction, and login-session "
        "history. Employee accounts, vehicles, and their assignments were kept."
    )
    if failed_cleanup:
        print(
            "Some local meter-photo files could not be removed.",
            file=sys.stderr,
        )
        return 1
    return 0


def reset_production_data() -> int:
    if os.environ.get("FUEL_ENV", "").strip().lower() != "production":
        print(
            "Production reset requires FUEL_ENV=production.",
            file=sys.stderr,
        )
        return 2
    if engine.dialect.name != "postgresql":
        print(
            "Production reset requires the PostgreSQL database configured by "
            "DATABASE_URL.",
            file=sys.stderr,
        )
        return 2
    if os.environ.get("FUEL_PHOTO_STORAGE", "").strip().lower() != "r2":
        print(
            "Production reset requires FUEL_PHOTO_STORAGE=r2.",
            file=sys.stderr,
        )
        return 2
    try:
        validate_photo_storage_configuration()
        with SessionLocal() as session:
            administrators = list(
                session.scalars(
                    select(Employee).where(Employee.role == "admin")
                ).all()
            )
            if len(administrators) != 1:
                print(
                    "Reset cancelled: exactly one admin account must exist.",
                    file=sys.stderr,
                )
                return 2
            admin_email = administrators[0].email
            row_counts = {}
            for table in Base.metadata.sorted_tables:
                query = select(func.count()).select_from(table)
                if table.name == Employee.__tablename__:
                    query = query.where(table.c.role != "admin")
                row_counts[table.name] = int(session.scalar(query) or 0)
            photo_keys = list(
                session.scalars(select(MeterPhoto.storage_key)).all()
            )
    except (PhotoStorageError, SQLAlchemyError) as error:
        print(f"Could not inspect production data: {error}", file=sys.stderr)
        return 1

    total_rows = sum(row_counts.values())
    database_name = engine.url.database or "unknown"
    print(
        f"This will delete {total_rows} application rows and "
        f"{len(photo_keys)} R2 meter photos."
    )
    print(f"PostgreSQL database: {engine.url.host}/{database_name}")
    print(f"It will preserve the admin account {admin_email!r}.")
    print(
        "All other accounts, vehicles, records, readings, and sessions will "
        "be deleted."
    )
    print("Pause app activity before continuing; this reset does not stop writes.")
    print("No backup is created by this command.")
    try:
        confirmation = input(
            f"Type RESET {admin_email} {database_name} to continue: "
        ).strip()
    except EOFError:
        confirmation = ""
    if confirmation != f"RESET {admin_email} {database_name}":
        print("Production reset cancelled.")
        return 2

    failed_photos = []
    for storage_key in photo_keys:
        try:
            delete_photo(storage_key)
        except PhotoStorageError as error:
            failed_photos.append((storage_key, error))
    if failed_photos:
        print(
            "Reset stopped before database deletion because some R2 photos "
            "could not be deleted. Re-run the command to retry.",
            file=sys.stderr,
        )
        for storage_key, error in failed_photos:
            print(f"{storage_key}: {error}", file=sys.stderr)
        return 1

    try:
        with SessionLocal.begin() as session:
            reset_application_data(session)
    except (ValueError, SQLAlchemyError) as error:
        print(
            "R2 photo cleanup completed, but the database reset failed. "
            f"Re-run the command to retry the database reset: {error}",
            file=sys.stderr,
        )
        return 1

    print(
        "Production data reset complete. The admin account and database schema "
        "were preserved; sign in again because sessions were cleared."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Diesel Desk local administration")
    parser.add_argument(
        "command",
        choices=[
            "bootstrap-admin",
            "seed-demo-data",
            "reset-demo-data",
            "clear-history",
            "reset-production-data",
        ],
    )
    args = parser.parse_args()
    if args.command == "bootstrap-admin":
        return bootstrap_first_admin()
    if args.command == "seed-demo-data":
        return seed_local_demo_data()
    if args.command == "reset-demo-data":
        return reset_local_demo_data()
    if args.command == "clear-history":
        return clear_local_history()
    if args.command == "reset-production-data":
        return reset_production_data()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
