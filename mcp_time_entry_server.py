import os
import httpx
from fastmcp import FastMCP
from mcp_calendar_server import sanitize_unicode, get_access_token
from dotenv import load_dotenv
# datetime and timedelta imports removed - not needed
from typing import List, Dict 
from ai_calendar_helpers import CalendarAIHelper
from ai_time_entry_helpers import TimeEntryAIHelper
import logging

load_dotenv()

# Initialize AI helpers for intelligent name matching and query validation
try:
    calendar_ai = CalendarAIHelper()
    time_entry_ai = TimeEntryAIHelper(calendar_ai)
except Exception as e:
    calendar_ai = None
    time_entry_ai = None
    logging.warning(f"AI helpers initialization failed: {e}. Name matching and query validation will fail.")

TENANT_ID = os.getenv('TENANT_ID')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
SCOPE = 'https://graph.microsoft.com/.default'

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

N8N_TIMEENTRY_WEBHOOK = os.getenv('N8N_TIMEENTRY_WEBHOOK').strip()
#Adding for new deploy this comment can be removed later

mcp = FastMCP("Time Entry Server")


def fetch_users_list() -> List[Dict[str, str]]:
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
    return fetch_users_list()


# Removed get_user_by_name - now using AI matching via calendar_ai.match_user_name()


@mcp.tool()
def process_time_entry(userName: str, query: str) -> dict:
    """
    Process a time entry and submit it to QuickBooks and Monday.com via N8N webhook.
    
    Uses AI to:
    - Match userName to a valid user in the system
    - Extract and validate required fields (date, client, description, hours) from natural language query
    
    Args:
        userName: Name of the user logging time (will be matched using AI)
        query: Natural language time entry query containing date, client, description, and hours
    
    Returns:
        Dictionary with success status, validated user info, and N8N response
    
    Raises:
        ValueError: If userName not found, required fields missing, or AI validation fails
    """
    if not N8N_TIMEENTRY_WEBHOOK or not N8N_TIMEENTRY_WEBHOOK.startswith('http'):
        raise ValueError(f"Invalid N8N_TIMEENTRY_WEBHOOK: {N8N_TIMEENTRY_WEBHOOK}. Check N8N_TIMEENTRY_WEBHOOK environment variable.")
    
    # 1. Validate userName using AI (same as calendar server)
    if not calendar_ai:
        raise ValueError(
            "AI helper not available. Please ensure Azure OpenAI is configured. "
            "User name validation requires AI."
        )
    
    users = fetch_users_list()
    validated_user = calendar_ai.match_user_name(userName, users)
    
    if not validated_user:
        available_names = [user['name'] for user in users[:5]]  # Show first 5 as examples
        raise ValueError(
            f"User '{userName}' not found or ambiguous. "
            f"Please use get_users_with_name_and_email tool first to get the correct user name. "
            f"Example names found: {', '.join(available_names)}"
        )
    
    validated_user_name = validated_user['name']
    validated_user_email = validated_user['email']
    
    # 2. Validate and extract fields from query using AI
    if not time_entry_ai:
        raise ValueError(
            "AI helper not available. Please ensure Azure OpenAI is configured. "
            "Query validation requires AI."
        )
    
    extracted = time_entry_ai.validate_and_extract_time_entry(query)
    
    # 3. Check for missing required fields
    missing_fields = extracted.get('missing_fields', [])
    if missing_fields:
        missing_list = ', '.join(missing_fields)
        raise ValueError(
            f"Missing required fields in time entry query: {missing_list}. "
            f"Please provide: date, client/customer name, description, and hours. "
            f"Example: 'I worked for Arvaya Internal on 1/3/2026. I did backend work. This was 8 hours.'"
        )
    
    # 4. Build payload with validated and extracted data
    payload = {
        "userName": validated_user_name,
        "userEmail": validated_user_email,
        "date": extracted['date'],
        "client": extracted['client'],
        "description": extracted['description'],
        "hours": extracted['hours'],
        "query": query  # Keep original query for reference
    }
    
    # Add optional fields if present
    if extracted.get('project'):
        payload['project'] = extracted['project']
    if extracted.get('task'):
        payload['task'] = extracted['task']
    
    # 5. Send to webhook
    resp = httpx.post(N8N_TIMEENTRY_WEBHOOK, json=payload, timeout=30.0)
    resp.raise_for_status()
    
    result = resp.json()
    
    return sanitize_unicode({
        "success": True,
        "userName": validated_user_name,
        "userEmail": validated_user_email,
        "extracted_fields": {
            "date": extracted['date'],
            "client": extracted['client'],
            "description": extracted['description'],
            "hours": extracted['hours']
        },
        "n8n_response": result
    })


if __name__ == "__main__":
    mcp.run(transport="http", port=8001)