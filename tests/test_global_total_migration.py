import importlib
from pathlib import Path
import unittest

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


global_total_migration = importlib.import_module(
    "backend.migrations.versions.0018_global_total_millilitres"
)


class GlobalTotalMigrationTests(unittest.TestCase):
    def test_revision_ids_fit_alembic_version_column(self) -> None:
        config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
        script_directory = ScriptDirectory.from_config(Config(str(config_path)))

        for migration in script_directory.walk_revisions():
            with self.subTest(revision=migration.revision):
                self.assertLessEqual(len(migration.revision), 32)

    def test_upgrade_scales_litre_compatibility_fields_and_preserves_digits(self) -> None:
        engine = create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    CREATE TABLE fuel_records (
                        id INTEGER PRIMARY KEY,
                        meter_photo_id INTEGER,
                        litres FLOAT,
                        current_fill_litres FLOAT,
                        cumulative_meter_reading FLOAT,
                        cumulative_total_litres FLOAT,
                        meter_delta_litres FLOAT,
                        current_fill_milli_litres INTEGER,
                        current_fill_raw_digits VARCHAR(32),
                        cumulative_total_integer INTEGER,
                        cumulative_total_raw_digits VARCHAR(32)
                    )
                    """
                )
                connection.exec_driver_sql(
                    """
                    CREATE TABLE meter_photos (
                        id INTEGER PRIMARY KEY,
                        ocr_cumulative_total_litres FLOAT,
                        cumulative_total_litres FLOAT,
                        ocr_cumulative_total_raw_digits VARCHAR(32),
                        ocr_cumulative_total_decimal_position INTEGER,
                        ocr_current_fill_litres FLOAT,
                        ocr_current_fill_raw_digits VARCHAR(32),
                        current_fill_litres FLOAT,
                        current_fill_milli_litres INTEGER,
                        current_fill_raw_digits VARCHAR(32),
                        cumulative_total_integer INTEGER,
                        cumulative_total_raw_digits VARCHAR(32),
                        verification_method VARCHAR(24)
                    )
                    """
                )
                connection.exec_driver_sql(
                    """
                    CREATE TABLE global_meter_state (
                        id INTEGER PRIMARY KEY,
                        current_cumulative_total_litres FLOAT,
                        previous_cumulative_total_litres FLOAT,
                        current_total_integer INTEGER,
                        previous_total_integer INTEGER,
                        current_total_raw_digits VARCHAR(32),
                        previous_total_raw_digits VARCHAR(32),
                        last_transaction_id INTEGER
                    )
                    """
                )
                connection.exec_driver_sql(
                    """
                    CREATE TABLE global_meter_events (
                        id INTEGER PRIMARY KEY,
                        previous_cumulative_total_litres FLOAT,
                        baseline_cumulative_total_litres FLOAT,
                        previous_total_integer INTEGER,
                        baseline_total_integer INTEGER,
                        previous_total_raw_digits VARCHAR(32),
                        baseline_total_raw_digits VARCHAR(32)
                    )
                    """
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO fuel_records VALUES
                            (1, 1, 22032, 22032, 261563, 261563, 22032,
                                NULL, '22032', 261563, '261563'),
                            (2, 2, 22.032, 22.032, 261.563, 261.563, 22.032,
                                NULL, NULL, NULL, NULL)
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO meter_photos VALUES
                            (1, 261563, 261563, '261563', NULL, 22032, '22032',
                                22032, NULL, NULL, NULL, NULL, 'ocr_confirmed'),
                            (2, 261.563, 261.563, '261563', NULL, 22.032, '22032',
                                22.032, NULL, NULL, NULL, NULL, 'ocr_confirmed')
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO global_meter_state VALUES
                            (1, 261563, 220100, NULL, NULL, '261563', '220100', 1)
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO global_meter_events VALUES
                            (1, 220100, 261563, NULL, NULL, '220100', '261563')
                        """
                    )
                )

                with Operations.context(MigrationContext.configure(connection)):
                    global_total_migration.upgrade()

                self.assertEqual(
                    connection.execute(
                        text(
                            """
                            SELECT cumulative_meter_reading,
                                cumulative_total_litres, meter_delta_litres,
                                litres, current_fill_litres,
                                current_fill_milli_litres,
                                cumulative_total_integer, cumulative_total_raw_digits
                            FROM fuel_records WHERE id = 1
                            """
                        )
                    ).one(),
                    (261.563, 261.563, 22.032, 22.032, 22.032, 22032, 261563, "261563"),
                )
                self.assertEqual(
                    connection.execute(
                        text(
                            """
                            SELECT current_fill_litres, cumulative_total_litres,
                                current_fill_milli_litres, cumulative_total_integer
                            FROM fuel_records WHERE id = 2
                            """
                        )
                    ).one(),
                    (22.032, 261.563, 22032, 261563),
                )
                self.assertEqual(
                    connection.execute(
                        text(
                            """
                            SELECT ocr_cumulative_total_litres,
                                cumulative_total_litres,
                                ocr_cumulative_total_decimal_position,
                                cumulative_total_integer, cumulative_total_raw_digits,
                                current_fill_litres, current_fill_milli_litres
                            FROM meter_photos WHERE id = 1
                            """
                        )
                    ).one(),
                    (261.563, 261.563, 3, 261563, "261563", 22.032, 22032),
                )
                self.assertEqual(
                    connection.execute(
                        text(
                            """
                            SELECT current_cumulative_total_litres,
                                previous_cumulative_total_litres
                            FROM global_meter_state WHERE id = 1
                            """
                        )
                    ).one(),
                    (261.563, 220.1),
                )
                self.assertEqual(
                    connection.execute(
                        text(
                            """
                            SELECT previous_cumulative_total_litres,
                                baseline_cumulative_total_litres
                            FROM global_meter_events WHERE id = 1
                            """
                        )
                    ).one(),
                    (220.1, 261.563),
                )

                with Operations.context(MigrationContext.configure(connection)):
                    global_total_migration.downgrade()

                self.assertEqual(
                    connection.execute(
                        text(
                            """
                            SELECT litres, current_fill_litres,
                                cumulative_meter_reading, cumulative_total_litres,
                                meter_delta_litres
                            FROM fuel_records WHERE id = 1
                            """
                        )
                    ).one(),
                    (22032, 22032, 261563, 261563, 22032),
                )
                self.assertEqual(
                    connection.execute(
                        text(
                            """
                            SELECT ocr_cumulative_total_litres,
                                cumulative_total_litres, ocr_current_fill_litres,
                                current_fill_litres
                            FROM meter_photos WHERE id = 1
                            """
                        )
                    ).one(),
                    (261563, 261563, 22032, 22032),
                )
                self.assertNotIn(
                    "meter_scale_migration_backup",
                    inspect(connection).get_table_names(),
                )
        finally:
            engine.dispose()
