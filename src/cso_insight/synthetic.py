"""Original synthetic fixture, never taken from an environmental source row."""

from datetime import datetime, timedelta

from cso_insight.linkage import NOTIFICATION, VERIFIED, SourceRow


def synthetic_rows() -> list[SourceRow]:
    rows: list[SourceRow] = []
    for ordinal, group, verified, offset in [
        (1, "Alpha", False, 0),
        (2, "Alpha", True, 5),
        (3, "Beta", False, 0),
        (4, "Beta", True, 22),
        (5, "Gamma", False, 0),
        (6, "Gamma", True, 0),
    ]:
        start = datetime(2099, 1, 1, 0, 0) + timedelta(minutes=offset)
        raw = {
            "incidentId": f"SYNTHETIC-{ordinal}",
            "incidentNumber": f"SYNTHETIC-{ordinal}",
            "parentIncidentId": "",
            "permiteeId": f"SYNTHETIC-{group}",
            "permiteeName": f"Synthetic organisation {group}",
            "eventType": "CSO - Untreated",
            "outfallId": f"SYNTHETIC-LOCATION-{group}",
            "location": "Synthetic location",
            "latitude": "0",
            "longitude": "0",
            "reporterClass": VERIFIED if verified else NOTIFICATION,
            "reportingType": "" if verified else "Initial-Ceased",
            "incidentDate": "2099-01-01",
            "incidentTime": start.strftime("%H:%M"),
            "amPm": "",
            "submittedDate": "2099-01-03" if verified else "2099-01-01",
            "volumnOfEvent": "10" if verified else "",
            "rainfallData": "1" if verified else "",
            "hours": "1",
            "minutes": "0",
        }
        rows.append(SourceRow(ordinal, raw, start.date(), start, "24_hour", "synthetic-demo"))
    return rows
