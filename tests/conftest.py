"""Test fixtures for cso-insight."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cso_insight.clean import CleanEvent
from cso_insight.ingest import CsoRecord

SAMPLE_CSV = """incidentId,incidentNumber,incidentDate,incidentTime,amPm,reporterClass,eventType,permiteeClass,permiteeName,permiteeId,outfallId,municipality,reportingType,location,latitude,longitude,waterBody,waterBodyDescription,volumnOfEvent,rainfallData,hours,minutes,month,additionalInformation,submittedDate,parentIncidentId,Year
a1,n1,2022-06-01 10:00:00,08:00,,Public Notification Report,CSO – UnTreated,CSO,CITY A,MA001,OUT1,Boston,,,42.3,-71.0,,,1000,0.5,1,30,,,2022-06-01,,2022.0
a2,n2,2022-07-15 12:00:00,10:00,,Public Notification Report,CSO – UnTreated,CSO,CITY A,MA001,OUT1,Boston,,,42.3,-71.0,,,2000,1.0,2,0,,,2022-07-15,,2022.0
a3,n3,2023-03-10 09:00:00,07:00,,Public Notification Report,CSO – UnTreated,CSO,CITY A,MA001,OUT1,Boston,,,42.3,-71.0,,,1500,0.8,1,0,,,2023-03-10,,2023.0
a4,n4,2024-01-20 11:00:00,09:00,,Public Notification Report,CSO – UnTreated,CSO,CITY A,MA001,OUT1,Boston,,,42.3,-71.0,,,1800,1.2,1,15,,,2024-01-20,,2024.0
a5,n5,2025-02-05 14:00:00,12:00,,Public Notification Report,CSO – UnTreated,CSO,CITY A,MA001,OUT1,Boston,,,42.3,-71.0,,,2200,1.5,2,30,,,2025-02-05,,2025.0
b1,n6,2022-08-01 10:00:00,08:00,,Public Notification Report,CSO – UnTreated,CSO,CITY B,MA002,OUT2,Cambridge,,,42.4,-71.1,,,500,0.3,0,45,,,2022-08-01,,2022.0
b2,n7,2023-09-01 10:00:00,08:00,,Public Notification Report,CSO – UnTreated,CSO,CITY B,MA002,OUT2,Cambridge,,,42.4,-71.1,,,600,0.4,1,0,,,2023-09-01,,2023.0
b3,n8,2024-10-01 10:00:00,08:00,,Public Notification Report,CSO – UnTreated,CSO,CITY B,MA002,OUT2,Cambridge,,,42.4,-71.1,,,700,0.5,1,0,,,2024-10-01,,2024.0
b4,n9,2025-11-01 10:00:00,08:00,,Public Notification Report,CSO – UnTreated,CSO,CITY B,MA002,OUT2,Cambridge,,,42.4,-71.1,,,800,0.6,1,0,,,2025-11-01,,2025.0
c1,n10,2022-05-01 10:00:00,08:00,,Public Notification Report,SSO – Discharge,Non-CSO,CITY C,MA003,,Lowell,,,,,,,,,,,,2022-05-01,,2022.0
"""


def write_sample_csv(path: Path) -> Path:
    path.write_text(SAMPLE_CSV, encoding="utf-8")
    return path


def sample_records() -> list[CsoRecord]:
    return [
        CsoRecord(
            incident_id="a1",
            incident_number="n1",
            start_time=datetime(2022, 6, 1, 8, 0),
            event_type="CSO – UnTreated",
            permitee_name="CITY A",
            permitee_id="MA001",
            outfall_id="OUT1",
            municipality="Boston",
            latitude=42.3,
            longitude=-71.0,
            volume_gallons=1000.0,
            rainfall_inches=0.5,
            duration_hours=1.5,
            year=2022,
            is_treated=False,
        )
    ]


def make_event(
    event_id: str,
    outfall_id: str,
    year: int,
    volume: float | None = 1.0,
    rain: float | None = 1.0,
    eligible: bool = True,
) -> CleanEvent:
    return CleanEvent(
        event_id=event_id,
        outfall_id=outfall_id,
        permitee_name="A",
        municipality="B",
        start_time="2025-01-01",
        year=year,
        volume_m3=volume,
        rainfall_mm=rain,
        duration_hours=1.0,
        is_treated=False,
        event_type="CSO",
        fit_eligible=eligible,
    )
