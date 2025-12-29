import os
import httpx
from fastmcp import FastMCP
from dotenv import load_dotenv
from datetime import datetime
from typing import Optional, List, Dict 

load_dotenv()

# Environment variables
TENANT_ID = os.getenv('TENANT_ID')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
SCOPE = 'https://graph.microsoft.com/.default'

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

mcp = FastMCP("Calendar Availability Server")


# Helper functions
def get_access_token() -> str:
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": SCOPE,
        "grant_type": "client_credentials"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = httpx.post(TOKEN_URL, data=data, headers=headers)
    resp.raise_for_status()
    return resp.json()['access_token']


def list_users():
    token = get_access_token()
    resp = httpx.get(f"{GRAPH_BASE}/users", headers={"Authorization": f"Bearer {token}"})
    resp.raise_for_status()
    return resp.json()


def get_user_id_by_email(email: str) -> str:
    users = list_users()
    for user in users['value']:
        if user['mail'] and user['mail'].lower() == email.lower():
            return user['id']
        if user['userPrincipalName'].lower() == email.lower():
            return user['id']
    raise ValueError(f"User not found: {email}")


def get_calendar_view(user_email: str, start_datetime: str, end_datetime: str):
    token = get_access_token()
    user_id = get_user_id_by_email(user_email)
    url = f"{GRAPH_BASE}/users/{user_id}/calendarView"
    params = {
        "startDateTime": start_datetime,
        "endDateTime": end_datetime,
        "$select": "subject,start,end,isAllDay"
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.timezone="Eastern Standard Time"'
    }
    resp = httpx.get(url, params=params, headers=headers)
    resp.raise_for_status()
    return resp.json()


def calculate_duration(start: str, end: str):
    try:
        start_clean = start.replace('Z', '').split('+')[0].split('.')[0]
        end_clean = end.replace('Z', '').split('+')[0].split('.')[0]
        start_dt = datetime.fromisoformat(start_clean)
        end_dt = datetime.fromisoformat(end_clean)
        duration = (end_dt - start_dt).total_seconds() / 3600
        return round(duration, 2)
    except:
        return 0


def calculate_free_slots(busy_times: list, date: str):
    if not busy_times:
        return [{
            'start': f"{date}T09:00:00",
            'end': f"{date}T17:00:00",
            'duration_hours': 8
        }]
    
    sorted_busy = sorted(busy_times, key=lambda x: x['start'])
    free_slots = []
    business_start = f"{date}T09:00:00"
    business_end = f"{date}T17:00:00"
    
    first_meeting_start = sorted_busy[0]['start'].split('T')[1].split('.')[0]
    if first_meeting_start > "09:00:00":
        free_slots.append({
            'start': business_start,
            'end': sorted_busy[0]['start'],
            'duration_hours': calculate_duration(business_start, sorted_busy[0]['start'])
        })
    
    for i in range(len(sorted_busy) - 1):
        current_end = sorted_busy[i]['end']
        next_start = sorted_busy[i + 1]['start']
        if current_end < next_start:
            duration = calculate_duration(current_end, next_start)
            if duration > 0:
                free_slots.append({
                    'start': current_end,
                    'end': next_start,
                    'duration_hours': duration
                })
    
    last_meeting_end = sorted_busy[-1]['end'].split('T')[1].split('.')[0]
    if last_meeting_end < "17:00:00":
        free_slots.append({
            'start': sorted_busy[-1]['end'],
            'end': business_end,
            'duration_hours': calculate_duration(sorted_busy[-1]['end'], business_end)
        })
    
    return free_slots

@mcp.tool()
def get_users_with_name_and_email() -> Dict[str, str]:
    token = get_access_token()
    
    url = f"{GRAPH_BASE}/users"
    params = {
        "$select": "displayName,mail,userPrincipalName"
    }
    headers = {"Authorization": f"Bearer {token}"}
    
    resp = httpx.get(url, params=params, headers=headers)
    resp.raise_for_status()
    
    data = resp.json()
    
    for user in data.get('value', []):
        email = user.get('mail') or user.get('userPrincipalName')
        name = user.get('displayName', 'Unknown')
        
      
    return  {
        'name': name,
        'email': email
    }

# MCP Tool
@mcp.tool()
def check_availability(user_email: str, date: Optional[str] = None) -> dict:
    """
    Check calendar availability for a user on a specific date.
    
    Args:
        user_email: The email address of the user to check availability for
        date: The date to check in YYYY-MM-DD format. Defaults to today if not provided.
    
    Returns:
        Dictionary containing availability information including busy times and free slots
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    start_datetime = f"{date}T09:00:00"
    end_datetime = f"{date}T17:00:00"
    
    events = get_calendar_view(user_email, start_datetime, end_datetime)
    
    busy_times = []
    for event in events.get('value', []):
        event_start = event['start']['dateTime']
        event_end = event['end']['dateTime']
        event_date = event_start.split('T')[0]
        
        if event_date == date:
            busy_times.append({
                'subject': event.get('subject'),
                'start': event_start,
                'end': event_end
            })
    
    free_slots = calculate_free_slots(busy_times, date)
    
    return {
        'user_email': user_email,
        'date': date,
        'day_of_week': date_obj.strftime('%A'),
        'busy_times': busy_times,
        'total_events': len(busy_times),
        'free_slots': free_slots,
        'is_completely_free': len(busy_times) == 0
    }


@mcp.tool()
def book_meeting(
    user_email: str,
    subject: str,
    start_datetime: str,
    end_datetime: str,
    attendees: Optional[list] = None,
    body: Optional[str] = None
) -> dict:
    """
    Book a meeting on a user's calendar.
    
    Args:
        user_email: The email address of the user whose calendar to book on
        subject: The subject/title of the meeting
        start_datetime: Start time in YYYY-MM-DDTHH:MM:SS format
        end_datetime: End time in YYYY-MM-DDTHH:MM:SS format
        attendees: Optional list of attendee email addresses
        body: Optional meeting body/description
    
    Returns:
        Dictionary containing the created meeting details including Teams link
    """
    try:
        start_dt = datetime.fromisoformat(start_datetime)
        end_dt = datetime.fromisoformat(end_datetime)
    except:
        raise ValueError("Invalid datetime format. Use YYYY-MM-DDTHH:MM:SS")
    
    if end_dt <= start_dt:
        raise ValueError("End time must be after start time")
    
    day_of_week = start_dt.strftime('%A')
    date_formatted = start_dt.strftime('%B %d, %Y')
    
    token = get_access_token()
    user_id = get_user_id_by_email(user_email)
    url = f"{GRAPH_BASE}/users/{user_id}/events"
    
    event_data = {
        "subject": subject,
        "start": {
            "dateTime": start_datetime,
            "timeZone": "Eastern Standard Time"
        },
        "end": {
            "dateTime": end_datetime,
            "timeZone": "Eastern Standard Time"
        },
        "isOnlineMeeting": True,
        "onlineMeetingProvider": "teamsForBusiness"
    }
    
    if body:
        event_data["body"] = {
            "contentType": "HTML",
            "content": body
        }
    
    if attendees:
        event_data["attendees"] = [
            {
                "emailAddress": {"address": email},
                "type": "required"
            }
            for email in attendees
        ]
    
    resp = httpx.post(
        url,
        json=event_data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )
    resp.raise_for_status()
    
    result = resp.json()
    
    teams_link = None
    if result.get('onlineMeeting') and result['onlineMeeting'].get('joinUrl'):
        teams_link = result['onlineMeeting']['joinUrl']
    
    result['validated_date_info'] = {
        'subject': subject,
        'day_of_week': day_of_week,
        'date_formatted': date_formatted,
        'start_time': start_dt.strftime('%I:%M %p'),
        'end_time': end_dt.strftime('%I:%M %p'),
        'duration_minutes': int((end_dt - start_dt).total_seconds() / 60),
        'teams_link': teams_link,
        'has_teams_link': teams_link is not None,
        'attendee_emails': attendees if attendees else []
    }
    
    return result


if __name__ == "__main__":
    mcp.run(transport="http", port=8000)