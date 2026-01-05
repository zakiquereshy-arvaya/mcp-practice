from ai_calendar_helpers import CalendarAIHelper
from typing import Dict, List, Optional, Any
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
from dotenv import load_dotenv


load_dotenv()


class TimeEntryAIHelper:
    """
    AI-powered helper for time entry query validation and extraction.
    Uses Azure OpenAI to extract structured data from natural language queries
    and validate that all required fields are present.
    """
    
    def __init__(self, calendar_ai_helper: CalendarAIHelper):
        """
        Initialize with a CalendarAIHelper instance to reuse the same Azure OpenAI client.
        
        Args:
            calendar_ai_helper: CalendarAIHelper instance with configured Azure OpenAI client
        """
        self.calendar_ai = calendar_ai_helper
        self.client = calendar_ai_helper.client
        self.model = calendar_ai_helper.model
    
    def validate_and_extract_time_entry(self, query: str) -> Dict[str, Any]:
        """
        Extract and validate required fields from natural language time entry query.
        
        Required fields:
        - date: Date of work (YYYY-MM-DD format)
        - client: Client/customer name
        - description: Description of work performed
        - hours: Duration in decimal hours
        
        Args:
            query: Natural language time entry query
        
        Returns:
            Dict with extracted fields:
            - date: str (YYYY-MM-DD) or None
            - client: str or None
            - description: str or None
            - hours: float or None
            - project: str or None (optional)
            - task: str or None (optional)
            - missing_fields: List[str] - list of missing required fields
        
        Raises:
            ValueError: If AI call fails
        """
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

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a time entry extraction assistant. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # Low temperature for consistency
                max_tokens=500,
                timeout=10.0
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # Try to parse JSON response
            try:
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
                
            except json.JSONDecodeError as e:
                logger.error("Failed to parse AI response as JSON: %s", result_text[:200])
                raise ValueError(f"AI returned invalid JSON response: {e}")
            
        except Exception as e:
            logger.error("AI time entry extraction failed: %s", e)
            raise ValueError(
                f"Failed to extract time entry information from query. "
                f"Please ensure your query includes: date, client/customer name, description, and hours. "
                f"Error: {str(e)}"
            )

