import re
import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Employee, UserRole
from documentRequest.models import DocumentRequest
from leave.models import Leave
from orgSetup.models import EmployeeIDPrefix, OrganizationProfile, ReportingTree, WeekendSettings
from reimbursement.models import Reimbursement
from separation.models import Separation
from timelog.models import TimeLog
from timesheet.models import TimeSheet

from .services import classify_chat_intent, format_scoped_answer, invoke_bedrock_chat

logger = logging.getLogger(__name__)

GREETING_WORDS = {
    "hi",
    "hello",
    "hey",
    "hii",
    "hiii",
    "helo",
    "hola",
    "yo",
    "sup",
    "whats up",
    "what's up",
    "good day",
    "good night",
    "bye",
    "goodbye",
    "see you",
    "good morning",
    "good afternoon",
    "good evening",
    "thanks",
    "thank you",
    "thankyou",
    "ok thanks",
    "okay thanks",
}

ATTENDANCE_PRESENT_STATUSES = ["Present", "Remote", "Half Day"]
OUT_OF_SCOPE_KEYWORDS = {
    "place",
    "places",
    "city",
    "country",
    "tourist",
    "tourism",
    "travel",
    "weather",
    "restaurant",
    "movie",
    "song",
    "actor",
    "temple",
    "beach",
    "history of",
    "capital of",
    "tell me about",
}


def leave_summary(leave_obj):
    employee = leave_obj.employee
    return {
        "employee_id": employee.employee_id,
        "name": f"{employee.first_name} {employee.last_name}".strip(),
        "leave_type": getattr(leave_obj.leave_type, "leave_type", str(leave_obj.leave_type)),
        "from_date": str(leave_obj.from_date),
        "to_date": str(leave_obj.to_date),
        "status": leave_obj.status,
        "reason": leave_obj.reason,
        "department": employee.department.name if employee.department else "",
    }


def format_percentage(value):
    return f"{value:.1f}%"


def format_time_value(value):
    if not value:
        return "not available"
    text = str(value)
    return text[:5] if len(text) >= 5 else text


def get_attendance_percentage_for_range(organization, employee, start_date, end_date):
    logs = TimeLog.objects.filter(
        organization=organization,
        employee=employee,
        punch_date__range=[start_date, end_date],
    )
    total_days = logs.count()
    if total_days == 0:
        return 0.0
    present_days = logs.filter(work_status__in=ATTENDANCE_PRESENT_STATUSES).count()
    return (present_days / total_days) * 100


def get_scope_attendance_percentage(organization, start_date, end_date, employee_ids=None):
    filters = {
        "organization": organization,
        "punch_date__range": [start_date, end_date],
    }
    if employee_ids is not None:
        filters["employee_id__in"] = employee_ids

    logs = TimeLog.objects.filter(**filters)
    total_days = logs.count()
    if total_days == 0:
        return 0.0
    present_days = logs.filter(work_status__in=ATTENDANCE_PRESENT_STATUSES).count()
    return (present_days / total_days) * 100


def is_out_of_scope_question(question):
    q = question.strip().lower()
    if not q:
        return False

    hrms_keywords = [
        "employee",
        "attendance",
        "leave",
        "timesheet",
        "reimbursement",
        "document",
        "payroll",
        "payslip",
        "reportee",
        "team",
        "branch",
        "department",
        "designation",
        "shift",
        "holiday",
        "weekend",
        "prefix",
        "separation",
        "loan",
        "task",
        "goal",
        "approval",
        "report",
        "firstclick",
        "mobile",
        "email",
        "employee id",
        "punch",
    ]
    if any(keyword in q for keyword in hrms_keywords):
        return False

    return any(keyword in q for keyword in OUT_OF_SCOPE_KEYWORDS)


def out_of_scope_response():
    return (
        "I am an AI chatbot designed for FirstClick. "
        "I can help only with FirstClick HRMS and work-related questions, so I cannot answer questions like that."
    )


def insufficient_data_response():
    return "Sorry, I do not have enough data to answer that right now."


def build_daily_attendance_lines(organization, employee, end_date, days=7):
    start_date = end_date - timedelta(days=days - 1)
    logs = (
        TimeLog.objects
        .filter(
            organization=organization,
            employee=employee,
            punch_date__range=[start_date, end_date],
        )
        .order_by("-punch_date")
    )
    return [
        {
            "date": str(log.punch_date),
            "status": log.work_status,
            "punch_in": format_time_value(log.punch_in_time),
            "punch_out": format_time_value(log.punch_out_time),
        }
        for log in logs[:days]
    ]


def resolve_employee_from_question(question, organization, role, current_employee=None):
    employee_ids = re.findall(r"\b[A-Za-z]{2,}\d+\b", question.upper())
    if not employee_ids:
        return None, None

    target = (
        Employee.objects
        .filter(organization=organization, employee_id__in=employee_ids)
        .select_related("department", "designation", "branch", "work_shift")
        .first()
    )
    if not target:
        return None, f"No employee was found for ID {employee_ids[0]}."

    role_label = get_role_label(role)
    if role_label == "Admin":
        return target, None
    if role_label == "Manager" and current_employee:
        is_allowed = ReportingTree.objects.filter(
            organization=organization,
            manager=current_employee,
            reportee=target,
        ).exists() or target.id == current_employee.id
        if is_allowed:
            return target, None
        return None, "You do not have access to that employee's data."
    if current_employee and target.id == current_employee.id:
        return target, None
    return None, "You do not have access to that employee's data."


def build_target_employee_summary(target_employee, organization, today):
    today_log = (
        TimeLog.objects
        .filter(organization=organization, employee=target_employee, punch_date=today)
        .order_by("-updated_at")
        .first()
    )
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)

    pending_requests = {
        "leave": Leave.objects.filter(
            organization=organization, employee=target_employee, status="Pending"
        ).count(),
        "timesheet": TimeSheet.objects.filter(
            organization=organization, employee=target_employee, manager_approval="Pending"
        ).count(),
        "reimbursement": Reimbursement.objects.filter(
            organization=organization, employee=target_employee, reimbursement_status="Pending"
        ).count(),
        "document": DocumentRequest.objects.filter(
            organization=organization, employee=target_employee, status="Pending"
        ).count(),
        "separation": Separation.objects.filter(
            organization=organization, employee=target_employee, status="Pending"
        ).count(),
    }

    return {
        "employee_id": target_employee.employee_id,
        "name": target_employee.get_full_name(),
        "email": target_employee.email_id,
        "mobile_number": target_employee.phone_no,
        "department": target_employee.department.name if target_employee.department else "",
        "designation": target_employee.designation.name if target_employee.designation else "",
        "branch": target_employee.branch.name if target_employee.branch else "",
        "work_shift": target_employee.work_shift.name if target_employee.work_shift else "",
        "today_status": today_log.work_status if today_log else "No log",
        "today_punch_in": format_time_value(today_log.punch_in_time if today_log else None),
        "today_punch_out": format_time_value(today_log.punch_out_time if today_log else None),
        "attendance_percentage": {
            "week": format_percentage(
                get_attendance_percentage_for_range(organization, target_employee, week_start, today)
            ),
            "month": format_percentage(
                get_attendance_percentage_for_range(organization, target_employee, month_start, today)
            ),
            "year": format_percentage(
                get_attendance_percentage_for_range(organization, target_employee, year_start, today)
            ),
        },
        "daily_attendance": build_daily_attendance_lines(organization, target_employee, today, days=7),
        "pending_requests": pending_requests,
    }


def build_pending_requests_payload(target_employee, organization):
    return {
        "employee_id": target_employee.employee_id,
        "name": target_employee.get_full_name(),
        "pending_requests": {
            "leave": Leave.objects.filter(
                organization=organization, employee=target_employee, status="Pending"
            ).count(),
            "timesheet": TimeSheet.objects.filter(
                organization=organization, employee=target_employee, manager_approval="Pending"
            ).count(),
            "reimbursement": Reimbursement.objects.filter(
                organization=organization, employee=target_employee, reimbursement_status="Pending"
            ).count(),
            "document": DocumentRequest.objects.filter(
                organization=organization, employee=target_employee, status="Pending"
            ).count(),
            "separation": Separation.objects.filter(
                organization=organization, employee=target_employee, status="Pending"
            ).count(),
        },
    }


def build_employee_field_payload(target_employee, organization, today):
    summary = build_target_employee_summary(target_employee, organization, today)
    return {
        "employee_id": summary["employee_id"],
        "name": summary["name"],
        "email": summary["email"],
        "mobile_number": summary["mobile_number"],
        "department": summary["department"],
        "designation": summary["designation"],
        "branch": summary["branch"],
        "work_shift": summary["work_shift"],
        "today_status": summary["today_status"],
        "today_punch_in": summary["today_punch_in"],
        "today_punch_out": summary["today_punch_out"],
    }



def build_attendance_payload(target_employee, organization, today):
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    today_log = (
        TimeLog.objects
        .filter(organization=organization, employee=target_employee, punch_date=today)
        .order_by("-updated_at")
        .first()
    )
    return {
        "employee_id": target_employee.employee_id,
        "name": target_employee.get_full_name(),
        "today": {
            "status": today_log.work_status if today_log else "No log",
            "punch_in": format_time_value(today_log.punch_in_time if today_log else None),
            "punch_out": format_time_value(today_log.punch_out_time if today_log else None),
        },
        "attendance_percentage": {
            "week": format_percentage(
                get_attendance_percentage_for_range(organization, target_employee, week_start, today)
            ),
            "month": format_percentage(
                get_attendance_percentage_for_range(organization, target_employee, month_start, today)
            ),
            "year": format_percentage(
                get_attendance_percentage_for_range(organization, target_employee, year_start, today)
            ),
        },
        "daily_attendance": build_daily_attendance_lines(organization, target_employee, today, days=7),
    }


def build_role_scoped_attendance_percentage_payload(role_label, organization, today, employee=None):
    timeframe = {
        "today": (today, today),
        "weekly": (today - timedelta(days=today.weekday()), today),
        "monthly": (today.replace(day=1), today),
        "yearly": (today.replace(month=1, day=1), today),
    }

    if role_label == "Admin":
        return {
            "scope_label": "organization",
            "attendance_percentage": {
                key: format_percentage(get_scope_attendance_percentage(organization, start, end))
                for key, (start, end) in timeframe.items()
            },
        }

    if role_label == "Manager" and employee:
        reportee_ids = list(
            ReportingTree.objects.filter(organization=organization, manager=employee)
            .values_list("reportee_id", flat=True)
        )
        allowed_ids = reportee_ids + [employee.id]
        return {
            "scope_label": "your team",
            "attendance_percentage": {
                key: format_percentage(get_scope_attendance_percentage(organization, start, end, employee_ids=allowed_ids))
                for key, (start, end) in timeframe.items()
            },
        }

    if employee:
        return {
            "scope_label": "yourself",
            "attendance_percentage": {
                "today": format_percentage(
                    100.0 if (employee_summary(employee, organization, today).get("today_attendance_status") in ATTENDANCE_PRESENT_STATUSES)
                    else 50.0 if employee_summary(employee, organization, today).get("today_attendance_status") == "Half Day"
                    else 0.0
                ),
                "weekly": format_percentage(get_attendance_percentage_for_range(organization, employee, timeframe["weekly"][0], timeframe["weekly"][1])),
                "monthly": format_percentage(get_attendance_percentage_for_range(organization, employee, timeframe["monthly"][0], timeframe["monthly"][1])),
                "yearly": format_percentage(get_attendance_percentage_for_range(organization, employee, timeframe["yearly"][0], timeframe["yearly"][1])),
            },
        }

    return {
        "scope_label": "yourself",
        "attendance_percentage": {
            "today": "0.0%",
            "weekly": "0.0%",
            "monthly": "0.0%",
            "yearly": "0.0%",
        },
    }



def format_target_employee_summary(summary):
    pending = summary["pending_requests"]
    lines = [
        f"Employee details for {summary['employee_id']}:",
        f"Name: {summary['name']}",
        f"Email: {summary['email']}",
        f"Mobile number: {summary['mobile_number']}",
        f"Department: {summary['department'] or 'Not assigned'}",
        f"Designation: {summary['designation'] or 'Not assigned'}",
        f"Branch: {summary['branch'] or 'Not assigned'}",
        f"Work shift: {summary['work_shift'] or 'Not assigned'}",
        "",
        "Pending requests:",
        f"- Leave: {pending['leave']}",
        f"- Timesheet: {pending['timesheet']}",
        f"- Reimbursement: {pending['reimbursement']}",
        f"- Document requests: {pending['document']}",
        f"- Separation: {pending['separation']}",
        "",
        "Attendance:",
        f"- Today: {summary['today_status']}",
        f"- Punch in: {summary['today_punch_in']}",
        f"- Punch out: {summary['today_punch_out']}",
        f"- Weekly attendance percentage: {summary['attendance_percentage']['week']}",
        f"- Monthly attendance percentage: {summary['attendance_percentage']['month']}",
        f"- Yearly attendance percentage: {summary['attendance_percentage']['year']}",
    ]

    if summary["daily_attendance"]:
        lines.extend(["", "Daily attendance (recent days):"])
        for item in summary["daily_attendance"]:
            lines.append(
                f"- {item['date']}: {item['status']} | In: {item['punch_in']} | Out: {item['punch_out']}"
            )

    return "\n".join(lines)



def build_org_pending_requests_payload(organization):
    return {
        "pending_requests": {
            "leave": Leave.objects.filter(organization=organization, status="Pending").count(),
            "timesheet": TimeSheet.objects.filter(organization=organization, manager_approval="Pending").count(),
            "reimbursement": Reimbursement.objects.filter(organization=organization, reimbursement_status="Pending").count(),
            "document": DocumentRequest.objects.filter(organization=organization, status="Pending").count(),
            "separation": Separation.objects.filter(organization=organization, status="Pending").count(),
        }
    }



def build_org_today_punch_payload(organization, today):
    logs = (
        TimeLog.objects
        .filter(organization=organization, punch_date=today)
        .select_related("employee")
        .order_by("employee__first_name", "employee__last_name")[:25]
    )
    return {
        "date": str(today),
        "entries": [
            {
                "employee_id": log.employee.employee_id,
                "name": log.employee.get_full_name(),
                "status": log.work_status,
                "punch_in": format_time_value(log.punch_in_time),
                "punch_out": format_time_value(log.punch_out_time),
            }
            for log in logs
        ],
    }



def build_weekend_settings_payload(organization):
    weekend_settings = (
        WeekendSettings.objects
        .filter(organization=organization)
        .order_by("-id")
        .first()
    )
    weekends = weekend_settings.weekends if weekend_settings and weekend_settings.weekends else []
    return {
        "organization": organization.organization_name or "Organization",
        "weekends": weekends,
    }


def build_employee_id_prefix_payload(organization):
    prefix_obj = (
        EmployeeIDPrefix.objects
        .filter(organization=organization)
        .order_by("-id")
        .first()
    )
    return {
        "organization": organization.organization_name or "Organization",
        "prefix": prefix_obj.prefix if prefix_obj and prefix_obj.prefix else "Not configured",
    }



def format_self_field_fallback(self_payload, field_name):
    field_map = {
        "employee_id": ("Your employee ID", self_payload.get("employee_id") or "Not available"),
        "name": ("Your name", self_payload.get("name") or "Not available"),
        "email": ("Your email", self_payload.get("email") or "Not available"),
        "mobile_number": ("Your mobile number", self_payload.get("mobile_number") or "Not available"),
        "department": ("Your department", self_payload.get("department") or "Not assigned"),
        "designation": ("Your designation", self_payload.get("designation") or "Not assigned"),
        "branch": ("Your branch", self_payload.get("branch") or "Not assigned"),
        "work_shift": ("Your work shift", self_payload.get("work_shift") or "Not assigned"),
        "today_attendance_status": ("Your attendance status today", self_payload.get("today_attendance_status") or "No log"),
        "today_punch_in": ("Your punch in today", format_time_value(self_payload.get("today_punch_in"))),
        "today_punch_out": ("Your punch out today", format_time_value(self_payload.get("today_punch_out"))),
    }
    label, value = field_map[field_name]
    return f"{label}: {value}"



def build_attendance_status_payload(organization, target_date, status_value, employee_ids=None):
    filters = {
        "organization": organization,
        "punch_date": target_date,
        "work_status": status_value,
    }
    if employee_ids is not None:
        filters["employee_id__in"] = employee_ids

    logs = (
        TimeLog.objects
        .filter(**filters)
        .select_related("employee", "employee__department")
        .order_by("employee__first_name", "employee__last_name")[:50]
    )
    return {
        "date": str(target_date),
        "status": status_value,
        "entries": [
            {
                "employee_id": log.employee.employee_id,
                "name": log.employee.get_full_name(),
                "department": log.employee.department.name if log.employee.department else "",
            }
            for log in logs
        ],
    }


def build_today_attendance_overview_payload(organization, target_date, employee_ids=None):
    employee_filters = {"organization": organization}
    if employee_ids is not None:
        employee_filters["id__in"] = employee_ids

    employees = list(
        Employee.objects
        .filter(**employee_filters)
        .select_related("department")
        .order_by("first_name", "last_name", "employee_id")
    )

    log_filters = {
        "organization": organization,
        "punch_date": target_date,
    }
    if employee_ids is not None:
        log_filters["employee_id__in"] = employee_ids

    logs = (
        TimeLog.objects
        .filter(**log_filters)
        .select_related("employee", "employee__department")
        .order_by("employee_id", "-updated_at", "-id")
    )

    latest_log_by_employee_id = {}
    for log in logs:
        if log.employee_id not in latest_log_by_employee_id:
            latest_log_by_employee_id[log.employee_id] = log

    present_entries = []
    absentee_entries = []

    for emp in employees:
        log = latest_log_by_employee_id.get(emp.id)
        status_text = (getattr(log, "work_status", "") or "").strip()
        department_name = ""
        if emp.department:
            department_name = getattr(emp.department, "name", "") or getattr(emp.department, "department_name", "")

        entry = {
            "employee_id": emp.employee_id,
            "name": emp.get_full_name() or f"{emp.first_name} {emp.last_name}".strip(),
            "department": department_name,
            "status": status_text or "No Status",
        }

        if status_text in ATTENDANCE_PRESENT_STATUSES:
            present_entries.append(entry)
        else:
            absentee_entries.append(entry)

    return {
        "date": str(target_date),
        "present_count": len(present_entries),
        "absent_count": len(absentee_entries),
        "present_employees": present_entries,
        "absentees": absentee_entries,
    }


def format_today_attendance_overview_fallback(payload, role_label):
    present_entries = payload.get("present_employees", [])
    absentee_entries = payload.get("absentees", [])
    scope_suffix = " across the organization" if role_label == "Admin" else ""

    def format_names(entries):
        return ", ".join(
            f"{item['name']} ({item['status']})" if item.get("status") else item["name"]
            for item in entries
        )

    present_text = (
        format_names(present_entries)
        if present_entries
        else "No employees are marked present today."
    )
    absentee_text = (
        format_names(absentee_entries)
        if absentee_entries
        else "No absentees found for today."
    )

    return (
        f"Today's attendance list{scope_suffix}: "
        f"Present ({len(present_entries)}): {present_text}. "
        f"Absentees ({len(absentee_entries)}): {absentee_text}."
    )



def employee_summary(emp, organization, today):
    if not emp:
        return {}

    today_log = (
        TimeLog.objects
        .filter(organization=organization, employee=emp, punch_date=today)
        .order_by("-updated_at")
        .first()
    )

    return {
        "employee_id": emp.employee_id,
        "name": f"{emp.first_name} {emp.last_name}".strip(),
        "email": emp.email_id,
        "mobile_number": emp.phone_no,
        "department": emp.department.name if emp.department else "",
        "designation": emp.designation.name if emp.designation else "",
        "branch": emp.branch.name if emp.branch else "",
        "work_shift": emp.work_shift.name if emp.work_shift else "",
        "today_attendance_status": today_log.work_status if today_log else "No log",
        "today_punch_in": str(today_log.punch_in_time) if today_log and today_log.punch_in_time else "",
        "today_punch_out": str(today_log.punch_out_time) if today_log and today_log.punch_out_time else "",
        "pending_leave_count": Leave.objects.filter(
            organization=organization, employee=emp, status="Pending"
        ).count(),
        "approved_leave_count": Leave.objects.filter(
            organization=organization, employee=emp, status="Approved"
        ).count(),
        "pending_timesheet_count": TimeSheet.objects.filter(
            organization=organization, employee=emp, manager_approval="Pending"
        ).count(),
    }


def get_role_label(role):
    if role in (UserRole.ADMIN, "Admin"):
        return "Admin"
    if role == UserRole.MANAGER:
        return "Manager"
    return "Default"


def is_out_of_scope_question(question):
    q = question.lower()
    off_topic = [
        "recipe", "weather", "music", "joke", "movie", "news", 
        "price of", "buy", "sell", "market", "sport"
    ]
    return any(term in q for term in off_topic)

def out_of_scope_response():
    return "I am specialized in FirstClick HRMS data and company policies. I can't help with off-topic queries."

def insufficient_data_response():
    return "Sorry, I do not have enough data to answer that right now."

def format_today_leave_fallback(today_leave_list, role_label):
    if not today_leave_list:
        return "No employees are on approved leave today."
    names = ", ".join([item.get("employee_name", "Unknown") for item in today_leave_list])
    suffix = " (Organization-wide)" if role_label == "Admin" else " (Our team)"
    return f"Employees on leave today: {names}{suffix}"

def build_org_today_punch_payload(organization, today):
    employees = list(
        Employee.objects
        .filter(organization=organization)
        .select_related("department")
        .order_by("first_name", "last_name", "employee_id")
    )

    punch_qs = (
        TimeLog.objects
        .filter(
            organization=organization,
            punch_date=today,
        )
        .select_related("employee", "employee__department")
        .order_by("employee_id", "-updated_at", "-id")
    )

    latest_log_by_employee_id = {}
    for log in punch_qs:
        if log.employee_id not in latest_log_by_employee_id:
            latest_log_by_employee_id[log.employee_id] = log

    punched_in = []
    not_punched_in = []

    for emp in employees:
        log = latest_log_by_employee_id.get(emp.id)
        department_name = "N/A"
        if emp.department:
            department_name = getattr(emp.department, "department_name", "") or getattr(emp.department, "name", "") or "N/A"

        entry = {
            "employee_id": emp.employee_id,
            "employee_name": f"{emp.first_name} {emp.last_name}".strip(),
            "department": department_name,
            "status": (getattr(log, "work_status", "") or "No Status") if log else "No Status",
            "punch_in": str(log.punch_in_time) if log and log.punch_in_time else "Not punched in",
            "punch_out": str(log.punch_out_time) if log and log.punch_out_time else "Not punched out",
        }

        if log and log.punch_in_time:
            punched_in.append(entry)
        else:
            not_punched_in.append(entry)

    return {
        "date": str(today),
        "punched_in_count": len(punched_in),
        "not_punched_in_count": len(not_punched_in),
        "punched_in": punched_in,
        "not_punched_in": not_punched_in,
    }

def format_org_today_punch_fallback(payload):
    punched_in = payload.get("punched_in", []) if isinstance(payload, dict) else []
    not_punched_in = payload.get("not_punched_in", []) if isinstance(payload, dict) else []

    def format_names(entries, include_time=False):
        formatted = []
        for item in entries:
            if include_time:
                formatted.append(f"{item['employee_name']} ({item['punch_in']})")
            else:
                formatted.append(item["employee_name"])
        return ", ".join(formatted)

    punched_in_text = (
        format_names(punched_in, include_time=True)
        if punched_in
        else "No employees have punched in today."
    )
    not_punched_in_text = (
        format_names(not_punched_in)
        if not_punched_in
        else "Everyone has punched in today."
    )

    return (
        f"Today's punch details: "
        f"Punched in ({len(punched_in)}): {punched_in_text}. "
        f"Did not punch in ({len(not_punched_in)}): {not_punched_in_text}."
    )

def build_org_pending_requests_payload(organization):
    pending_leaves = Leave.objects.filter(organization=organization, status="Pending").count()
    pending_timesheets = TimeSheet.objects.filter(organization=organization, manager_approval="Pending").count()
    return {"pending_leaves": pending_leaves, "pending_timesheets": pending_timesheets}

def format_org_pending_requests_fallback(payload):
    return (
        f"You have {payload['pending_leaves']} pending leave requests "
        f"and {payload['pending_timesheets']} pending timesheet approvals across the organization."
    )

def build_employee_id_prefix_payload(organization):
    return {"prefix": organization.employee_id_prefix or "No prefix set"}

def format_employee_id_prefix_fallback(payload):
    return f"The employee ID prefix for your organization is: {payload['prefix']}"



def build_greeting_response(question, role):
    # We now let the AI handle greetings naturally for better "normal" feel.
    return None



def fallback_response(role, question, context):
    q = question.lower()
    role_label = get_role_label(role)
    today_leave_list = context.get("today_leave_list", [])

    if is_out_of_scope_question(question):
        return out_of_scope_response()

    if "access" in q or "who can" in q:
        if role_label == "Admin":
            return "As Admin, you can access organization-wide employee data and your own data."
        if role_label == "Manager":
            return "As Manager, you can access your own data and your reportees data only."
        return "As Employee, you can access only your own data."

    if "leave" in q and any(term in q for term in ["who", "which", "list", "show", "on leave", "leave today"]):
        return format_today_leave_fallback(today_leave_list, role_label)

    if "attendance list" in q and "today" in q:
        reportee_ids = None
        if role_label == "Manager" and context.get("self", {}).get("employee_id"):
            reportee_ids = list(
                ReportingTree.objects.filter(
                    organization=context["organization_obj"],
                    manager__employee_id=context["self"]["employee_id"],
                ).values_list("reportee_id", flat=True)
            )
        elif role_label == "Default" and context.get("self", {}).get("employee_id"):
            self_emp = Employee.objects.filter(
                organization=context["organization_obj"],
                employee_id=context["self"]["employee_id"],
            ).first()
            reportee_ids = [self_emp.id] if self_emp else []

        payload = build_today_attendance_overview_payload(
            context["organization_obj"],
            context["date_obj"],
            employee_ids=reportee_ids,
        )
        return format_today_attendance_overview_fallback(payload, role_label)

    if role_label == "Admin" and "punch" in q and "today" in q:
        payload = build_org_today_punch_payload(context["organization_obj"], context["date_obj"])
        return format_org_today_punch_fallback(payload)

    if role_label == "Admin" and "pending request" in q:
        payload = build_org_pending_requests_payload(context["organization_obj"])
        return format_org_pending_requests_fallback(payload)

    if "employee id prefix" in q or ("prefix" in q and "employee id" in q):
        payload = build_employee_id_prefix_payload(context["organization_obj"])
        return format_employee_id_prefix_fallback(payload)

    if "weekend" in q or "weekends" in q or "working day" in q or "working days" in q:
        payload = build_weekend_settings_payload(context["organization_obj"])
        return format_weekend_settings_fallback(payload)

    if "leave" in q and context.get("self"):
        return (
            f"You currently have {context['self'].get('pending_leave_count', 0)} pending leave request(s) "
            f"and {context['self'].get('approved_leave_count', 0)} approved leave record(s)."
        )

    if "attendance" in q and context.get("self"):
        return (
            f"Your attendance today is {context['self'].get('today_attendance_status', 'No log')}. "
            f"Punch in: {context['self'].get('today_punch_in') or 'not available'}. "
            f"Punch out: {context['self'].get('today_punch_out') or 'not available'}."
        )

    if role_label == "Manager" and ("reportee" in q or "team" in q):
        team_stats = context.get("team_stats", {})
        return (
            f"You have {team_stats.get('reportee_count', 0)} reportee(s), "
            f"{team_stats.get('pending_team_leaves', 0)} pending leave request(s), and "
            f"{team_stats.get('pending_team_timesheets', 0)} pending timesheet(s)."
        )

    if role_label == "Admin" and ("employee" in q or "organization" in q):
        org_stats = context.get("organization_stats", {})
        return (
            f"Organization summary: {org_stats.get('employee_count', 0)} employees, "
            f"{org_stats.get('present_today', 0)} present today, "
            f"{org_stats.get('on_leave_today', 0)} on approved leave today, and "
            f"{org_stats.get('pending_timesheets', 0)} pending timesheet(s)."
        )

    if "reportee" in q or "team" in q:
        reportees = context.get("reportees", [])
        if not reportees:
            return "No reportee data is available in your current scope."
        names = ", ".join(item.get("name") or item.get("employee_id") for item in reportees[:8])
        extra = len(reportees) - min(len(reportees), 8)
        suffix = f" and {extra} more." if extra > 0 else "."
        return f"Your accessible reportees are: {names}{suffix}"

    return (
        insufficient_data_response()
    )


def format_answer_with_model_or_fallback(question, role, payload, fallback_text, history=None):
    try:
        result = format_scoped_answer(question, role, payload, history=history)
        return result["answer"], result["model"]
    except Exception as e:
        logger.error(f"Chatbot generation failed, using fallback. Error: {str(e)}")
        return fallback_text, "fallback-assistant"


class ChatQueryView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        question = str(request.data.get("message", "")).strip()
        history = request.data.get("history", [])
        if not question:
            return Response({"error": "Message is required."}, status=status.HTTP_400_BAD_REQUEST)

        if is_out_of_scope_question(question):
            return Response({
                "answer": out_of_scope_response(),
                "role": "none",
                "model": "scope-guard",
            })

        user = request.user
        employee = (
            Employee.objects
            .filter(user=user)
            .select_related("organization", "department", "designation", "branch", "work_shift")
            .first()
        )

        organization = None
        role = "Admin" if hasattr(user, "organization_profile") else UserRole.DEFAULT
        if hasattr(user, "organization_profile"):
            organization = user.organization_profile
        elif employee and employee.organization:
            organization = employee.organization
            role = employee.user_role or UserRole.DEFAULT
        else:
            organization = OrganizationProfile.objects.filter(owner=user).first()

        if not organization:
            return Response(
                {"error": "Organization context not found for chatbot."},
                status=status.HTTP_403_FORBIDDEN,
            )

        today = timezone.now().date()
        context = {
            "role": role,
            "organization": organization.organization_name or "Organization",
            "date": str(today),
            "date_obj": today,
            "organization_obj": organization,
            "self": employee_summary(employee, organization, today),
            "today_leave_list": [],
        }

        if role == UserRole.ADMIN or role == "Admin":
            today_leave_qs = (
                Leave.objects
                .filter(
                    organization=organization,
                    status="Approved",
                    from_date__lte=today,
                    to_date__gte=today,
                )
                .select_related("employee", "employee__department", "leave_type")
                .order_by("employee__first_name", "employee__last_name")[:25]
            )
            context["today_leave_list"] = [leave_summary(item) for item in today_leave_qs]
            context["organization_stats"] = {
                "employee_count": Employee.objects.filter(organization=organization).count(),
                "present_today": TimeLog.objects.filter(
                    organization=organization, punch_date=today, work_status="Present"
                ).count(),
                "on_leave_today": Leave.objects.filter(
                    organization=organization, status="Approved", from_date__lte=today, to_date__gte=today
                ).count(),
                "pending_timesheets": TimeSheet.objects.filter(
                    organization=organization, manager_approval="Pending"
                ).count(),
            }
        elif role == UserRole.MANAGER:
            reportee_ids = list(
                ReportingTree.objects.filter(organization=organization, manager=employee)
                .values_list("reportee_id", flat=True)
            )
            reportees = Employee.objects.filter(
                organization=organization,
                id__in=reportee_ids,
            ).select_related("department", "designation", "branch", "work_shift")[:25]
            context["reportees"] = [employee_summary(emp, organization, today) for emp in reportees]
            context["team_stats"] = {
                "reportee_count": len(reportee_ids),
                "pending_team_leaves": Leave.objects.filter(
                    organization=organization, employee_id__in=reportee_ids, status="Pending"
                ).count(),
                "pending_team_timesheets": TimeSheet.objects.filter(
                    organization=organization, employee_id__in=reportee_ids, manager_approval="Pending"
                ).count(),
            }
            today_leave_qs = (
                Leave.objects
                .filter(
                    organization=organization,
                    employee_id__in=reportee_ids,
                    status="Approved",
                    from_date__lte=today,
                    to_date__gte=today,
                )
                .select_related("employee", "employee__department", "leave_type")
                .order_by("employee__first_name", "employee__last_name")[:25]
            )
            context["today_leave_list"] = [leave_summary(item) for item in today_leave_qs]
        elif employee:
            today_leave_qs = (
                Leave.objects
                .filter(
                    organization=organization,
                    employee=employee,
                    status="Approved",
                    from_date__lte=today,
                    to_date__gte=today,
                )
                .select_related("employee", "employee__department", "leave_type")[:5]
            )
            context["today_leave_list"] = [leave_summary(item) for item in today_leave_qs]

        # --- AI-FIRST AGENTIC FLOW ---
        has_employee_id = bool(re.findall(r"\b[A-Za-z]{2,}\d+\b", question.upper()))
        
        # 0. Shortcuts: For suggestions and very specific phrases
        q_low = question.lower()
        if role == UserRole.ADMIN:
            default_scope = "organization"
        elif role == UserRole.MANAGER:
            default_scope = "team"
        else:
            default_scope = "self"

        if "attendance list" in q_low and "today" in q_low:
            intent_payload = {"intent": "today_attendance_overview", "scope": default_scope, "timeframe": "today"}
        elif "approved leave" in q_low or "who all are on leave" in q_low or "on leave today" in q_low:
            intent_payload = {"intent": "leave_today", "scope": default_scope, "timeframe": "today"}
        elif "punch details" in q_low or "organization punch" in q_low or "who punched" in q_low:
            intent_payload = {"intent": "today_punch_details", "scope": default_scope, "timeframe": "today"}
        elif "pending approval" in q_low or "pending request" in q_low or "pending items" in q_low:
            intent_payload = {"intent": "organization_pending_requests", "scope": default_scope, "timeframe": "none"}
        else:
            # 1. Plan: Identify the user's goal via AI
            try:
                classified = classify_chat_intent(question, get_role_label(role), has_employee_id=has_employee_id, history=history)
                intent_payload = classified["data"]
                # Override scope if worker role is low
                if default_scope == "self":
                    intent_payload["scope"] = "self"
                elif default_scope == "team" and intent_payload.get("scope") == "organization":
                    intent_payload["scope"] = "team"
            except Exception:
                logger.exception("Chatbot intent classification failed for: %s", question)
                intent_payload = {"intent": "unknown", "scope": default_scope}

        intent = intent_payload.get("intent", "unknown")
        
        # 2. Greeting handling
        if intent == "greeting":
            greeting = build_greeting_response(question, role)
            if greeting:
                return Response(greeting)

        # 3. Resolve Target Employee scope
        target_employee, target_error = resolve_employee_from_question(question, organization, role, employee)
        
        # Use AI-inferred ID if regex fails
        if not target_employee and intent_payload.get("employee_id") and intent_payload.get("employee_id") != "none":
            inferred_id = intent_payload["employee_id"]
            target_employee = Employee.objects.filter(organization=organization, employee_id=inferred_id).first()
            if target_employee:
                target_error = None

        if intent_payload.get("scope") == "target_employee" and target_error:
            return Response({"answer": target_error, "role": role, "model": "guardrail"})

        # 4. Execute: Fetch only the necessary data "payload"
        payload = {}
        role_label = get_role_label(role)

        try:
            if intent == "leave_today":
                payload = {"on_leave_today": context.get("today_leave_list", [])}
                
            elif intent == "today_attendance_overview":
                reportee_ids = None
                if role_label == "Manager" and employee:
                    reportee_ids = list(
                        ReportingTree.objects.filter(organization=organization, manager=employee)
                        .values_list("reportee_id", flat=True)
                    )
                elif role_label == "Default" and employee:
                    reportee_ids = [employee.id]

                payload = build_today_attendance_overview_payload(
                    organization,
                    today,
                    employee_ids=reportee_ids,
                )

            elif intent == "attendance_status_list":
                timeframe = intent_payload.get("timeframe", "today")
                target_date = today - timedelta(days=1) if timeframe == "yesterday" else today
                status_value = intent_payload.get("status", "Absent")
                
                reportee_ids = None
                if role_label == "Manager" and "team_stats" in context:
                    reportee_ids = list(ReportingTree.objects.filter(organization=organization, manager=employee).values_list("reportee_id", flat=True))
                elif role_label == "Default" and employee:
                    reportee_ids = [employee.id]
                
                payload = build_attendance_status_payload(organization, target_date, status_value, employee_ids=reportee_ids)

            elif intent == "today_punch_details" and role_label == "Admin":
                payload = build_org_today_punch_payload(organization, today)

            elif intent == "organization_pending_requests" and role_label == "Admin":
                payload = build_org_pending_requests_payload(organization)

            elif intent == "company_weekends":
                payload = build_weekend_settings_payload(organization)

            elif intent == "employee_id_prefix":
                payload = build_employee_id_prefix_payload(organization)

            elif intent == "role_scoped_attendance_percentage":
                payload = build_role_scoped_attendance_percentage_payload(role_label, organization, today, employee=employee)

            elif intent == "team_reportees" and role_label == "Manager":
                payload = {"team_reportees": context.get("reportees", [])}

            elif intent.startswith("employee_") and target_employee:
                if intent == "employee_summary":
                    payload = build_target_employee_summary(target_employee, organization, today)
                elif intent == "employee_pending_requests":
                    payload = build_pending_requests_payload(target_employee, organization)
                elif intent in {"employee_attendance", "employee_attendance_percentage"}:
                    payload = build_attendance_payload(target_employee, organization, today)
                else:
                    # Field specific
                    payload = build_employee_field_payload(target_employee, organization, today)

            elif intent.startswith("self_") and context.get("self"):
                payload = {"your_details": context["self"]}

            elif intent == "unknown":
                # Fallback to general context
                payload = context
        except Exception:
            logger.exception("Data fetching failed for intent: %s", intent)
            payload = context

        # 5. Generate: Let Claude 3.5 Sonnet write the final answer using the payload
        try:
            answer, model_name = format_answer_with_model_or_fallback(
                question, 
                role_label, 
                payload or context, 
                fallback_response(role, question, context),
                history=history
            )
        except Exception as e:
            logger.error(f"Final generation failed: {str(e)}")
            answer, model_name = fallback_response(role, question, context), "fallback-error"

        return Response({
            "answer": answer,
            "role": role,
            "model": model_name,
            "suggested_action": intent_payload.get("suggested_action", "none"),
        })


class ChatbotVoiceTranscriptionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if "audio" not in request.FILES:
            return Response({"error": "Audio file is required."}, status=status.HTTP_400_BAD_REQUEST)

        audio_file = request.FILES["audio"]
        from decouple import config
        import requests

        # Collect all available Groq keys for rotation
        api_keys = [
            config("GROQ_API_KEY", default=None),
            config("GROQ_API_KEY_2", default=None),
            config("GROQ_API_KEY_3", default=None)
        ]
        api_keys = [k for k in api_keys if k]

        if not api_keys:
            logger.error("ChatbotVoiceTranscriptionView: No Groq API keys found in environment.")
            return Response({"error": "Voice service not configured."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        last_error = "Unknown error"

        # Try each key until one works (similar to chatbot logic)
        for api_key in api_keys:
            headers = {"Authorization": f"Bearer {api_key}"}
            files = {
                "file": (getattr(audio_file, 'name', 'voice.webm'), audio_file, "audio/webm"),
                "model": (None, "whisper-large-v3"),
                "language": (None, "en"),
                "response_format": (None, "json"),
            }

            try:
                logger.info(f"Attempting voice transcription with key {api_key[:10]}...")
                response = requests.post(url, headers=headers, files=files, timeout=20)
                
                if response.status_code == 200:
                    transcript = response.json().get("text", "")
                    logger.info("Transcription successful.")
                    return Response({"transcript": transcript}, status=status.HTTP_200_OK)
                
                # If rate limited or other API error, log and try next key
                last_error = f"API {response.status_code}: {response.text}"
                logger.warning(f"Key {api_key[:10]} failed: {last_error}")
                
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                logger.warning(f"Key {api_key[:10]} connection error: {last_error}")

class EmployeeCheckView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee_id = request.query_params.get("employee_id")
        if not employee_id:
            return Response({"error": "employee_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        organization = None
        current_emp = getattr(user, 'employee', None)

        if hasattr(user, 'organization_profile'):
            organization = user.organization_profile
        elif current_emp:
            organization = current_emp.organization

        if not organization:
            return Response({"error": "Organization not found."}, status=status.HTTP_404_NOT_FOUND)

        # Basic existence check within org
        target_employee = Employee.objects.filter(
            employee_id__iexact=employee_id,
            organization=organization
        ).first()

        if not target_employee:
            return Response({"exists": False}, status=status.HTTP_404_NOT_FOUND)

        # ROLE-BASED VISIBILITY CHECK
        # Managers can only see their team. Admins can see everyone.
        role = getattr(current_emp, 'user_role', 'Employee')
        is_staff = getattr(user, 'is_staff', False)
        
        if role == 'Manager' and not is_staff:
            # Check if target is a direct reportee
            is_in_team = ReportingTree.objects.filter(
                manager=current_emp,
                reportee=target_employee
            ).exists()
            
            # Also allow viewing self
            if not is_in_team and target_employee.id != current_emp.id:
                 return Response({
                     "exists": False, 
                     "error": "This employee is not in your reported team."
                 }, status=status.HTTP_403_FORBIDDEN)

        return Response({
            "exists": True,
            "name": f"{target_employee.first_name} {target_employee.last_name}".strip(),
            "id": target_employee.id
        }, status=status.HTTP_200_OK)
