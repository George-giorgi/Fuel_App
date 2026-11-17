from sqlalchemy.orm import Session


def clear_history(session: Session) -> list[str]:
    session.flush()
    connection = session.connection()
    if connection.dialect.name != "sqlite":
        raise ValueError("History cleanup is restricted to local SQLite.")

    photo_keys = [
        row[0]
        for row in connection.exec_driver_sql(
            "SELECT storage_key FROM meter_photos"
        )
    ]

    for table in (
        "global_meter_state",
        "meter_reading_reviews",
        "fuel_records",
        "meter_photos",
        "qr_sessions",
        "global_meter_events",
        "vehicle_meter_events",
        "vehicle_odometer_corrections",
        "employee_sessions",
    ):
        connection.exec_driver_sql(f"DELETE FROM {table}")

    connection.exec_driver_sql(
        "UPDATE vehicles SET cumulative_total_litres = NULL, meter_epoch = 0"
    )
    session.expire_all()
    return photo_keys
