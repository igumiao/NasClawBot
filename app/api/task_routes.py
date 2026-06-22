"""HTTP routes for organization automation settings."""

from pathlib import Path

from fastapi import APIRouter

from app.api.schemas import OrganizationAutomationPolicyResponse
from app.domain.organization import OrganizationAutomationPolicy
from app.services.organization_policy_store import OrganizationAutomationPolicyStore

_SETTINGS_DIR = Path(__file__).resolve().parents[2] / "memory" / "settings"


def _organization_policy_store() -> OrganizationAutomationPolicyStore:
    return OrganizationAutomationPolicyStore(_SETTINGS_DIR)


def build_task_router() -> APIRouter:
    """Build a router exposing organization automation policy endpoints."""
    router = APIRouter(tags=["organization"])

    @router.get(
        "/settings/organization-automation",
        response_model=OrganizationAutomationPolicyResponse,
    )
    def get_organization_automation_policy() -> OrganizationAutomationPolicyResponse:
        """Return the user-configured organization automation policy.

        This policy controls whether and how media files are automatically
        organized after torrent downloads complete.
        """
        policy = _organization_policy_store().load()
        return OrganizationAutomationPolicyResponse.model_validate(policy.model_dump())

    @router.put(
        "/settings/organization-automation",
        response_model=OrganizationAutomationPolicyResponse,
    )
    def update_organization_automation_policy(
        body: OrganizationAutomationPolicy,
    ) -> OrganizationAutomationPolicyResponse:
        """Persist the user-configured organization automation policy.

        Accepts the policy fields; ``allow_delete`` and ``allow_overwrite``
        are always forced to ``False`` for safety regardless of the submitted
        value.
        """
        policy = _organization_policy_store().save(body)
        return OrganizationAutomationPolicyResponse.model_validate(policy.model_dump())

    return router
