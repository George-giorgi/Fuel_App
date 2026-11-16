from backend.app.schemas.dashboard import DashboardStatus


def get_dashboard_status() -> DashboardStatus:
    return DashboardStatus(
        available=False,
        message="No verified dashboard or inventory data source is configured.",
    )
