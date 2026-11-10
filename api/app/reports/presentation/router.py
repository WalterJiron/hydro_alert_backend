"""Public report reading and authenticated report creation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import RedirectResponse

from app.auth.domain.entities import User
from app.auth.presentation.dependencies import get_current_user
from app.bootstrap.container import ApplicationContainer
from app.bootstrap.dependencies import get_container
from app.core.errors import ReportPhotoTooLargeError, ResourceNotFoundError
from app.reports.domain.entities import Report
from app.reports.presentation.schemas import ActiveReportsResponse, ReportView

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/active",
    response_model=ActiveReportsResponse,
    summary="List the 100 most recent active reports (public)",
)
async def list_active_reports(
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> ActiveReportsResponse:
    reports = await container.report_service.list_active()
    return ActiveReportsResponse(data=[_to_view(report) for report in reports])


@router.post(
    "",
    response_model=ReportView,
    status_code=201,
    summary="Create a community report (Bearer token required)",
)
async def create_report(
    container: Annotated[ApplicationContainer, Depends(get_container)],
    current_user: Annotated[User, Depends(get_current_user)],
    category: Annotated[str, Form(description="Report category")],
    description: Annotated[str, Form(description="10 to 500 characters")],
    latitude: Annotated[float, Form(ge=-90, le=90)],
    longitude: Annotated[float, Form(ge=-180, le=180)],
    photo: Annotated[UploadFile | None, File()] = None,
) -> ReportView:
    photo_data = await _read_photo(photo, container)
    report = await container.report_service.create(
        user=current_user,
        category=category,
        description=description,
        latitude=latitude,
        longitude=longitude,
        photo_data=photo_data,
    )
    return _to_view(report)


@router.get(
    "/photos/{report_id}",
    summary="Serve or redirect to report photo in storage",
)
async def get_report_photo(
    report_id: str,
    container: Annotated[ApplicationContainer, Depends(get_container)],
) -> Response:
    direct_photo = await container.photo_storage.get_photo(report_id)
    if direct_photo is not None:
        data, content_type = direct_photo
        return Response(
            content=data,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=86400, immutable",
                "Content-Disposition": "inline",
            },
        )

    photo_url = await container.report_service.get_photo_url(report_id)
    if photo_url is None:
        raise ResourceNotFoundError("report photo", report_id)

    return RedirectResponse(
        url=photo_url,
        status_code=307,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.delete(
    "/{report_id}",
    status_code=204,
    summary="Deactivate one of your own reports",
)
async def delete_report(
    report_id: str,
    container: Annotated[ApplicationContainer, Depends(get_container)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    await container.report_service.delete(report_id, user=current_user)
    return Response(status_code=204)


async def _read_photo(
    photo: UploadFile | None,
    container: ApplicationContainer,
) -> bytes | None:
    if photo is None:
        return None
    limit = container.settings.report_photo_max_bytes
    try:
        data = await photo.read(limit + 1)
    finally:
        await photo.close()
    if len(data) > limit:
        raise ReportPhotoTooLargeError(limit)
    return data or None


def _to_view(report: Report) -> ReportView:
    return ReportView(
        id=report.id,
        category=report.category,
        description=report.description,
        latitude=report.latitude,
        longitude=report.longitude,
        photoUrl=report.photo_url,
        createdAt=report.created_at,
    )
