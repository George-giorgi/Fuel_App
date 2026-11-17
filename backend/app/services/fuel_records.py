from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import is_manual_meter_entry_enabled
from backend.app.models import (
    Employee,
    FuelRecord,
    GlobalMeterState,
    MeterReadingReview,
    Vehicle,
    VehicleOdometerCorrection,
)
from backend.app.repositories.fuel_records import (
    get_latest_vehicle_record,
    list_fuel_records,
    list_vehicle_fuel_records,
)
from backend.app.repositories.meter_photos import get_meter_photo_by_id
from backend.app.repositories.vehicles import (
    get_employee_vehicle,
    get_odometer_correction,
    get_vehicle_by_id,
    is_employee_assigned_to_vehicle,
)
from backend.app.schemas.fuel_record import (
    FuelRecordCreate,
    MeterReadingPreviewRequest,
)
from backend.app.services.global_meter import (
    GlobalMeterConcurrentUpdate,
    advance_global_meter_revision,
    create_global_meter_event,
    get_or_create_global_meter_state,
    update_global_meter_after_fill,
)
from backend.app.services.meter_readings import (
    InvalidMeterDigits,
    MAX_FILL_MILLI_LITRES,
    assess_meter_readings,
    decimal_to_milli_litres,
    milli_litres_to_decimal,
    parse_total_raw_digits,
)


class FuelSubmissionError(ValueError):
    pass


class MeterPhotoNotOwned(FuelSubmissionError):
    pass


class MeterPhotoNotVerified(FuelSubmissionError):
    pass


def get_fuel_records(session: Session, employee_id: int) -> list[FuelRecord]:
    return list_fuel_records(session, employee_id)


def get_assigned_vehicle_fuel_records(
    session: Session, employee_id: int
) -> tuple[Vehicle | None, list[FuelRecord]]:
    vehicle = get_employee_vehicle(session, employee_id)
    if vehicle is None:
        return None, []
    return vehicle, list_vehicle_fuel_records(session, vehicle.id, employee_id)


def create_fuel_record(
    session: Session,
    employee: Employee,
    request: FuelRecordCreate,
) -> FuelRecord | MeterReadingReview:
    if request.vehicle_id is not None and employee.role != "boss":
        raise FuelSubmissionError("Only boss accounts can select another vehicle.")

    vehicle = (
        get_vehicle_by_id(session, request.vehicle_id)
        if request.vehicle_id is not None
        else get_employee_vehicle(session, employee.id)
    )
    if vehicle is None or (
        request.vehicle_id is None
        and not is_employee_assigned_to_vehicle(vehicle, employee.id)
    ):
        raise FuelSubmissionError("No vehicle is assigned to this employee.")
    if vehicle.fuel_type not in {"Diesel", "AdBlue", "Petrol"}:
        raise FuelSubmissionError("The assigned vehicle's fuel type is invalid.")
    if vehicle.tank_capacity is None or vehicle.tank_capacity <= 0:
        raise FuelSubmissionError(
            "The assigned vehicle's tank capacity must be configured by an administrator."
        )

    meter_photo = None
    raw_fill = None
    raw_total = request.cumulative_total_raw_digits
    source = "MANUAL"
    if request.meter_photo_id is not None:
        meter_photo = get_meter_photo_by_id(session, request.meter_photo_id)
        if (
            meter_photo is None
            or meter_photo.employee_id != employee.id
            or meter_photo.vehicle_id != vehicle.id
        ):
            raise MeterPhotoNotOwned("Meter photo not found for the assigned vehicle.")
        if meter_photo.verified_at is None:
            raise MeterPhotoNotVerified(
                "Verify the meter readings against the photo before submitting."
            )
        raw_total = meter_photo.cumulative_total_raw_digits
        stored_source = (meter_photo.reading_source or "").upper()
        if stored_source in {"MANUAL", "GOOGLE_VISION", "OPENCV"}:
            source = stored_source
        elif meter_photo.ocr_status == "skipped":
            source = "MANUAL"
        elif meter_photo.ocr_provider == "google_vision":
            source = "GOOGLE_VISION"
        elif meter_photo.ocr_provider == "tesseract":
            source = "OPENCV"
        else:
            raise MeterPhotoNotVerified(
                "The verified meter reading source is unknown."
            )
        cumulative_total = (
            meter_photo.cumulative_total_integer
            if meter_photo.cumulative_total_integer is not None
            else None
        )
        source_warnings = list(
            meter_photo.reading_warnings
            if meter_photo.reading_warnings is not None
            else meter_photo.ocr_warnings or []
        )
        if meter_photo.cumulative_total_manually_corrected:
            resolved_ocr_warnings = set(meter_photo.ocr_warnings or [])
            source_warnings = [
                warning
                for warning in source_warnings
                if (
                    warning not in resolved_ocr_warnings
                    and warning
                    != "The employee corrected or manually entered the OCR-suggested TOTAL digits."
                )
                or "matches an earlier upload" in warning
            ]
        if session.scalar(
            select(FuelRecord.id).where(FuelRecord.meter_photo_id == meter_photo.id)
        ):
            raise FuelSubmissionError(
                "This meter photo is already linked to a fuel record."
            )
    else:
        if not is_manual_meter_entry_enabled():
            raise FuelSubmissionError(
                "Manual meter entry is disabled by configuration."
            )
        source_warnings = []
        try:
            if raw_total is not None:
                cumulative_total = parse_total_raw_digits(raw_total)
            elif request.cumulative_total_litres is not None:
                total_value = request.cumulative_total_litres
                cumulative_total = decimal_to_milli_litres(total_value)
                raw_total = str(cumulative_total).zfill(6)
            else:
                cumulative_total = None
        except InvalidMeterDigits as error:
            raise FuelSubmissionError(str(error)) from error
        if cumulative_total is None:
            raise FuelSubmissionError(
                "Global cumulative total digits are required."
            )

    if cumulative_total is None:
        raise MeterPhotoNotVerified(
            "The verified global cumulative total is missing."
        )
    latest_vehicle_record = get_latest_vehicle_record(session, vehicle.id)
    odometer_correction: VehicleOdometerCorrection | None = None
    if (
        latest_vehicle_record is not None
        and request.odometer_miles < latest_vehicle_record.mileage_miles
    ):
        odometer_correction = get_odometer_correction(
            session, vehicle.id, request.odometer_miles
        )
        if (
            odometer_correction is None
            or odometer_correction.previous_odometer_miles
            != latest_vehicle_record.mileage_miles
        ):
            raise FuelSubmissionError(
                "The odometer is below the vehicle's previous recorded reading "
                f"({latest_vehicle_record.mileage_miles:,.1f} mi). "
                "An administrator must authorize this exact corrected reading "
                "before it can be submitted."
            )

    global_meter_state: GlobalMeterState = get_or_create_global_meter_state(session)
    previous_total = global_meter_state.current_total_integer
    if (
        previous_total is None
        and global_meter_state.current_cumulative_total_litres is not None
    ):
        raise FuelSubmissionError(
            "The existing global total has no exact milli-litre value. "
            "An administrator must investigate it before new readings can be accepted."
        )
    if previous_total is None:
        raise FuelSubmissionError(
            "There is no previous accepted cumulative total, so fuel dispensed "
            "cannot be calculated. An administrator must establish the meter baseline."
        )
    assessment = assess_meter_readings(
        fill_milli_litres=None,
        previous_total_milli_litres=previous_total,
        cumulative_total_milli_litres=cumulative_total,
        source=source,
    )
    if meter_photo is not None:
        assessment_warnings = set(assessment.warnings)
        source_warnings = [
            warning
            for warning in source_warnings
            if warning not in assessment_warnings
        ]
    effective_calculation = assessment.fill_calculation
    if (
        effective_calculation == "global_total_difference"
        and assessment.top_current_fill_milli_litres is not None
        and not request.calculated_fill_confirmed
    ):
        calculated_litres = milli_litres_to_decimal(
            assessment.fill_milli_litres
        )
        raise FuelSubmissionError(
            "Confirm the calculated fill amount before submitting: "
            f"{calculated_litres} L."
        )
    combined_warnings = list(
        dict.fromkeys(list(source_warnings) + list(assessment.warnings))
    )
    fill_milli_litres = assessment.fill_milli_litres
    fill_source = assessment.fill_source
    fill_calculation = assessment.fill_calculation
    duplicate_record_id = session.scalar(
        select(FuelRecord.id)
        .where(
            FuelRecord.employee_id == employee.id,
            FuelRecord.vehicle_id == vehicle.id,
            FuelRecord.cumulative_total_integer == cumulative_total,
            FuelRecord.current_fill_raw_digits == raw_fill,
            FuelRecord.mileage_miles == request.odometer_miles,
        )
        .limit(1)
    )
    if duplicate_record_id is not None:
        raise FuelSubmissionError(
            "This global cumulative reading has already been saved. "
            "Check the latest fuel record before submitting again."
        )
    if assessment.delta_milli_litres == 0:
        raise FuelSubmissionError(
            "The global cumulative total has not changed. Check the digits "
            "or confirm that this is not a duplicate submission."
        )
    existing_review = session.scalar(
        select(MeterReadingReview.id)
        .where(
            MeterReadingReview.employee_id == employee.id,
            MeterReadingReview.vehicle_id == vehicle.id,
            MeterReadingReview.cumulative_total_integer == cumulative_total,
            MeterReadingReview.current_fill_raw_digits == raw_fill,
            MeterReadingReview.odometer_miles == request.odometer_miles,
            MeterReadingReview.status == "pending",
        )
        .limit(1)
    )
    if existing_review is not None:
        raise FuelSubmissionError(
            "This meter reading is already waiting for administrator review."
        )
    if meter_photo is not None and session.scalar(
        select(MeterReadingReview.id).where(
            MeterReadingReview.meter_photo_id == meter_photo.id
        )
    ):
        raise FuelSubmissionError(
            "This meter photo has already been submitted for administrator review."
        )

    if combined_warnings:
        review = MeterReadingReview(
            employee_id=employee.id,
            vehicle_id=vehicle.id,
            meter_photo_id=meter_photo.id if meter_photo is not None else None,
            odometer_correction_id=(
                odometer_correction.id if odometer_correction is not None else None
            ),
            odometer_miles=request.odometer_miles,
            current_fill_milli_litres=fill_milli_litres,
            top_current_fill_milli_litres=(
                assessment.top_current_fill_milli_litres
            ),
            cumulative_total_integer=cumulative_total,
            previous_global_total_integer=previous_total,
            current_fill_raw_digits=raw_fill,
            cumulative_total_raw_digits=raw_total,
            reading_source=assessment.source,
            fill_source=fill_source,
            fill_calculation=fill_calculation,
            warnings=combined_warnings,
            global_meter_revision=global_meter_state.revision,
            submitted_at=datetime.now(timezone.utc),
        )
        session.add(review)
        session.flush()
        return review

    if fill_milli_litres is None:
        raise FuelSubmissionError(
            "Fuel dispensed could not be calculated from the previous and new TOTAL readings."
        )
    if fill_milli_litres <= 0:
        raise FuelSubmissionError(
            "Fuel dispensed must be greater than zero."
        )
    fill_value = milli_litres_to_decimal(fill_milli_litres)
    if fill_value is None:
        raise FuelSubmissionError(
            "Fuel dispensed could not be calculated from the cumulative TOTAL."
        )
    current_fill = float(fill_value)
    cumulative_total_value = float(milli_litres_to_decimal(cumulative_total))
    meter_delta = (
        float(milli_litres_to_decimal(assessment.delta_milli_litres))
        if assessment.delta_milli_litres is not None
        else None
    )
    first_name, _, surname = employee.name.partition(" ")
    now = datetime.now(timezone.utc)
    record = FuelRecord(
        reg_number=vehicle.registration_number,
        fuel_type=vehicle.fuel_type,
        first_name=first_name,
        surname=surname,
        mileage_miles=request.odometer_miles,
        capacity=vehicle.tank_capacity,
        litres=current_fill,
        cost=0,
        employee_id=employee.id,
        vehicle_id=vehicle.id,
        current_fuel_reading=None,
        cumulative_meter_reading=cumulative_total_value,
        current_fill_litres=current_fill,
        cumulative_total_litres=cumulative_total_value,
        meter_delta_litres=meter_delta,
        current_fill_milli_litres=fill_milli_litres,
        top_current_fill_milli_litres=None,
        cumulative_total_integer=cumulative_total,
        previous_global_total_integer=previous_total,
        current_fill_raw_digits=None,
        cumulative_total_raw_digits=raw_total,
        meter_reading_source=fill_source or assessment.source,
        reading_source=assessment.source,
        fill_calculation=fill_calculation,
        meter_check_status=(
            "baseline"
            if previous_total is None
            else "warning"
            if combined_warnings
            else "matched"
            if assessment.reconciliation_status == "reconciled"
            else assessment.reconciliation_status
        ),
        meter_warnings=combined_warnings,
        meter_epoch=vehicle.meter_epoch,
        meter_photo_id=meter_photo.id if meter_photo is not None else None,
        odometer_correction_id=(
            odometer_correction.id if odometer_correction is not None else None
        ),
        is_demo=employee.is_demo,
        demo_key=(
            f"global-meter-test:{employee.username or employee.id}:"
            f"{meter_photo.id}"
            if employee.is_demo and meter_photo is not None
            else None
        ),
        created_at=now,
    )
    if odometer_correction is not None:
        odometer_correction.used_by_employee_id = employee.id
        odometer_correction.used_at = now
    session.add(record)
    session.flush()
    establishes_baseline = (
        previous_total is None
        and not source_warnings
        and assessment.top_current_fill_milli_litres is not None
        and assessment.warnings
        == (
            "There is no previous global total; this reading establishes the baseline.",
        )
    )
    reconciled_fill = (
        previous_total is not None
        and not combined_warnings
        and assessment.delta_milli_litres is not None
        and assessment.delta_milli_litres > 0
    )
    if establishes_baseline or reconciled_fill:
        update_global_meter_after_fill(
            session,
            global_meter_state,
            record,
            employee,
            vehicle,
            now,
        )
    else:
        advance_global_meter_revision(session, global_meter_state)
    return record


def preview_meter_reading(
    session: Session,
    request: MeterReadingPreviewRequest,
) -> dict[str, object]:
    try:
        cumulative_total = parse_total_raw_digits(
            request.cumulative_total_raw_digits
        )
    except InvalidMeterDigits as error:
        raise FuelSubmissionError(str(error)) from error
    global_meter_state = get_or_create_global_meter_state(session)
    previous_total = global_meter_state.current_total_integer
    assessment = assess_meter_readings(
        fill_milli_litres=None,
        previous_total_milli_litres=previous_total,
        cumulative_total_milli_litres=cumulative_total,
        source="MANUAL",
    )
    return {
        "fill_milli_litres": assessment.fill_milli_litres,
        "previous_total_litres": (
            float(milli_litres_to_decimal(assessment.previous_total_milli_litres))
            if assessment.previous_total_milli_litres is not None
            else None
        ),
        "previous_total_milli_litres": assessment.previous_total_milli_litres,
        "cumulative_total_litres": float(milli_litres_to_decimal(cumulative_total)),
        "cumulative_total_milli_litres": cumulative_total,
        "delta_litres": (
            float(milli_litres_to_decimal(assessment.delta_milli_litres))
            if assessment.delta_milli_litres is not None
            else None
        ),
        "delta_milli_litres": assessment.delta_milli_litres,
        "fill_calculation": assessment.fill_calculation,
        "fill_source": assessment.fill_source,
        "reading_source": assessment.source,
        "reconciliation_status": assessment.reconciliation_status,
        "warnings": list(assessment.warnings),
    }


def list_meter_reading_reviews(
    session: Session, *, status: str = "pending"
) -> list[MeterReadingReview]:
    return list(
        session.scalars(
            select(MeterReadingReview)
            .where(MeterReadingReview.status == status)
            .order_by(
                MeterReadingReview.submitted_at.asc(),
                MeterReadingReview.id.asc(),
            )
        )
    )


def decide_meter_reading_review(
    session: Session,
    reviewer: Employee,
    review_id: int,
    decision: str,
    note: str,
) -> MeterReadingReview:
    review = session.scalar(
        select(MeterReadingReview)
        .where(MeterReadingReview.id == review_id)
        .with_for_update()
    )
    if review is None:
        raise FuelSubmissionError("Meter reading review not found.")
    if review.status != "pending":
        raise FuelSubmissionError("This meter reading review is already closed.")
    now = datetime.now(timezone.utc)
    if decision == "reject":
        review.status = "rejected"
        review.reviewed_at = now
        review.reviewed_by_employee_id = reviewer.id
        review.review_note = note
        return review
    if decision != "approve":
        raise FuelSubmissionError("Choose approve or reject.")
    if review.cumulative_total_integer is None:
        raise FuelSubmissionError(
            "This reading has no usable global total. Reject it and submit a legible reading."
        )

    global_meter_state = get_or_create_global_meter_state(session)
    if global_meter_state.revision != review.global_meter_revision:
        raise GlobalMeterConcurrentUpdate(
            "The global meter has changed since this reading was submitted. "
            "Do not approve stale evidence; ask the employee to verify the current meter."
        )
    employee = session.get(Employee, review.employee_id)
    vehicle = session.get(Vehicle, review.vehicle_id)
    if employee is None or vehicle is None:
        raise FuelSubmissionError(
            "The employee or vehicle no longer exists; this review cannot be approved."
        )
    if (
        vehicle.fuel_type not in {"Diesel", "AdBlue", "Petrol"}
        or vehicle.tank_capacity is None
        or vehicle.tank_capacity <= 0
    ):
        raise FuelSubmissionError(
            "The vehicle's fuel type or tank capacity is no longer valid."
        )
    odometer_correction = (
        session.get(VehicleOdometerCorrection, review.odometer_correction_id)
        if review.odometer_correction_id is not None
        else None
    )
    if review.odometer_correction_id is not None and (
        odometer_correction is None
        or odometer_correction.used_at is not None
        or odometer_correction.authorized_odometer_miles != review.odometer_miles
    ):
        raise FuelSubmissionError(
            "The odometer correction is no longer available for this review."
        )
    previous_total = global_meter_state.current_total_integer
    if previous_total is None:
        if global_meter_state.current_cumulative_total_litres is not None:
            raise FuelSubmissionError(
                "The existing global total has no exact milli-litre value; "
                "it cannot be replaced by an inferred baseline."
            )
        fill_milli_litres = (
            review.current_fill_milli_litres
            or review.top_current_fill_milli_litres
        )
        if (
            vehicle.tank_capacity is None
            or vehicle.tank_capacity <= 0
            or fill_milli_litres is None
            or fill_milli_litres <= 0
            or fill_milli_litres > MAX_FILL_MILLI_LITRES
            or fill_milli_litres > vehicle.tank_capacity * 1000
        ):
            raise FuelSubmissionError(
                "The baseline fill is invalid or exceeds the vehicle tank capacity."
            )
        if review.meter_photo_id is not None and session.scalar(
            select(FuelRecord.id).where(
                FuelRecord.meter_photo_id == review.meter_photo_id
            )
        ):
            raise FuelSubmissionError(
                "This meter photo is already linked to a fuel record."
            )
        fill_value = milli_litres_to_decimal(fill_milli_litres)
        if fill_value is None:
            raise FuelSubmissionError("The baseline fill could not be calculated.")
        baseline_event = create_global_meter_event(
            session,
            reviewer,
            "baseline",
            Decimal(review.cumulative_total_integer).scaleb(-3),
            note,
        )
        baseline_event.baseline_total_raw_digits = (
            review.cumulative_total_raw_digits
        )
        first_name, _, surname = employee.name.partition(" ")
        total_value = float(
            milli_litres_to_decimal(review.cumulative_total_integer)
        )
        record = FuelRecord(
            reg_number=vehicle.registration_number,
            fuel_type=vehicle.fuel_type,
            first_name=first_name,
            surname=surname,
            mileage_miles=review.odometer_miles,
            capacity=vehicle.tank_capacity,
            litres=float(fill_value),
            cost=0,
            employee_id=employee.id,
            vehicle_id=vehicle.id,
            cumulative_meter_reading=total_value,
            current_fill_litres=float(fill_value),
            cumulative_total_litres=total_value,
            current_fill_milli_litres=fill_milli_litres,
            top_current_fill_milli_litres=(
                review.top_current_fill_milli_litres
            ),
            cumulative_total_integer=review.cumulative_total_integer,
            current_fill_raw_digits=review.current_fill_raw_digits,
            cumulative_total_raw_digits=review.cumulative_total_raw_digits,
            meter_reading_source=review.fill_source or review.reading_source,
            reading_source=review.reading_source,
            fill_calculation=review.fill_calculation,
            meter_check_status="baseline",
            meter_warnings=review.warnings,
            meter_epoch=vehicle.meter_epoch,
            meter_photo_id=review.meter_photo_id,
            odometer_correction_id=review.odometer_correction_id,
            is_demo=employee.is_demo,
            demo_key=(
                f"global-meter-test:{employee.username or employee.id}:"
                f"{review.meter_photo_id}"
                if employee.is_demo and review.meter_photo_id is not None
                else None
            ),
            created_at=now,
        )
        session.add(record)
        session.flush()
        if odometer_correction is not None:
            odometer_correction.used_by_employee_id = employee.id
            odometer_correction.used_at = now
        update_global_meter_after_fill(
            session,
            global_meter_state,
            record,
            employee,
            vehicle,
            now,
        )
        review.status = "approved"
        review.reviewed_at = now
        review.reviewed_by_employee_id = reviewer.id
        review.review_note = note
        review.global_meter_event_id = baseline_event.id
        review.fuel_record_id = record.id
        return review
    assessment = assess_meter_readings(
        fill_milli_litres=review.top_current_fill_milli_litres,
        previous_total_milli_litres=previous_total,
        cumulative_total_milli_litres=review.cumulative_total_integer,
        source=review.reading_source,
    )
    if assessment.delta_milli_litres is not None and assessment.delta_milli_litres <= 0:
        raise FuelSubmissionError(
            "A lower or unchanged global total cannot be approved as a fill. "
            "Record an authorized meter replacement/reset event first."
        )
    if assessment.fill_milli_litres is None or assessment.fill_milli_litres <= 0:
        raise FuelSubmissionError(
            "A positive fill is required. Reject this reading or ask the employee to correct it."
        )
    fill_value = milli_litres_to_decimal(assessment.fill_milli_litres)
    if fill_value is None:
        raise FuelSubmissionError("The fill amount could not be calculated.")
    assessment = assess_meter_readings(
        fill_milli_litres=review.top_current_fill_milli_litres,
        previous_total_milli_litres=previous_total,
        cumulative_total_milli_litres=review.cumulative_total_integer,
        source=review.reading_source,
        tank_capacity_litres=vehicle.tank_capacity,
    )
    if (
        assessment.fill_milli_litres is None
        or assessment.fill_milli_litres <= 0
        or assessment.fill_milli_litres > MAX_FILL_MILLI_LITRES
        or assessment.fill_milli_litres > vehicle.tank_capacity * 1000
    ):
        raise FuelSubmissionError(
            "The reviewed fill is invalid or exceeds the vehicle tank capacity."
        )
    if review.meter_photo_id is not None and session.scalar(
        select(FuelRecord.id).where(
            FuelRecord.meter_photo_id == review.meter_photo_id
        )
    ):
        raise FuelSubmissionError(
            "This meter photo is already linked to a fuel record."
        )

    first_name, _, surname = employee.name.partition(" ")
    fill_litres = float(fill_value)
    total_litres = float(
        milli_litres_to_decimal(review.cumulative_total_integer)
    )
    meter_delta = (
        float(milli_litres_to_decimal(assessment.delta_milli_litres))
        if assessment.delta_milli_litres is not None
        else None
    )
    record = FuelRecord(
        reg_number=vehicle.registration_number,
        fuel_type=vehicle.fuel_type,
        first_name=first_name,
        surname=surname,
        mileage_miles=review.odometer_miles,
        capacity=vehicle.tank_capacity,
        litres=fill_litres,
        cost=0,
        employee_id=employee.id,
        vehicle_id=vehicle.id,
        cumulative_meter_reading=total_litres,
        current_fill_litres=fill_litres,
        cumulative_total_litres=total_litres,
        meter_delta_litres=meter_delta,
        current_fill_milli_litres=assessment.fill_milli_litres,
        top_current_fill_milli_litres=assessment.top_current_fill_milli_litres,
        cumulative_total_integer=review.cumulative_total_integer,
        previous_global_total_integer=previous_total,
        current_fill_raw_digits=review.current_fill_raw_digits,
        cumulative_total_raw_digits=review.cumulative_total_raw_digits,
        meter_reading_source=assessment.fill_source or assessment.source,
        reading_source=assessment.source,
        fill_calculation=assessment.fill_calculation,
        meter_check_status=(
            "baseline"
            if previous_total is None
            else "matched"
            if assessment.reconciliation_status == "reconciled"
            else "discrepancy"
        ),
        meter_warnings=review.warnings,
        meter_epoch=vehicle.meter_epoch,
        meter_photo_id=review.meter_photo_id,
        odometer_correction_id=review.odometer_correction_id,
        is_demo=employee.is_demo,
        demo_key=(
            f"global-meter-test:{employee.username or employee.id}:"
            f"{review.meter_photo_id}"
            if employee.is_demo and review.meter_photo_id is not None
            else None
        ),
        created_at=now,
    )
    session.add(record)
    session.flush()
    if odometer_correction is not None:
        odometer_correction.used_by_employee_id = employee.id
        odometer_correction.used_at = now
    update_global_meter_after_fill(
        session,
        global_meter_state,
        record,
        employee,
        vehicle,
        now,
    )
    review.status = "approved"
    review.reviewed_at = now
    review.reviewed_by_employee_id = reviewer.id
    review.review_note = note
    review.fuel_record_id = record.id
    return review
