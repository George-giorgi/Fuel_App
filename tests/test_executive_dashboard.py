import asyncio
import json
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_employee
from backend.app.db.base import Base
from backend.app.db.session import create_database_engine, get_db_session
from backend.app.main import app
from backend.app.models import Employee, FuelRecord, GlobalMeterState, Vehicle
from backend.app.schemas.executive_dashboard import (
    ExecutiveAnalyticsRead,
    ExecutiveEmployeeListRead,
    ExecutiveEmployeeRecordsRead,
    ExecutiveOverviewRead,
    ExecutiveVehicleDetailRead,
    ExecutiveVehicleListRead,
    MyVehicleRead,
    SetMyVehicleRequest,
)
from backend.app.services.executive_dashboard import (
    get_executive_analytics,
    get_executive_overview,
    get_executive_vehicle_detail,
    get_my_vehicle,
    list_executive_employee_records,
    list_executive_employees,
    list_executive_vehicles,
    set_my_vehicle,
)


class ExecutiveDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_database_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.today = datetime(2026, 11, 17).date()
        self.today_patch = patch(
            "backend.app.services.executive_dashboard.get_irish_today",
            return_value=self.today,
        )
        self.today_patch.start()
        self.addCleanup(self.today_patch.stop)

        self.boss = Employee(
            email="boss@example.test",
            name="Fleet Boss",
            password_hash="unused",
            role="boss",
            is_active=True,
            is_demo=False,
        )
        self.other_employee = Employee(
            email="other@example.test",
            name="Other Driver",
            password_hash="unused",
            role="employee",
            is_active=True,
            is_demo=False,
        )
        self.company_vehicle = Vehicle(
            registration_number="241-D-100",
            make="Ford",
            model="Transit",
            fuel_type="Diesel",
            tank_capacity=80,
            is_company_vehicle=True,
            is_demo=False,
        )
        self.personal_vehicle = Vehicle(
            registration_number="241-D-200",
            make="Toyota",
            model="Corolla",
            fuel_type="Diesel",
            tank_capacity=50,
            is_company_vehicle=False,
            is_demo=False,
        )
        self.demo_vehicle = Vehicle(
            registration_number="DD-DEMO-001",
            is_company_vehicle=True,
            is_demo=True,
        )
        self.session.add_all(
            [
                self.boss,
                self.other_employee,
                self.company_vehicle,
                self.personal_vehicle,
                self.demo_vehicle,
            ]
        )
        self.session.flush()
        self.company_vehicle.employees.append(self.boss)
        self.session.add_all(
            [
                self._record(
                    self.company_vehicle,
                    self.boss,
                    litres=12,
                    cost=42.5,
                    demo=False,
                ),
                self._record(
                    self.personal_vehicle,
                    self.boss,
                    litres=50,
                    cost=200,
                    demo=False,
                ),
                self._record(
                    self.company_vehicle,
                    self.boss,
                    litres=80,
                    cost=900,
                    demo=True,
                ),
            ]
        )
        self.session.flush()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _record(
        self,
        vehicle: Vehicle,
        employee: Employee,
        *,
        litres: float,
        cost: float,
        demo: bool,
    ) -> FuelRecord:
        return FuelRecord(
            reg_number=vehicle.registration_number,
            fuel_type="Diesel",
            first_name=employee.name.split()[0],
            surname=employee.name.split()[-1],
            mileage_miles=12_000,
            capacity=vehicle.tank_capacity or 70,
            litres=litres,
            current_fill_litres=litres,
            cumulative_total_litres=litres,
            cost=cost,
            employee_id=employee.id,
            vehicle_id=vehicle.id,
            meter_check_status="verified",
            is_demo=demo,
            created_at=datetime(2026, 11, 17, 12, tzinfo=timezone.utc),
        )

    def test_overview_excludes_personal_and_demo_data(self) -> None:
        result = get_executive_overview(self.session)

        self.assertEqual(result["fleet"]["total_vehicles"], 1)
        self.assertEqual(result["today_summary"]["litres"], 12)
        self.assertEqual(result["today_summary"]["cost_eur"], 42.5)
        self.assertEqual(result["today_summary"]["transaction_count"], 1)
        self.assertEqual(result["month_summary"]["cost_record_count"], 1)
        self.assertEqual(len(result["latest_activity"]), 1)
        self.assertIsNone(result["meter"]["current_cumulative_total_litres"])
        self.assertIsNone(self.session.get(GlobalMeterState, 1))

    def test_boss_data_can_include_demo_records_across_dashboard_views(self) -> None:
        overview = get_executive_overview(self.session, include_demo=True)
        analytics = get_executive_analytics(
            self.session, 7, include_demo=True
        )
        vehicles = list_executive_vehicles(
            self.session, page_size=10, include_demo=True
        )
        detail = get_executive_vehicle_detail(
            self.session, self.company_vehicle.id, include_demo=True
        )

        self.assertEqual(overview["fleet"]["total_vehicles"], 2)
        self.assertEqual(overview["today_summary"]["litres"], 92)
        self.assertEqual(overview["today_summary"]["transaction_count"], 2)
        self.assertEqual(sum(analytics["diesel_litres"]), 92)
        self.assertEqual(vehicles["total"], 2)
        self.assertEqual(detail["month_diesel_litres"], 92)
        self.assertEqual(len(detail["transactions"]), 2)

    def test_analytics_and_vehicle_details_use_company_records(self) -> None:
        analytics = get_executive_analytics(self.session, 7)
        vehicles = list_executive_vehicles(self.session, page_size=10)
        detail = get_executive_vehicle_detail(
            self.session, self.company_vehicle.id
        )

        self.assertEqual(sum(analytics["diesel_litres"]), 12)
        self.assertEqual(sum(analytics["fuel_cost_eur"]), 42.5)
        self.assertEqual(
            [vehicle["registration_number"] for vehicle in analytics["top_vehicles"]],
            ["241-D-100"],
        )
        self.assertEqual(vehicles["total"], 1)
        self.assertEqual(vehicles["items"][0]["registration_number"], "241-D-100")
        self.assertEqual(detail["month_diesel_litres"], 12)
        self.assertEqual(detail["month_cost_eur"], 42.5)
        self.assertEqual(len(detail["transactions"]), 1)

    def test_employee_directory_and_paginated_records_include_demo_for_boss(self) -> None:
        self.company_vehicle.employees.append(self.other_employee)
        self.session.add(
            self._record(
                self.company_vehicle,
                self.other_employee,
                litres=7,
                cost=14,
                demo=False,
            )
        )
        demo_employee = Employee(
            email="demo-driver@example.test",
            name="Demo Driver",
            password_hash="unused",
            role="employee",
            is_active=True,
            is_demo=True,
        )
        self.session.add(demo_employee)
        self.session.flush()
        self.demo_vehicle.employees.append(demo_employee)
        self.session.add(
            self._record(
                self.demo_vehicle,
                demo_employee,
                litres=9,
                cost=20,
                demo=True,
            )
        )
        self.session.flush()

        boss_directory = list_executive_employees(
            self.session, page_size=10, include_demo=True
        )
        admin_directory = list_executive_employees(self.session, page_size=10)
        employee = next(
            item
            for item in boss_directory["items"]
            if item["id"] == self.other_employee.id
        )
        demo_records = list_executive_employee_records(
            self.session,
            demo_employee.id,
            page=1,
            page_size=10,
            include_demo=True,
        )

        self.assertEqual(boss_directory["total"], 2)
        self.assertEqual(admin_directory["total"], 1)
        self.assertEqual(employee["vehicle_registrations"], ["241-D-100"])
        self.assertEqual(employee["record_count"], 1)
        self.assertEqual(employee["month_diesel_litres"], 7)
        self.assertEqual(demo_records["total"], 1)
        self.assertEqual(demo_records["items"][0]["registration_number"], "DD-DEMO-001")
        self.assertIsNone(
            list_executive_employee_records(
                self.session, demo_employee.id, include_demo=False
            )
        )

    def test_employee_records_can_be_filtered_by_inclusive_date_range(self) -> None:
        first_record = self._record(
        self.company_vehicle,
        self.other_employee,
        litres=8,
        cost=24,
        demo=False,
        )
        first_record.created_at = datetime(
        2025, 1, 1, 10, tzinfo=timezone.utc
        )
        second_record = self._record(
        self.company_vehicle,
        self.other_employee,
        litres=7,
        cost=0,
        demo=False,
        )
        second_record.created_at = datetime(
        2025, 1, 1, 23, 30, tzinfo=timezone.utc
        )
        outside_record = self._record(
        self.company_vehicle,
        self.other_employee,
        litres=5,
        cost=15,
        demo=False,
        )
        outside_record.created_at = datetime(
        2024, 12, 31, 12, tzinfo=timezone.utc
        )
        self.session.add_all([first_record, second_record, outside_record])
        self.session.flush()

        result = list_executive_employee_records(
        self.session,
        self.other_employee.id,
        page_size=1,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 1),
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["diesel_litres"], 15)
        self.assertEqual(result["cost_eur"], 24)
        self.assertEqual(result["cost_record_count"], 1)

    def test_missing_costs_are_reported_without_inventing_a_total(self) -> None:
        self.session.add(
            self._record(
                self.company_vehicle,
                self.boss,
                litres=4,
                cost=0,
                demo=False,
            )
        )
        self.session.flush()

        result = get_executive_overview(self.session)

        self.assertEqual(result["month_summary"]["cost_eur"], 42.5)
        self.assertEqual(result["month_summary"]["cost_record_count"], 1)
        self.assertEqual(result["month_summary"]["missing_cost_count"], 1)
        self.assertTrue(
            any(notification["kind"] == "cost_data" for notification in result["notifications"])
        )

    def test_analytics_uses_irish_local_calendar_days(self) -> None:
        record = self._record(
            self.company_vehicle,
            self.boss,
            litres=3,
            cost=7,
            demo=False,
        )
        record.created_at = datetime(2026, 6, 1, 23, 30, tzinfo=timezone.utc)
        self.session.add(record)
        self.session.flush()

        with patch(
            "backend.app.services.executive_dashboard.get_irish_today",
            return_value=date(2026, 6, 2),
        ):
            result = get_executive_analytics(self.session, 7)

        self.assertEqual(result["labels"][-1], date(2026, 6, 2))
        self.assertEqual(result["diesel_litres"][-1], 3)

    def test_service_results_match_api_response_schemas(self) -> None:
        ExecutiveOverviewRead.model_validate(get_executive_overview(self.session))
        ExecutiveAnalyticsRead.model_validate(
            get_executive_analytics(self.session, 30)
        )
        ExecutiveEmployeeListRead.model_validate(
            list_executive_employees(self.session)
        )
        ExecutiveEmployeeRecordsRead.model_validate(
            list_executive_employee_records(self.session, self.other_employee.id)
            or {"items": [], "total": 0, "page": 1, "page_size": 20}
        )
        ExecutiveVehicleListRead.model_validate(
            list_executive_vehicles(
                self.session, sort_by="activity", sort_order="desc"
            )
        )
        ExecutiveVehicleDetailRead.model_validate(
            get_executive_vehicle_detail(self.session, self.company_vehicle.id)
        )
        MyVehicleRead.model_validate(get_my_vehicle(self.session, self.boss.id))
        self.assertEqual(
            SetMyVehicleRequest.model_validate(
                {"vehicleId": self.personal_vehicle.id}
            ).vehicle_id,
            self.personal_vehicle.id,
        )

    def test_personal_vehicle_assignment_is_isolated_and_exclusive(self) -> None:
        with self.assertRaisesRegex(ValueError, "active personal vehicle"):
            set_my_vehicle(self.session, self.boss.id, self.company_vehicle.id)

        assigned = set_my_vehicle(
            self.session, self.boss.id, self.personal_vehicle.id
        )
        self.assertEqual(assigned["vehicle"]["id"], self.personal_vehicle.id)
        self.assertFalse(assigned["vehicle"]["is_company_vehicle"])
        self.assertEqual(assigned["vehicle"]["month_diesel_litres"], 50)

        self.other_employee.vehicles.append(self.personal_vehicle)
        stranger = Employee(
            email="stranger@example.test",
            name="Stranger Driver",
            password_hash="unused",
            role="employee",
            is_active=True,
            is_demo=False,
        )
        self.session.add(stranger)
        self.session.flush()
        with self.assertRaisesRegex(ValueError, "already assigned"):
            set_my_vehicle(self.session, stranger.id, self.personal_vehicle.id)

    def test_executive_routes_allow_management_and_deny_employees(self) -> None:
        demo_employee = Employee(
            email="demo-driver@example.test",
            name="Demo Driver",
            password_hash="unused",
            role="employee",
            is_active=True,
            is_demo=True,
        )
        self.session.add(demo_employee)
        self.session.flush()
        self.company_vehicle.employees.append(demo_employee)
        demo_record = self._record(
            self.company_vehicle,
            demo_employee,
            litres=9,
            cost=20,
            demo=True,
        )
        self.session.add(demo_record)
        self.session.flush()
        self.session.add(
            GlobalMeterState(
                id=1,
                current_cumulative_total_litres=9,
                previous_cumulative_total_litres=0,
                last_updated_at=demo_record.created_at,
                last_transaction_id=demo_record.id,
                last_employee_id=demo_employee.id,
                last_vehicle_id=self.company_vehicle.id,
            )
        )
        self.session.flush()

        employees = {
            "boss": self.boss,
            "admin": Employee(
                email="admin@example.test",
                name="Fleet Admin",
                password_hash="unused",
                role="admin",
                is_active=True,
                is_demo=False,
            ),
            "employee": self.other_employee,
        }
        self.session.add(employees["admin"])
        self.session.flush()
        original_overrides = app.dependency_overrides.copy()
        selected_employee = [self.boss]
        app.dependency_overrides[get_db_session] = lambda: self.session
        app.dependency_overrides[get_current_employee] = lambda: selected_employee[0]

        async def request_dashboard(
            path: str = "/api/executive/dashboard",
            query_string: str = "",
        ) -> tuple[int, dict]:
            request_messages = [
                {"type": "http.request", "body": b"", "more_body": False}
            ]
            response_status: int | None = None
            response_body = bytearray()

            async def receive():
                if request_messages:
                    return request_messages.pop(0)
                return {"type": "http.disconnect"}

            async def send(message):
                nonlocal response_status
                if message["type"] == "http.response.start":
                    response_status = message["status"]
                elif message["type"] == "http.response.body":
                    response_body.extend(message.get("body", b""))

            await app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.3"},
                    "http_version": "1.1",
                    "method": "GET",
                    "scheme": "http",
                    "path": path,
                    "raw_path": path.encode(),
                    "query_string": query_string.encode(),
                    "headers": [],
                    "client": ("127.0.0.1", 1234),
                    "server": ("testserver", 8000),
                    "root_path": "",
                },
                receive,
                send,
            )
            result = json.loads(response_body) if response_body else {}
            return int(response_status or 0), result

        try:
            boss_status, boss_result = asyncio.run(request_dashboard())
            self.assertEqual(boss_status, 200)
            self.assertEqual(boss_result["fleet"]["totalVehicles"], 2)
            self.assertEqual(boss_result["todaySummary"]["transactionCount"], 3)
            self.assertEqual(
                boss_result["meter"]["currentCumulativeTotalLitres"], 9
            )
            self.assertTrue(boss_result["meter"]["isDemo"])
            boss_analytics_status, boss_analytics = asyncio.run(
                request_dashboard(
                    "/api/executive/analytics", "range_days=30"
                )
            )
            self.assertEqual(boss_analytics_status, 200)
            self.assertEqual(boss_analytics["rangeDays"], 30)
            unsupported_analytics_status, unsupported_analytics = asyncio.run(
                request_dashboard(
                    "/api/executive/analytics", "range_days=14"
                )
            )
            self.assertEqual(unsupported_analytics_status, 422)
            self.assertEqual(
                unsupported_analytics["detail"],
                "range_days must be 7, 30, or 90.",
            )
            boss_directory_status, boss_directory = asyncio.run(
                request_dashboard("/api/executive/employees", "page_size=10")
            )
            self.assertEqual(boss_directory_status, 200)
            self.assertEqual(boss_directory["total"], 2)
            boss_records_status, boss_records = asyncio.run(
                request_dashboard(
                    f"/api/executive/employees/{demo_employee.id}/fuel-records",
                    "page_size=10",
                )
            )
            self.assertEqual(boss_records_status, 200)
            self.assertEqual(boss_records["total"], 1)
            filtered_records_status, filtered_records = asyncio.run(
                request_dashboard(
                    f"/api/executive/employees/{demo_employee.id}/fuel-records",
                    "page_size=10&start_date=2026-11-17&end_date=2026-11-17",
                )
            )
            self.assertEqual(filtered_records_status, 200)
            self.assertEqual(filtered_records["total"], 1)
            self.assertEqual(filtered_records["dieselLitres"], 9)
            invalid_range_status, _ = asyncio.run(
                request_dashboard(
                    f"/api/executive/employees/{demo_employee.id}/fuel-records",
                    "start_date=2026-11-18&end_date=2026-11-17",
                )
            )
            self.assertEqual(invalid_range_status, 422)

            selected_employee[0] = employees["admin"]
            admin_status, admin_result = asyncio.run(request_dashboard())
            self.assertEqual(admin_status, 200)
            self.assertEqual(admin_result["fleet"]["totalVehicles"], 2)
            self.assertEqual(
                admin_result["todaySummary"]["transactionCount"], 3
            )
            self.assertEqual(
                admin_result["meter"]["currentCumulativeTotalLitres"], 9
            )
            self.assertTrue(admin_result["meter"]["isDemo"])
            admin_analytics_status, admin_analytics = asyncio.run(
                request_dashboard(
                    "/api/executive/analytics", "range_days=30"
                )
            )
            self.assertEqual(admin_analytics_status, 200)
            self.assertEqual(admin_analytics["rangeDays"], 30)
            admin_directory_status, admin_directory = asyncio.run(
                request_dashboard("/api/executive/employees", "page_size=10")
            )
            self.assertEqual(admin_directory_status, 200)
            self.assertEqual(admin_directory["total"], 2)
            admin_records_status, admin_records = asyncio.run(
                request_dashboard(
                    f"/api/executive/employees/{demo_employee.id}/fuel-records",
                    "page_size=10",
                )
            )
            self.assertEqual(admin_records_status, 200)
            self.assertEqual(admin_records["total"], 1)

            selected_employee[0] = self.other_employee
            employee_status, result = asyncio.run(request_dashboard())
            self.assertEqual(employee_status, 403)
            self.assertEqual(result["detail"], "Management access required.")
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(original_overrides)


if __name__ == "__main__":
    unittest.main()
