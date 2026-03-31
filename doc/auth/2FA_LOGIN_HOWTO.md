# Dashboard 2FA (Login + Configuration) – How to Develop

## Goal
- **Login with 2FA**: After correct password, if user has 2FA enabled → show TOTP step → verify code → then issue session.
- **Configure 2FA**: From dashboard, user can **enable** 2FA (QR + confirm with code) or **disable** 2FA (with password or TOTP).

## Stack (already in project)
- **Backend**: FastAPI, aiosqlite, `pyotp` (already in requirements).
- **Optional**: `qrcode` + `pillow` for QR image (or expose provisioning URI and render QR in frontend via JS).

---

## 1. Database

Add columns to `users` (migration or ALTER in init):

- `totp_secret TEXT` – encrypted or plain TOTP secret (per user).
- `totp_enabled INTEGER DEFAULT 0` – 1 = 2FA on.

In `init_db()` (or one-off migration):  
`ALTER TABLE users ADD COLUMN totp_secret TEXT;`  
`ALTER TABLE users ADD COLUMN totp_enabled INTEGER DEFAULT 0;`

---

## 2. Backend API (nse_url_test.py)

### 2.1 Login flow (two steps when 2FA is on)

**Current:** `POST /api/login` { username, password } → { session_token, ... }.

**New behaviour:**

1. **First call** (same body): Check username + password.  
   - If 2FA **disabled** → return session_token as today (no change).  
   - If 2FA **enabled** → do **not** create session. Return e.g.  
     `{ "success": true, "requires_2fa": true, "login_id": "<short-lived token>" }`.  
     Store `login_id` in memory or DB with short TTL (e.g. 5 min), tied to `user_id`.

2. **Second call** (2FA step): New endpoint e.g.  
   `POST /api/login/verify_2fa`  
   Body: `{ "login_id": "...", "totp_code": "123456" }`.  
   - Validate `login_id` and TOTP with `pyotp.TOTP(user.totp_secret).verify(totp_code)`.  
   - If OK → create session, return `session_token`; delete/expire `login_id`.

So: **login** = password only, or password → then 2FA step with `login_id` + TOTP.

### 2.2 Enable 2FA (from dashboard, user already logged in)

- **GET (or POST) /api/2fa/setup**  
  - Require valid session (e.g. `verify_session`).  
  - Generate new secret: `secret = pyotp.random_base32()`.  
  - Save to user: `totp_secret = secret`, leave `totp_enabled = 0` until verified.  
  - Return `{ "secret": "<base32>", "provisioning_uri": pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name="Stock Dashboard") }`.  
  - Frontend shows QR (from `provisioning_uri`) and/or manual entry.

- **POST /api/2fa/enable**  
  Body: `{ "totp_code": "123456" }`.  
  - Session required.  
  - Verify current user’s `totp_secret` with `pyotp.TOTP(totp_secret).verify(totp_code)`.  
  - If OK → set `totp_enabled = 1`, return success.

### 2.3 Disable 2FA

- **POST /api/2fa/disable**  
  Body: `{ "password": "..." }` or `{ "totp_code": "..." }`.  
  - Session required.  
  - Verify password (hash compare) or TOTP.  
  - Set `totp_enabled = 0`, optionally clear `totp_secret`.

### 2.4 Optional: get 2FA status

- **GET /api/2fa/status**  
  - Session required.  
  - Return `{ "enabled": true/false }` (do not return secret).

---

## 3. Frontend

### 3.1 Login page (static/login.html)

- On submit, call `POST /api/login` with username + password.
- If response has `requires_2fa: true` and `login_id`:
  - Hide username/password form (or leave read-only).
  - Show TOTP input and “Verify” button.
  - On Verify: `POST /api/login/verify_2fa` with `login_id` + `totp_code`.
  - On success → save `session_token`, redirect to `/dashboard`.
- If no `requires_2fa` → current behaviour (save token, redirect).

### 3.2 Dashboard – 2FA configuration

- Add a “Security” or “2FA” section (e.g. in settings or profile).
- **If 2FA disabled:**  
  - “Enable 2FA” → call `GET /api/2fa/setup` → show QR (e.g. use `provisioning_uri` with a QR lib like `qrcode.js` or an image from backend) and secret for manual entry.  
  - User enters code from app → “Confirm” calls `POST /api/2fa/enable` with `totp_code`.
- **If 2FA enabled:**  
  - “Disable 2FA” → ask password or TOTP → `POST /api/2fa/disable`.

---

## 4. Security notes

- Store `totp_secret` in DB; optionally encrypt at rest (e.g. with a key from env).
- `login_id` must be one-time and short-lived (e.g. 5 min).
- Rate-limit 2FA attempts (e.g. per user / per IP).
- On disable 2FA, require either password or current TOTP.

---

## 5. Implementation order

1. DB: add `totp_secret`, `totp_enabled` to `users` (init or migration).
2. Backend: `/api/login` – if user has 2FA, return `requires_2fa` + `login_id`; store `login_id` in memory/DB with TTL.
3. Backend: `POST /api/login/verify_2fa` – validate `login_id` + TOTP, create session.
4. Backend: `GET /api/2fa/setup`, `POST /api/2fa/enable`, `POST /api/2fa/disable`, optional `GET /api/2fa/status`.
5. Frontend login: handle `requires_2fa` and TOTP step.
6. Frontend dashboard: 2FA enable/disable UI and QR display.

---

## 6. QR code for provisioning URI

- **Option A**: Backend returns `provisioning_uri`; frontend uses a JS library (e.g. `qrcode.js`, or a CDN) to render QR from that URL.
- **Option B**: Backend generates PNG with `qrcode` + `pillow`: add `qrcode` to requirements, return image in `GET /api/2fa/setup` or a separate `GET /api/2fa/qr`.

Once this is in place, “updating or login using 2FA configuration” is covered: login uses 2FA when enabled, and users can enable/disable 2FA from the dashboard.
