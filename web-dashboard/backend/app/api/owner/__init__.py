"""Protected Owner API composition."""

from fastapi import APIRouter, Depends

from app.api.owner import (
    approvals,
    compliance_runtime,
    executive_bi,
    final_platform_integration,
    finalization,
    licensing,
    notification_runtime,
    operations,
    operations_integration,
    platform_integration,
    production_runtime,
    realtime,
    release_governance,
    runtime,
    security_integration,
    timeline,
)
from app.core.auth import require_super_owner

router = APIRouter(dependencies=[Depends(require_super_owner)])
router.include_router(platform_integration.router)
router.include_router(operations_integration.router)
router.include_router(security_integration.router)
router.include_router(final_platform_integration.router)
router.include_router(production_runtime.router)
router.include_router(runtime.router)
router.include_router(operations.router)
router.include_router(approvals.router)
router.include_router(realtime.router)
router.include_router(release_governance.router)
router.include_router(timeline.router)
router.include_router(compliance_runtime.router)
router.include_router(executive_bi.router)
router.include_router(licensing.router)
router.include_router(notification_runtime.router)
router.include_router(finalization.router)
