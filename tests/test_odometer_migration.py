import importlib
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


odometer_migration = importlib.import_module(
    "backend.migrations.versions.0014_odometer_miles"
)


class OdometerMigrationTests(unittest.TestCase):
    def test_upgrade_converts_existing_readings_and_downgrade_restores_kilometres(
        self,
    ) -> None:
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    CREATE TABLE fuel_records (
                        id INTEGER PRIMARY KEY,
                        mileage INTEGER NOT NULL,
                        CONSTRAINT ck_fuel_records_mileage CHECK (mileage >= 0)
                    )
                    """
                )
                connection.exec_driver_sql(
                    """
                    CREATE TABLE vehicle_odometer_corrections (
                        id INTEGER PRIMARY KEY,
                        authorized_odometer_km INTEGER NOT NULL,
                        previous_odometer_km INTEGER NOT NULL
                    )
                    """
                )
                connection.execute(
                    text("INSERT INTO fuel_records (id, mileage) VALUES (1, 12785)")
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO vehicle_odometer_corrections
                            (id, authorized_odometer_km, previous_odometer_km)
                        VALUES (1, 12000, 12785)
                        """
                    )
                )
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    odometer_migration.upgrade()

                reading = connection.execute(
                    text("SELECT mileage_miles FROM fuel_records WHERE id = 1")
                ).scalar_one()
                correction = connection.execute(
                    text(
                        """
                        SELECT authorized_odometer_miles, previous_odometer_miles
                        FROM vehicle_odometer_corrections
                        WHERE id = 1
                        """
                    )
                ).one()
                self.assertEqual(reading, 7944.2)
                self.assertEqual(correction, (7456.5, 7944.2))
                self.assertIn(
                    "mileage_miles",
                    {column["name"] for column in inspect(connection).get_columns(
                        "fuel_records"
                    )},
                )

                with Operations.context(context):
                    odometer_migration.downgrade()

                restored = connection.execute(
                    text("SELECT mileage FROM fuel_records WHERE id = 1")
                ).scalar_one()
                restored_correction = connection.execute(
                    text(
                        """
                        SELECT authorized_odometer_km, previous_odometer_km
                        FROM vehicle_odometer_corrections
                        WHERE id = 1
                        """
                    )
                ).one()
                self.assertEqual(restored, 12785)
                self.assertEqual(restored_correction, (12000, 12785))
        finally:
            engine.dispose()
