# Authentication and authorization

Registration accepts creator, brand and customer roles; brand/creator profile rows are initialized as appropriate. Passwords are stored as PBKDF2-HMAC-SHA256 with random salt (never plaintext). Login issues a short-lived signed HS256 access JWT. Authenticated API routes resolve the subject against the current active user record. Role checks and ownership checks are server-side dependencies/route checks; the UI is not the authorization boundary.

Current limitation: bearer tokens are stored in localStorage by the SPA, with no refresh token rotation/revocation, secure HTTP-only cookie, verification email, password reset, MFA, login throttling or account lockout. This must be upgraded and security reviewed before exposing sensitive user accounts publicly. Provide a non-default high-entropy `JWT_SECRET` and HTTPS in any shared environment. Never use local seed credentials in production.
