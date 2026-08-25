"""EVERY Google Meet DOM selector lives here and nowhere else (spine M18).
When Meet moves, this file changes; nothing else should. Text matches are case-insensitive."""

# accounts.google.com
LOGIN_EMAIL = 'input[type="email"]'
LOGIN_PASSWORD = 'input[type="password"]'
LOGIN_NEXT = 'button:has-text("Next")'
LOGIN_2SV_HINT = 'text=/2-Step Verification|Verify it.s you|Check your phone/i'

# meet.google.com home when signed out
HOME_SIGN_IN = 'a:has-text("Sign in"), button:has-text("Sign in")'

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
LOBBY_WAITING = 'text=/Asking to join|Someone will let you in|will let you in soon|wait until a meeting host|host brings you into the call/i'
LOBBY_DENIED = 'text=/You can.t join this (video )?call|meeting code that you entered doesn.t work|No one responded|denied your request|Meeting is full/i'

# in call
IN_CALL_LEAVE = 'button[aria-label*="Leave call" i]'
IN_CALL_REMOVED = 'text=/You.ve been removed|You left the meeting|removed you from/i'
IN_CALL_ENDED = 'text=/The meeting has ended|call has ended|Return to home screen/i'

# chat
CHAT_OPEN = 'button[aria-label*="Chat with everyone" i]'
CHAT_INPUT = 'textarea[aria-label*="Send a message" i]'
CHAT_SEND = 'button[aria-label*="Send a message" i]'
CHAT_CLOSE = 'button[aria-label*="Close" i]'

# participants: the People button renders the count as its only text ("2"); tiles carry
# data-participant-id and the display name as their first text line. Both include the bot itself.
PEOPLE_COUNT_JS = """() => {
  const b = Array.from(document.querySelectorAll('button,[role=button]'))
    .map(e => (e.innerText || '').trim()).find(t => /^\\d+$/.test(t));
  return b ? parseInt(b, 10) : null;
}"""
# the bot's own tile has no name, only icon labels (e.g. "visual_effects"); those are not people
TILE_NAMES_JS = """() => Array.from(document.querySelectorAll('[data-participant-id]'))
  .map(t => ((t.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean)[0]) || '')
  .filter(n => n && !/^[a-z_]+$/.test(n))"""

# active speaker: participant tiles carry data-participant-id; the speaking indicator is an
# animated element inside the tile. Best-effort, refined by the spike report.
TILE = "[data-participant-id]"
TILE_NAME_ATTR = "data-self-name"
TILE_SPEAKING = '[class*="speaking" i], [aria-label*="is speaking" i]'

# captions: Meet renders "<speaker name> / <text>" blocks inside a live region. Turning them on gives
# speaker attribution with names for free (AC-S1-6 route chosen 2026-08-24, names guaranteed).
CAPTIONS_ON = 'button[aria-label*="Turn on captions" i]'
CAPTIONS_OFF = 'button[aria-label*="Turn off captions" i]'
CAPTION_BLOCKS_JS = """() => {
  const region = document.querySelector('[aria-live="polite"], [aria-live="assertive"], [role="region"][aria-label*="aption" i]');
  if (!region) return null;
  const blocks = Array.from(region.children).map(b => (b.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean));
  return blocks.filter(b => b.length >= 2).map(b => ({speaker: b[0], text: b.slice(1).join(' ')}));
}"""
CAPTION_REGION_TEXT_JS = """() => {
  const region = document.querySelector('[aria-live="polite"], [aria-live="assertive"], [role="region"][aria-label*="aption" i]');
  return region ? (region.innerText || '').slice(0, 400) : null;
}"""
