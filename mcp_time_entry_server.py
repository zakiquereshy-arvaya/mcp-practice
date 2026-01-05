import os
import httpx
from fastmcp import FastMCP
from mcp_calendar_server import sanitize_unicode, get_access_token
from dotenv import load_dotenv
from typing import List, Dict, Optional, Any
from openai import AzureOpenAI
import json
import logging

load_dotenv()

logger = logging.getLogger(__name__)

# Azure OpenAI configuration
AZURE_OPENAI_API_KEY = os.getenv('AZURE_OPENAI_API_KEY')
AZURE_OPENAI_API_VERSION = os.getenv('AZURE_OPENAI_API_VERSION', '2024-12-01-preview')
AZURE_OPENAI_ENDPOINT = os.getenv('AZURE_OPENAI_ENDPOINT')
AZURE_OPENAI_MODEL = os.getenv('AZURE_OPENAI_MODEL')

# Initialize Azure OpenAI client if credentials are available
azure_openai_client = None
if AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_MODEL:
    try:
        azure_openai_client = AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
            azure_endpoint=AZURE_OPENAI_ENDPOINT
        )
        logger.info("Azure OpenAI client initialized successfully")
    except Exception as e:
        logger.warning(f"Failed to initialize Azure OpenAI client: {e}")
        azure_openai_client = None
else:
    missing = []
    if not AZURE_OPENAI_API_KEY:
        missing.append('AZURE_OPENAI_API_KEY')
    if not AZURE_OPENAI_ENDPOINT:
        missing.append('AZURE_OPENAI_ENDPOINT')
    if not AZURE_OPENAI_MODEL:
        missing.append('AZURE_OPENAI_MODEL')
    logger.warning(f"Azure OpenAI not configured. Missing: {', '.join(missing)}")

TENANT_ID = os.getenv('TENANT_ID')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
SCOPE = 'https://graph.microsoft.com/.default'

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

N8N_TIMEENTRY_WEBHOOK = os.getenv('N8N_TIMEENTRY_WEBHOOK')
if N8N_TIMEENTRY_WEBHOOK:
    N8N_TIMEENTRY_WEBHOOK = N8N_TIMEENTRY_WEBHOOK.strip()

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


def ai_match_user_name(query_name: str, users_list: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """
    Use AI to intelligently match a query name to a user from the list.
    Handles possessive forms, nicknames, partial names.
    """
    if not azure_openai_client:
        raise ValueError(
            "Azure OpenAI not configured. Please set AZURE_OPENAI_API_KEY, "
            "AZURE_OPENAI_ENDPOINT, and AZURE_OPENAI_MODEL environment variables."
        )
    
    if not query_name or not query_name.strip() or not users_list:
        return None
    
    try:
        prompt = f"""You are a user name matching assistant. Given a query name and a list of users, 
find the best matching user. You must be STRICT to prevent false matches.

Query: "{query_name}"
Users: {json.dumps(users_list, indent=2)}

Rules:
- Match possessive forms (e.g., "ryan's" → "Ryan Botindari") ONLY if unambiguous
- Match partial names (e.g., "zaki" → "Zaki Quereshy") ONLY if unique
- Match nicknames ONLY if obvious and unambiguous
- If multiple users could match, return null (do not guess)
- Confidence must be > 0.9 to return a match
- Return JSON: {{"name": "...", "email": "...", "confidence": 0.0-1.0}}
- If confidence < 0.9 or ambiguous, return: {{"match": null, "reason": "..."}}

Return ONLY valid JSON, no other text."""

        response = azure_openai_client.chat.completions.create(
            model=AZURE_OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a strict user name matching assistant. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=200,
            timeout=10.0
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()
        
        result = json.loads(result_text)
        
        # Check if match was found
        if result.get("match") is None:
            return None
        
        # Check confidence threshold
        confidence = result.get("confidence", 0.0)
        if confidence < 0.9:
            return None
        
        # Return the matched user
        return {
            "name": result.get("name"),
            "email": result.get("email")
        }
        
    except Exception as e:
        logger.error(f"AI name matching failed for '{query_name}': {e}")
        raise ValueError(
            f"Failed to match user name '{query_name}'. "
            f"Please use get_users_with_name_and_email tool first to get the correct email address. "
            f"Error: {str(e)}"
        )


def ai_extract_time_entry(query: str) -> Dict[str, Any]:
    """
    Extract and validate required fields from natural language time entry query.
    """
    if not azure_openai_client:
        raise ValueError(
            "Azure OpenAI not configured. Please set AZURE_OPENAI_API_KEY, "
            "AZURE_OPENAI_ENDPOINT, and AZURE_OPENAI_MODEL environment variables."
        )
    
    if not query or not query.strip():
        return {
            "date": None,
            "client": None,
            "description": None,
            "hours": None,
            "project": None,
            "task": None,
            "missing_fields": ["date", "client", "description", "hours"]
        }
    
    try:
        prompt = f"""Extract time entry information from this natural language query.

Query: "{query}"

Extract the following fields:
- date: Date of work (convert to YYYY-MM-DD format, e.g., "1/3/2026" → "2026-01-03", "January 3, 2026" → "2026-01-03")
- client: Client/customer name (e.g., "Arvaya Internal", "Customer ABC")
- description: Description of work performed (full description text)
- hours: Duration in decimal hours (e.g., "8 hours" → 8.0, "30 minutes" → 0.5, "2.5 hours" → 2.5, "8h" → 8.0)

Optional fields:
- project: Project name (if mentioned)
- task: Specific task (if mentioned)

Rules:
- If date is mentioned but format is unclear, use today's date as fallback
- Extract hours from phrases like "8 hours", "8h", "30 minutes", "half hour", etc.
- Description should be the full work description, not truncated
- Client name should be extracted exactly as mentioned

Return JSON:
{{
  "date": "YYYY-MM-DD" or null,
  "client": "client name" or null,
  "description": "description" or null,
  "hours": 8.0 or null,
  "project": "project name" or null,
  "task": "task name" or null,
  "missing_fields": ["field1", "field2"]  // List of missing required fields
}}

Required fields are: date, client, description, hours.
If any are missing or cannot be determined, list them in missing_fields array.

Return ONLY valid JSON, no other text."""

        response = azure_openai_client.chat.completions.create(
            model=AZURE_OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a time entry extraction assistant. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=500,
            timeout=10.0
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()
        
        result = json.loads(result_text)
        
        # Ensure all expected fields are present
        extracted = {
            "date": result.get("date"),
            "client": result.get("client"),
            "description": result.get("description"),
            "hours": result.get("hours"),
            "project": result.get("project"),
            "task": result.get("task"),
            "missing_fields": result.get("missing_fields", [])
        }
        
        # Validate required fields and update missing_fields if needed
        missing = []
        if not extracted["date"]:
            missing.append("date")
        if not extracted["client"]:
            missing.append("client")
        if not extracted["description"]:
            missing.append("description")
        if extracted["hours"] is None:
            missing.append("hours")
        
        extracted["missing_fields"] = missing
        
        logger.info(f"Extracted time entry fields: date={extracted['date']}, client={extracted['client']}, hours={extracted['hours']}, missing={missing}")
        
        return extracted
        
    except Exception as e:
        logger.error(f"AI time entry extraction failed: {e}")
        raise ValueError(
            f"Failed to extract time entry information from query. "
            f"Please ensure your query includes: date, client/customer name, description, and hours. "
            f"Error: {str(e)}"
        )


@mcp.tool()
def process_time_entry(userName: str, query: str) -> dict:
    """
    Process a time entry and submit it to QuickBooks and Monday.com via N8N webhook.
    
    Uses AI to:
    - Match userName to a valid user in the system
    - Extract and validate required fields (date, client, description, hours) from natural language query
    
    Args:
        userName: Name of the user logging time (will be matched using AI, or can be email address)
        query: Natural language time entry query containing date, client, description, and hours
    
    Returns:
        Dictionary with success status, validated user info, and N8N response
    
    Raises:
        ValueError: If userName not found, required fields missing, or AI validation fails
    """
    if not N8N_TIMEENTRY_WEBHOOK or not N8N_TIMEENTRY_WEBHOOK.startswith('http'):
        raise ValueError(f"Invalid N8N_TIMEENTRY_WEBHOOK: {N8N_TIMEENTRY_WEBHOOK}. Check N8N_TIMEENTRY_WEBHOOK environment variable.")
    
    # 1. Validate userName - check if it's an email or a name
    users = fetch_users_list()
    
    # If userName is an email address, validate it directly
    if '@' in userName:
        validated_user = None
        userName_lower = userName.lower().strip()
        for user in users:
            user_email = (user.get('email') or '').lower().strip()
            if user_email == userName_lower:
                validated_user = user
                break
        
        if not validated_user:
            available_emails = [user.get('email', 'N/A') for user in users[:5] if user.get('email')]
            raise ValueError(
                f"User email '{userName}' not found in the system. "
                f"Please use get_users_with_name_and_email tool first to get a valid user email. "
                f"Example emails found: {', '.join(available_emails[:3])}"
            )
    else:
        # If userName is a name, use AI to match it
        validated_user = ai_match_user_name(userName, users)
        
        if not validated_user:
            available_names = [user['name'] for user in users[:5]]  # Show first 5 as examples
            raise ValueError(
                f"User '{userName}' not found or ambiguous. "
                f"Please use get_users_with_name_and_email tool first to get the correct user name or email. "
                f"Example names found: {', '.join(available_names)}"
            )
    
    validated_user_name = validated_user['name']
    validated_user_email = validated_user['email']
    
    # 2. Validate and extract fields from query using AI
    extracted = ai_extract_time_entry(query)
    
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
