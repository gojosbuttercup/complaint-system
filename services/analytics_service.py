from datetime import datetime, timedelta


def build_dashboard_data(complaints, departments):
    category_counts = {}
    urgency_counts = {}
    status_counts = {}
    department_counts = {department: 0 for department in departments}
    resolved_durations = []

    for complaint in complaints:
        category_counts[complaint.category] = category_counts.get(complaint.category, 0) + 1
        urgency_counts[complaint.urgency] = urgency_counts.get(complaint.urgency, 0) + 1
        status_counts[complaint.status] = status_counts.get(complaint.status, 0) + 1
        department_counts[complaint.department] = department_counts.get(complaint.department, 0) + 1
        if complaint.resolved_at and complaint.timestamp:
            resolved_durations.append((complaint.resolved_at - complaint.timestamp).total_seconds() / 3600)

    today = datetime.utcnow().date()
    daily_labels = []
    daily_counts = []
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        daily_labels.append(day.strftime("%m/%d"))
        daily_counts.append(sum(1 for c in complaints if c.timestamp.date() == day))

    avg_resolution_hours = round(sum(resolved_durations) / len(resolved_durations), 1) if resolved_durations else 0

    return {
        "category_counts": category_counts,
        "urgency_counts": urgency_counts,
        "status_counts": status_counts,
        "department_counts": department_counts,
        "daily_labels": daily_labels,
        "daily_counts": daily_counts,
        "avg_resolution_hours": avg_resolution_hours,
        "resolved_vs_pending": {
            "resolved": status_counts.get("resolved", 0),
            "pending": len(complaints) - status_counts.get("resolved", 0),
        },
    }
