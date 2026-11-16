from backend.app.schemas.inventory import InventoryStatus


def get_inventory_status() -> InventoryStatus:
    return InventoryStatus(
        available=False,
        items=[],
        message="No verified inventory data source is configured.",
    )
