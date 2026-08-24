"""EVERY Google Meet DOM selector lives here and nowhere else (spine M18).
When Meet moves, this file changes; nothing else should. Text matches are case-insensitive."""

# accounts.google.com
LOGIN_EMAIL = 'input[type="email"]'
LOGIN_PASSWORD = 'input[type="password"]'
LOGIN_NEXT = 'button:has-text("Next")'
LOGIN_2SV_HINT = 'text=/2-Step Verification|Verify it.s you|Check your phone/i'

# pre-join screen
PREJOIN_CONTINUE_WITHOUT_MEDIA = 'button:has-text("Continue without microphone")'
PREJOIN_MIC_BUTTON = '[role="button"][aria-label*="microphone" i]'
PREJOIN_CAM_BUTTON = '[role="button"][aria-label*="camera" i]'
PREJOIN_NAME_INPUT = 'input[aria-label*="name" i]'
PREJOIN_JOIN_NOW = 'button:has-text("Join now")'
PREJOIN_ASK_TO_JOIN = 'button:has-text("Ask to join")'
# never clicked: it would pull the user's own session out of the call
PREJOIN_SWITCH_HERE = 'button:has-text("Switch here")'

# lobby / denial
LOBBY_WAITING = 'text=/Asking to join|Someone will let you in|will let you in soon/i'
LOBBY_DENIED = 'text=/You can.t join this call|No one responded|denied your request|Meeting is full/i'

# in call
IN_CALL_LEAVE = 'button[aria-label*="Leave call" i]'
IN_CALL_REMOVED = 'text=/You.ve been removed|You left the meeting|removed you from/i'
IN_CALL_ENDED = 'text=/The meeting has ended|call has ended|Return to home screen/i'

# chat
CHAT_OPEN = 'button[aria-label*="Chat with everyone" i]'
CHAT_INPUT = 'textarea[aria-label*="Send a message" i]'
CHAT_SEND = 'button[aria-label*="Send a message" i]'
CHAT_CLOSE = 'button[aria-label*="Close" i]'

# people panel
PEOPLE_OPEN = 'button[aria-label*="People" i]'
PEOPLE_LIST_ITEM = 'div[role="list"][aria-label*="participant" i] [role="listitem"]'
PEOPLE_SELF_MARK = "(You)"

# active speaker: participant tiles carry data-participant-id; the speaking indicator is an
# animated element inside the tile. Best-effort, refined by the spike report.
TILE = "[data-participant-id]"
TILE_NAME_ATTR = "data-self-name"
TILE_SPEAKING = '[class*="speaking" i], [aria-label*="is speaking" i]'
