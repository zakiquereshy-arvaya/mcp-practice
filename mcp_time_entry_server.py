import os
import httpx
from fastmcp import FastMCP
from mcp_calendar_server import sanitize_unicode, get_access_token
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import List, Dict 

load_dotenv()

TENANT_ID = os.getenv('TENANT_ID')
CLIENT_ID = os.getenv('CLIENT_ID')
CLIENT_SECRET = os.getenv('CLIENT_SECRET')
SCOPE = 'https://graph.microsoft.com/.default'

TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
N8N_MCP_ENDPOINT = os.getenv('N8N_MCP_PROCESS_TIME_ENTRY_TOOL')

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


def get_user_by_name(name: str) -> Dict[str, str]:
    users = fetch_users_list()
    name_lower = name.lower()
    
    for user in users:
        if user['name'].lower() == name_lower:
            return user
    
    for user in users:
        if name_lower in user['name'].lower() or user['name'].lower() in name_lower:
            return user
    
    raise ValueError(f"User not found: {name}")


@mcp.tool()
def process_time_entry(userName: str, query: str) -> dict:
    if not N8N_MCP_ENDPOINT:
        raise ValueError("N8N_MCP_PROCESS_TIME_ENTRY_TOOL environment variable is not set")
    
    validated_user = get_user_by_name(userName)
    validated_user_name = validated_user['name']
    
    payload = {
        "userName": validated_user_name,
        "query": query
    }
    
    resp = httpx.post(N8N_MCP_ENDPOINT, json=payload, timeout=30.0)
    resp.raise_for_status()
    
    result = resp.json()
    
    return sanitize_unicode({
        "success": True,
        "userName": validated_user_name,
        "userEmail": validated_user['email'],
        "n8n_response": result
    })


if __name__ == "__main__":
    mcp.run(transport="http", port=8001)