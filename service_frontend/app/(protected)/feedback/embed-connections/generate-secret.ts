/**
 * Strong random signing-secret generator (client-side). Both the shared-service
 * and the host (sorento) must hold the SAME secret; the admin generates one here,
 * reveals it once, and pastes it into the host's embed config. 32 random bytes →
 * URL-safe base64 (~43 chars), well above the backend's 8-char floor.
 */
export function generateSigningSecret(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength);
  globalThis.crypto.getRandomValues(bytes);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
