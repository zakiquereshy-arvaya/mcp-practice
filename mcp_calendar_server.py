import os
import httpx
from fastmcp import FastMCP
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import List, Dict 

load_dotenv()

# Environment variables
TENANT_ID = os.getenv('TENANT_ID')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
SCOPE = 'https://graph.microsoft.com/.default'

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

mcp = FastMCP("Calendar Availability Server")


def sanitize_unicode(value):
    """
    Sanitize Unicode characters > 255 from return values.
    Recursively processes strings, dicts, lists, and other types.
    Characters > 255 are replaced with '?' to ensure MCP compatibility.
    """
    if isinstance(value, str):
        # Filter to only allow characters with ordinal value <= 255
        # Replace characters > 255 with '?'
        sanitized = ''.join(char if ord(char) <= 255 else '?' for char in value)
        return sanitized
    elif isinstance(value, dict):
        return {sanitize_unicode(k): sanitize_unicode(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [sanitize_unicode(item) for item in value]
    elif isinstance(value, tuple):
        return tuple(sanitize_unicode(item) for item in value)
    else:
        # For numbers, None, bool, etc., return as-is
        return value


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
        "$select": "subject,start,end,isAllDay,showAs"
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.timezone="Eastern Standard Time"'
    }
    
    # Handle pagination - fetch all pages
    all_events = []
    next_link = None
    
    while True:
        if next_link:
            # Use the nextLink URL directly (it already contains all params)
            resp = httpx.get(next_link, headers=headers)
        else:
            resp = httpx.get(url, params=params, headers=headers)
        
        resp.raise_for_status()
        data = resp.json()
        
        # Add events from this page
        all_events.extend(data.get('value', []))
        
        # Check if there are more pages
        next_link = data.get('@odata.nextLink')
        if not next_link:
            break
    
    # Return in the same format as before, but with all events
    return {'value': all_events}


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


def _fetch_users_list() -> List[Dict[str, str]]:
    """
    Internal helper function to fetch users from Microsoft Graph API.
    
    Returns:
        List of dictionaries containing 'name' and 'email' keys for each user
    """
    token = get_access_token()
    
    url = f"{GRAPH_BASE}/users"
    params = {
        "$select": "displayName,mail,userPrincipalName"
    }
    headers = {"Authorization": f"Bearer {token}"}
    
    resp = httpx.get(url, params=params, headers=headers)
    resp.raise_for_status()
    
    data = resp.json()
    
    users = []
    for user in data.get('value', []):
        email = user.get('mail') or user.get('userPrincipalName')
        name = user.get('displayName', 'Unknown')
        
        users.append({
            'name': name,
            'email': email
        })
    
    return sanitize_unicode(users)


@mcp.tool()
def get_users_with_name_and_email() -> List[Dict[str, str]]:
    """
    Get a list of all users with their display names and email addresses.
    
    Returns:
        List of dictionaries containing 'name' and 'email' keys for each user
    """
    return _fetch_users_list()


def get_user_by_name(name: str) -> Dict[str, str]:
    """
    Find a user by their display name.
    
    Args:
        name: The display name to search for (case-insensitive partial match)
    
    Returns:
        Dictionary with 'name' and 'email' keys, or raises ValueError if not found
    """
    users = _fetch_users_list()
    name_lower = name.lower()
    
    # Try exact match first
    for user in users:
        if user['name'].lower() == name_lower:
            return user
    
    # Try partial match
    for user in users:
        if name_lower in user['name'].lower() or user['name'].lower() in name_lower:
            return user
    
    raise ValueError(f"User not found: {name}")


@mcp.tool()
def check_availability(user_email: str, date: str = "") -> dict:
    """
    Check calendar availability for a user on a specific date.
    
    IMPORTANT: For best results, first call get_users_with_name_and_email to get the correct email address,
    then pass that email here. This function will attempt to resolve names to emails if needed.
    
    Args:
        user_email: The email address or display name of the user to check availability for.
                    If a name is provided, it will be matched against users from get_users_with_name_and_email.
        date: The date to check in YYYY-MM-DD format. Defaults to today if not provided.
    
    Returns:
        Dictionary containing availability information including busy times and free slots
    """
    if not date or date == "":
        date = datetime.now().strftime("%Y-%m-%d")
    
    # Check if user_email is actually an email or a name
    # If it doesn't contain '@', treat it as a name and look up the email using get_users_with_name_and_email data
    if '@' not in user_email:
        users = _fetch_users_list()
        name_lower = user_email.lower().strip()
        target_user = None
        
        # Normalize the search name - remove extra spaces
        search_name = ' '.join(name_lower.split())
        
        # Try exact match first (case-insensitive)
        for user in users:
            user_name_normalized = ' '.join(user['name'].lower().strip().split())
            if user_name_normalized == search_name:
                target_user = user
                break
        
        # Try partial match if exact match not found
        if not target_user:
            for user in users:
                user_name_normalized = ' '.join(user['name'].lower().strip().split())
                # Check if search name is contained in user name or vice versa
                if search_name in user_name_normalized or user_name_normalized in search_name:
                    # Prefer longer matches (more specific)
                    if not target_user or len(user_name_normalized) > len(target_user['name']):
                        target_user = user
        
        if not target_user:
            available_names = [user['name'] for user in users[:5]]  # Show first 5 as examples
            raise ValueError(
                f"User '{user_email}' not found. "
                f"Please use get_users_with_name_and_email tool first to get the correct email address. "
                f"Example names found: {', '.join(available_names)}"
            )
        
        user_email = target_user['email']
    
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    # Query the full day using UTC format (required by Microsoft Graph API)
    # EST is UTC-5, so start of day EST = 05:00 UTC, end of day EST = 05:00 UTC next day
    # But to be safe, let's query a bit wider range to catch all events
    start_datetime = f"{date}T04:00:00Z"  # Slightly before start of day EST in UTC
    next_day = (date_obj + timedelta(days=1)).strftime("%Y-%m-%d")
    end_datetime = f"{next_day}T05:00:00Z"  # Start of next day EST in UTC
    
    events = get_calendar_view(user_email, start_datetime, end_datetime)
    
    busy_times = []
    for event in events.get('value', []):
        # calendarView already filters by date range, so include all returned events
        event_start = event['start']['dateTime']
        event_end = event['end']['dateTime']
        
        busy_times.append({
            'subject': event.get('subject'),
            'start': event_start,
            'end': event_end
        })
    
    free_slots = calculate_free_slots(busy_times, date)
    
    result = {
        'user_email': user_email,
        'date': date,
        'day_of_week': date_obj.strftime('%A'),
        'busy_times': busy_times,
        'total_events': len(busy_times),
        'free_slots': free_slots,
        'is_completely_free': len(busy_times) == 0
    }
    
    return sanitize_unicode(result)


@mcp.tool()
def book_meeting(
    user_email: str,
    subject: str,
    start_datetime: str,
    end_datetime: str,
    sender_name: str,
    attendees: List[str] = None,
    body: str = "" 
) -> dict:
    """
    Book a meeting on a user's calendar.
    
    IMPORTANT: For best results, first call get_users_with_name_and_email to get the correct email addresses
    for both the user_email and sender_name, then pass those emails here. This function will attempt to 
    resolve names to emails if needed.
    
    Args:
        user_email: The email address or display name of the user whose calendar to book on.
                    If a name is provided, it will be matched against users from get_users_with_name_and_email.
        subject: The subject/title of the meeting
        start_datetime: Start time in YYYY-MM-DDTHH:MM:SS format
        end_datetime: End time in YYYY-MM-DDTHH:MM:SS format
        sender_name: The display name of the person booking the meeting (will be looked up to find their email).
                     Use the exact name from get_users_with_name_and_email for best results.
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
    
    # Look up sender's email from their name using get_users_with_name_and_email data
    users = _fetch_users_list()
    sender_name_normalized = ' '.join(sender_name.lower().strip().split())
    sender_user = None
    
    # Try exact match first (case-insensitive, normalized)
    for user in users:
        user_name_normalized = ' '.join(user['name'].lower().strip().split())
        if user_name_normalized == sender_name_normalized:
            sender_user = user
            break
    
    # Try partial match if exact match not found
    if not sender_user:
        for user in users:
            user_name_normalized = ' '.join(user['name'].lower().strip().split())
            # Check if search name is contained in user name or vice versa
            if sender_name_normalized in user_name_normalized or user_name_normalized in sender_name_normalized:
                # Prefer longer matches (more specific)
                if not sender_user or len(user_name_normalized) > len(sender_user['name']):
                    sender_user = user
    
    if not sender_user:
        available_names = [user['name'] for user in users[:5]]  # Show first 5 as examples
        raise ValueError(
            f"Sender '{sender_name}' not found. "
            f"Please use get_users_with_name_and_email tool first to get the correct sender name and email. "
            f"Example names found: {', '.join(available_names)}"
        )
    
    sender_email = sender_user['email']
    sender_display_name = sender_user['name']
    
    # Check if user_email is actually an email or a name
    # If it doesn't contain '@', treat it as a name and look up the email using get_users_with_name_and_email data
    if '@' not in user_email:
        name_normalized = ' '.join(user_email.lower().strip().split())
        target_user = None
        
        # Try exact match first (case-insensitive, normalized)
        for user in users:
            user_name_normalized = ' '.join(user['name'].lower().strip().split())
            if user_name_normalized == name_normalized:
                target_user = user
                break
        
        # Try partial match if exact match not found
        if not target_user:
            for user in users:
                user_name_normalized = ' '.join(user['name'].lower().strip().split())
                # Check if search name is contained in user name or vice versa
                if name_normalized in user_name_normalized or user_name_normalized in name_normalized:
                    # Prefer longer matches (more specific)
                    if not target_user or len(user_name_normalized) > len(target_user['name']):
                        target_user = user
        
        if not target_user:
            available_names = [user['name'] for user in users[:5]]  # Show first 5 as examples
            raise ValueError(
                f"User '{user_email}' not found. "
                f"Please use get_users_with_name_and_email tool first to get the correct email address. "
                f"Example names found: {', '.join(available_names)}"
            )
        
        user_email = target_user['email']
    
    token = get_access_token()
    user_id = get_user_id_by_email(user_email)
    url = f"{GRAPH_BASE}/users/{user_id}/events"
    
    # Include sender information in the meeting body
    sender_info = f"<p><strong>Booked by:</strong> {sender_display_name} ({sender_email})</p>"
    meeting_body = sender_info
    if body:
        meeting_body += f"<br>{body}"
    
    # Build attendees list - always include sender, and any additional attendees
    attendees_list = []
    
    # Always add sender as an attendee so it shows up on their calendar
    attendees_list.append({
        "emailAddress": {"address": sender_email},
        "type": "required"
    })
    
    # Add any additional attendees (avoid duplicates)
    if attendees:
        for email in attendees:
            # Don't add sender twice if they're already in the list
            if email.lower() != sender_email.lower():
                attendees_list.append({
                    "emailAddress": {"address": email},
                    "type": "required"
                })
    
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
        "onlineMeetingProvider": "teamsForBusiness",
        "body": {
            "contentType": "HTML",
            "content": meeting_body
        },
        "attendees": attendees_list
    }
    
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
        'attendee_emails': attendees if attendees else [],
        'sender_name': sender_display_name,
        'sender_email': sender_email
    }
    
    return sanitize_unicode(result)


if __name__ == "__main__":
    mcp.run(transport="http", port=8000)