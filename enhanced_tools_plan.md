# Enhanced Calendar MCP Server Tools

## Current State

The server currently has:

- `get_users_with_name_and_email()` - List all users
- `check_availability()` - Check single user availability for a date
- `book_meeting()` - Create a new meeting

## Proposed New Tools

### 1. Meeting Management Tools

#### `cancel_meeting(user_email: str, meeting_id: str, sender_name: str) -> dict`

- Cancel/delete an existing meeting
- Requires meeting ID (from booking response or list)
- Sends cancellation notices to attendees
- Uses: `DELETE /users/{id}/events/{eventId}`

#### `update_meeting(user_email: str, meeting_id: str, sender_name: str, subject: str = "", start_datetime: str = "", end_datetime: str = "", body: str = "", attendees: List[str] = None) -> dict`

- Update existing meeting details
- Partial updates (only provided fields)
- Can reschedule, change attendees, update subject/body
- Uses: `PATCH /users/{id}/events/{eventId}`

#### `get_meeting_details(user_email: str, meeting_id: str) -> dict`

- Get full details of a specific meeting
- Returns all meeting information including attendees, Teams link, etc.
- Uses: `GET /users/{id}/events/{eventId}`

### 2. Meeting Discovery Tools

#### `list_upcoming_meetings(user_email: str, days_ahead: int = 7, max_results: int = 50) -> dict`

- List upcoming meetings for a user
- Configurable lookahead period
- Returns meeting summaries with IDs for management operations
- Uses: `GET /users/{id}/calendarView` with date range

#### `search_meetings(user_email: str, search_query: str, start_date: str = "", end_date: str = "") -> dict`

- Search meetings by subject/keyword
- Optional date range filtering
- Returns matching meetings
- Uses: `GET /users/{id}/events` with `$filter` query

### 3. Multi-User Coordination Tools

#### `find_common_availability(user_emails: List[str], date: str = "", duration_minutes: int = 60, start_time: str = "09:00", end_time: str = "17:00") -> dict`

- Find time slots when all specified users are available
- Supports multiple users (not just one)
- Configurable duration and time window
- Returns list of available time slots
- Uses: `POST /users/{id}/calendar/getSchedule` (free/busy API)

#### `get_free_busy(user_emails: List[str], start_datetime: str, end_datetime: str) -> dict`

- Get free/busy information for multiple users
- Returns detailed availability for each user
- Useful for manual coordination
- Uses: `POST /users/{id}/calendar/getSchedule`

### 4. Meeting Response Tools

#### `respond_to_meeting(user_email: str, meeting_id: str, response: str) -> dict`

- Accept, decline, or tentatively accept a meeting
- Response options: "accepted", "declined", "tentativelyAccepted"
- Uses: `POST /users/{id}/events/{eventId}/accept` or `/decline` or `/tentativelyAccept`

### 5. Recurring Meeting Tools

#### `create_recurring_meeting(user_email: str, subject: str, start_datetime: str, end_datetime: str, sender_name: str, recurrence_pattern: str, recurrence_end: str, attendees: List[str] = None, body: str = "") -> dict`

- Create recurring meetings (daily, weekly, monthly)
- Pattern examples: "daily", "weekly", "monthly"
- End date or number of occurrences
- Uses: `POST /users/{id}/events` with recurrence object

### 6. Helper Enhancements

#### `get_meeting_id_by_subject(user_email: str, subject: str, start_date: str = "") -> str`

- Helper to find meeting ID by subject and optional date
- Useful when user knows meeting name but not ID
- Uses search functionality internally

## Implementation Priority

**High Priority (Core Functionality):**

1. `cancel_meeting` - Essential for meeting lifecycle
2. `list_upcoming_meetings` - Needed to discover meetings to manage
3. `find_common_availability` - Extends single-user availability to multi-user

**Medium Priority (Enhanced Features):**

4. `update_meeting` - Allows modifications without cancellation
5. `get_meeting_details` - Full meeting information
6. `search_meetings` - Find meetings by keyword

**Lower Priority (Nice to Have):**

7. `respond_to_meeting` - Meeting response management
8. `create_recurring_meeting` - Recurring meeting support
9. `get_free_busy` - Detailed multi-user availability

## Technical Considerations

- All tools should follow the same pattern as existing tools
- Use `get_user_by_name()` for sender lookup
- Use `sanitize_unicode()` for all return values
- Handle pagination for list operations
- Include proper error handling and validation
- Maintain consistent return format with `validated_date_info` where applicable