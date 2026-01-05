from openai import AzureOpenAI
from typing import List, Dict, Optional
import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

azure_deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT')

class CalendarAIHelper:
    """
    AI-powered helper for intelligent name matching and sender validation.
    Uses Azure OpenAI to handle natural language variations, possessive forms,
    and nicknames while maintaining strict confidence thresholds to prevent
    false matches at scale.
    """
    
    def __init__(self):
        api_key = os.getenv('AZURE_OPENAI_API_KEY')
        api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2024-12-01-preview')
        azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
        model = os.getenv('AZURE_OPENAI_MODEL')
        
        # Validate all required environment variables
        missing_vars = []
        if not api_key:
            missing_vars.append('AZURE_OPENAI_API_KEY')
        if not azure_endpoint:
            missing_vars.append('AZURE_OPENAI_ENDPOINT')
        if not model:
            missing_vars.append('AZURE_OPENAI_MODEL')
        
        if missing_vars:
            raise ValueError(
                f"Azure OpenAI credentials not found. Missing: {', '.join(missing_vars)}. "
                f"Please set these environment variables in .env"
            )
        
        self.client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_deployment=azure_deployment
        )
        self.model = model
        self.min_confidence_name = 0.9  # Strict threshold for name matching
        self.min_confidence_sender = 0.95  # Even stricter for sender validation
    
    def match_user_name(self, query_name: str, users_list: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """
        Use AI to intelligently match a query name to a user from the list.
        Handles possessive forms, nicknames, partial names.
        
        CRITICAL: Only returns match if confidence > 0.9 to prevent false positives at scale.
        No fuzzy matching fallback - if AI can't match with high confidence, returns None.
        
        Args:
            query_name: The name query (e.g., "ryan's", "zaki", "Ryan Botindari")
            users_list: List of user dicts with 'name' and 'email' keys
        
        Returns:
            User dict if match found with high confidence, None otherwise
        
        Raises:
            ValueError: If AI call fails (no fallback to fuzzy matching)
        """
        if not query_name or not query_name.strip():
            return None
        
        if not users_list:
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

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a strict user name matching assistant. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # Low temperature for consistency
                max_tokens=200,
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
                
                # Check if match was found
                if result.get("match") is None:
                    logger.info(f"No match found for '{query_name}': {result.get('reason', 'Unknown reason')}")
                    return None
                
                # Check confidence threshold
                confidence = result.get("confidence", 0.0)
                if confidence < self.min_confidence_name:
                    logger.info(f"Match found for '{query_name}' but confidence {confidence} < {self.min_confidence_name}")
                    return None
                
                # Return the matched user
                matched_user = {
                    "name": result.get("name"),
                    "email": result.get("email")
                }
                
                logger.info(f"AI matched '{query_name}' → '{matched_user['name']}' (confidence: {confidence})")
                return matched_user
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse AI response as JSON: {result_text[:100]}")
                raise ValueError(f"AI returned invalid JSON response: {e}")
            
        except Exception as e:
            logger.error(f"AI name matching failed for '{query_name}': {e}")
            # No fallback - fail safely
            raise ValueError(
                f"Failed to match user name '{query_name}'. "
                f"Please use get_users_with_name_and_email tool first to get the correct email address. "
                f"Error: {str(e)}"
            )
    
    def validate_sender(self, sender_name: str, sender_email: str, users_list: List[Dict[str, str]]) -> Dict[str, str]:
        """
        Validate sender_email exists and sender_name matches the email's user.
        
        CRITICAL: sender_email is REQUIRED. No fuzzy matching fallback.
        Uses AI to verify sender_name matches the user associated with sender_email.
        
        Args:
            sender_name: Display name provided
            sender_email: REQUIRED - Email address of sender
            users_list: List of all users
        
        Returns:
            Validated user dict with 'name' and 'email'
        
        Raises:
            ValueError: If validation fails (email not found, name doesn't match, etc.)
        """
        if not sender_email or not sender_email.strip():
            raise ValueError(
                "sender_email is REQUIRED. Please call get_users_with_name_and_email first "
                "to get the sender's email address, then provide it as sender_email parameter."
            )
        
        sender_email_lower = sender_email.lower().strip()
        
        # First: Deterministic check that sender_email exists
        sender_user_by_email = None
        for user in users_list:
            user_email = (user.get('email') or '').lower().strip()
            if user_email == sender_email_lower:
                sender_user_by_email = user
                break
        
        if not sender_user_by_email:
            available_emails = [user.get('email', 'N/A') for user in users_list[:5] if user.get('email')]
            raise ValueError(
                f"Sender email '{sender_email}' not found in the system. "
                f"Please use get_users_with_name_and_email tool first to get a valid sender email address. "
                f"Example emails found: {', '.join(available_emails[:3])}"
            )
        
        # Second: Use AI to verify sender_name matches this user
        if not sender_name or not sender_name.strip():
            # If no sender_name provided, just return the user found by email
            return sender_user_by_email
        
        try:
            prompt = f"""Validate that sender_email "{sender_email}" belongs to a user 
whose name matches "{sender_name}" (allowing for natural variations like possessive forms, 
nicknames, but must be the SAME person).

Found user by email: {json.dumps(sender_user_by_email, indent=2)}
All users: {json.dumps(users_list, indent=2)}

CRITICAL: 
- sender_email MUST exist in the users list (already verified)
- sender_name MUST match the user associated with sender_email
- Be strict - if uncertain, return valid: false
- Confidence must be > 0.95 to return valid: true

Return JSON: {{"name": "...", "email": "...", "valid": true/false, "confidence": 0.0-1.0}}
Return ONLY valid JSON, no other text."""

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a strict sender validation assistant. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # Low temperature for consistency
                max_tokens=200,
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
                
                is_valid = result.get("valid", False)
                confidence = result.get("confidence", 0.0)
                
                if not is_valid or confidence < self.min_confidence_sender:
                    raise ValueError(
                        f"Sender validation failed: sender_name '{sender_name}' does not match "
                        f"the user associated with sender_email '{sender_email}'. "
                        f"Confidence: {confidence}. "
                        f"Please use get_users_with_name_and_email to get the correct sender information."
                    )
                
                validated_user = {
                    "name": result.get("name") or sender_user_by_email["name"],
                    "email": result.get("email") or sender_email
                }
                
                logger.info(f"AI validated sender '{sender_name}' with email '{sender_email}' (confidence: {confidence})")
                return validated_user
                
            except json.JSONDecodeError:
                logger.error("Failed to parse AI validation response as JSON: %s", result_text[:100])
                # Fallback: if we can't parse AI response, use the user found by email
                # But log a warning
                logger.warning("AI validation response parse failed, using email-based match")
                return sender_user_by_email
            
        except ValueError:
            # Re-raise ValueError (validation failures)
            raise
        except Exception as e:
            logger.error(f"AI sender validation failed: {e}")
            # If AI fails, we still have the email-validated user, but warn
            logger.warning(f"AI validation failed, using email-based match. Error: {e}")
            return sender_user_by_email
