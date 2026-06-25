"""Administration services."""

from app.services.admin.application_read_service import (
    AdminApplicationReadService,
)
from app.services.admin.dashboard_service import AdminDashboardService

__all__ = ["AdminApplicationReadService", "AdminDashboardService"]
