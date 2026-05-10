# NEO API v2 Migration Plan – Phase by Phase

## Overview
Kotak NEO APIs are migrating from v1 (gw-napi/napi) to v2 (mis + dynamic baseUrl). Follow phases in order.

**Reference:** Postman collection `Client_AP_Is_postman_collection_82fa888c63.json` – use for exact URLs, headers, and body formats.

---

## Postman Collection Reference (Client APIs)

### Environment Variables (Postman → Code Mapping)

| Postman Variable | Source | Code Equivalent |
|------------------|--------|-----------------|
| `consumerKey` | Neo app dashboard (plain token) | `NEO_ACCESS_TOKEN` or `access_token` from env |
| `sidView` | TOTP response `data.sid` | `login_data["data"]["sid"]` |
| `viewtoken` | TOTP response `data.token` | `login_data["data"]["token"]` |
| `sidSession` | MPIN response `data.sid` | `session_data["data"]["sid"]` |
| `sessiontoken` | MPIN response `data.token` | `session_data["data"]["token"]` |
| `baseUrl` | MPIN response `data.baseUrl` | `session_data["data"]["baseUrl"]` |

### Login APIs (Exact Specs from Postman)

**TOTP Login (tradeApiLogin)**
- URL: `https://mis.kotaksecurities.com/login/1.0/tradeApiLogin`
- Method: POST
- Headers: `neo-fin-key: neotradeapi`, `Authorization: {{consumerKey}}` (plain, no Bearer)
- Body: `{"mobileNumber": "+91...", "ucc": "Y4HAU", "totp": "124579"}`
- Response: `data.token` → viewtoken, `data.sid` → sidView

**MPIN Validate (tradeApiValidate)**
- URL: `https://mis.kotaksecurities.com/login/1.0/tradeApiValidate`
- Method: POST
- Headers: `Authorization: {{consumerKey}}`, `neo-fin-key: neotradeapi`, `sid: {{sidView}}`, `Auth: {{viewtoken}}`
- Body: `{"mpin": "123456"}`
- Response: `data.token` → sessiontoken, `data.sid` → sidSession, `data.baseUrl` → baseUrl

### Order APIs (Headers: Sid, Auth, Content-Type – NO Authorization)

| API | Method | URL | Body (jData) |
|-----|--------|-----|--------------|
| Place order | POST | `{{baseUrl}}/quick/order/rule/ms/place` | Order payload |
| Modify order | POST | `{{baseUrl}}/quick/order/vr/modify` | Order + `no` (orderNo) |
| Cancel order | POST | `{{baseUrl}}/quick/order/cancel` | `{"on":"{{orderNo}}","am":"NO"}` |
| Exit Cover | POST | `{{baseUrl}}/quick/order/co/exit` | `{"on":"{{orderNo}}","am":"NO"}` |
| Exit Bracket | POST | `{{baseUrl}}/quick/order/bo/exit` | `{"on":"{{orderNo}}","am":"NO"}` |

### Report APIs (Headers: Sid, Auth, Content-Type – NO Authorization)

| API | Method | URL |
|-----|--------|-----|
| Order history | POST | `{{baseUrl}}/quick/order/history` |
| Order book | GET | `{{baseUrl}}/quick/user/orders` |
| Trade book | GET | `{{baseUrl}}/quick/user/trades` |
| Positions book | GET | `{{baseUrl}}/quick/user/positions` |
| Portfolio holdings | GET | `{{baseUrl}}/portfolio/v1/holdings` |

### Other APIs

| API | Method | URL | Headers |
|-----|--------|-----|---------|
| Check margin | POST | `{{baseUrl}}/quick/user/check-margin` | Sid, Auth (no Authorization) |
| Limits | POST | `{{baseUrl}}/quick/user/limits` | Sid, Auth (no Authorization) |
| Quotes | GET | `{{baseUrl}}/script-details/1.0/quotes/neosymbol/{symbols}/all` | `Authorization: {{consumerKey}}` (plain) |
| Scrip master | GET | `{{baseUrl}}/script-details/1.0/masterscrip/file-paths` | `Authorization: {{consumerKey}}` (plain) |

**Note:** Quotes and Scripmaster use **plain token** in `Authorization` header. Orders/Reports/Portfolio use **Sid + Auth only** (no Authorization).

---

## What to Do – Step by Step

1. **Import Postman** → Import `Client_AP_Is_postman_collection_82fa888c63.json`
2. **Set env** → Create Postman env var `consumerKey` = Neo app token
3. **Test login** → Run TOTP_Validate → MPIN_Validate; confirm `baseUrl` is set
4. **Phase 1** → Replace OAuth2 with env token (`NEO_ACCESS_TOKEN`)
5. **Phase 2** → Update login URLs to `mis.kotaksecurities.com`, use plain token
6. **Phase 3** → Save `baseUrl` from MPIN response in session
7. **Phase 4** → Place order: use `baseUrl`, headers = Sid + Auth + Content-Type
8. **Phase 5** → Portfolio validation: use `baseUrl`, Sid + Auth
9. **Phase 6** → Quotes: `baseUrl` + path, `Authorization: {plain_token}`
10. **Phase 7** → Scripmaster: same as Quotes
11. **Phase 9** → Full flow test

---

## Phase 0: Pre-Migration Setup (Do First)

### 0.1 Get New Access Token Source
- [ ] Login to **Kotak Neo app** or **Neo web**
- [ ] Go to **More** → **TradeAPI** card → **API Dashboard**
- [ ] Create application if not done
- [ ] Copy your **Access Token** (plain token, no Bearer)
- [ ] Add to `.env`: `NEO_ACCESS_TOKEN=<your_token>` (or keep using existing var name)

### 0.2 Register TOTP (if not done)
- [ ] On API Dashboard → **TOTP Registration**
- [ ] Verify with mobile, OTP, client code
- [ ] Scan QR with Google/Microsoft Authenticator
- [ ] Confirm "TOTP successfully registered"

### 0.3 Import Postman Collection & Setup
- [ ] Import `Client_AP_Is_postman_collection_82fa888c63.json` into Postman
- [ ] Create Postman environment with variable: `consumerKey` = your Neo app access token (plain)
- [ ] Run **TOTP_Validate** → **MPIN_Validate** in sequence (test scripts auto-set `viewtoken`, `sidView`, `sessiontoken`, `sidSession`, `baseUrl`)
- [ ] Verify login flow works before coding

---

## Phase 1: Access Token – Remove OAuth2

**Goal:** Stop using `/oauth2/token`; use token from Neo dashboard.

### 1.1 Update `neo_login/get_access_token.py`
- [ ] Remove OAuth2 API call logic
- [ ] Replace with: read token from env (e.g. `NEO_ACCESS_TOKEN` or `ACCESS_TOKEN`)
- [ ] Return `{"access_token": "<token_from_env>"}` for compatibility
- [ ] Or: create `get_neo_token.py` that reads from env and deprecate `get_access_token.py`

### 1.2 Update `neo_main_login.py`
- [ ] Ensure it still receives `access_token` (from env or new module)
- [ ] Remove dependency on `CLIENT_CREDENTIALS` for token fetch if switching to env token

### 1.3 Update `.env`
- [ ] Add `NEO_ACCESS_TOKEN` (or reuse `ACCESS_TOKEN`)
- [ ] Remove `CLIENT_CREDENTIALS` when no longer needed (after Phase 1)

**Files:** `neo_login/get_access_token.py`, `neo_main_login.py`, `.env`

---

## Phase 2: Login Endpoints – Switch to mis.kotaksecurities.com

**Goal:** Use new fixed login URLs and plain token (no Bearer).

### 2.1 Update `neo_login/get_token_totp.py`
- [ ] Change `base_url` to `https://mis.kotaksecurities.com`
- [ ] Change path: `/login/1.0/login/v6/totp/login` → `/login/1.0/tradeApiLogin`
- [ ] Change header: `Authorization: Bearer {token}` → `Authorization: {token}` (plain)
- [ ] Test TOTP login

### 2.2 Update `neo_login/get_final_session.py`
- [ ] Change `base_url` to `https://mis.kotaksecurities.com`
- [ ] Change path: `/login/1.0/login/v6/totp/validate` → `/login/1.0/tradeApiValidate`
- [ ] Change header: `Authorization: Bearer {token}` → `Authorization: {token}` (plain)
- [ ] **Important:** Parse response and extract `baseUrl` – store it for later phases
- [ ] Test MPIN validation

**Files:** `neo_login/get_token_totp.py`, `neo_login/get_final_session.py`

---

## Phase 3: Session Manager – Store and Use baseUrl

**Goal:** Save `baseUrl` from MPIN response; use it for all non-login APIs.

### 3.1 Update `neo_login/session_manager.py`
- [ ] Add `base_url` (or `baseUrl`) to session data saved in `save_session()`
- [ ] Read `baseUrl` from MPIN response (e.g. `session_data["data"]["baseUrl"]` – verify key from Postman)
- [ ] Persist `base_url` in `kotak_session.json`
- [ ] Add `get_base_url()` or ensure `load_session()` returns `base_url`
- [ ] Remove hardcoded `self.base_url = "https://gw-napi.kotaksecurities.com"`
- [ ] Use session's `base_url` for `validate_session()` (portfolio holdings call)

### 3.2 Update `neo_main_login.py`
- [ ] Ensure `session_manager.save_session(session_data)` receives MPIN response that includes `baseUrl`
- [ ] Verify `baseUrl` is present in response before saving

**Files:** `neo_login/session_manager.py`, `neo_main_login.py`

---

## Phase 4: Order APIs – Use baseUrl, Drop Authorization

**Goal:** Place order using `{{baseUrl}}/quick/order/rule/ms/place`; no `Authorization` header.

### 4.1 Update `place_order.py`
- [ ] Get `base_url` from session (via `session_manager.load_session()`)
- [ ] Build URL: `f"{base_url}/quick/order/rule/ms/place"`
- [ ] Headers (per Postman): `Sid`, `Auth`, `Content-Type` only – **remove** `Authorization` and `neo-fin-key`
- [ ] Test place order

**Files:** `place_order.py`

---

## Phase 5: Portfolio & Session Validation – Use baseUrl

**Goal:** Portfolio holdings and session validation use `{{baseUrl}}/portfolio/v1/holdings`.

### 5.1 Update `neo_login/session_manager.py`
- [ ] In `validate_session()`: use `session_data.get("base_url")` or `base_url`
- [ ] URL: `f"{base_url}/portfolio/v1/holdings?alt=false"`
- [ ] Drop `Authorization` header for this call (per migration guide: Orders/Reports use baseUrl, drop Authorization)
- [ ] Handle portfolio response structure change if any

**Files:** `neo_login/session_manager.py`

---

## Phase 6: Quotes API – Use baseUrl + Plain Token

**Goal:** Quotes use `{{baseUrl}}/script-details/1.0/quotes/` with plain token in `Authorization`.

### 6.1 Update `get_quote.py`
- [ ] Get `base_url` from session
- [ ] New path: `{base_url}/script-details/1.0/quotes/neosymbol/{symbols}/all` (verify exact path from Postman)
- [ ] Use plain token: `Authorization: {access_token}` (no Bearer)
- [ ] Test quote fetch

**Files:** `get_quote.py`

---

## Phase 7: Scripmaster / Files API – Use baseUrl + Plain Token

**Goal:** File paths use `{{baseUrl}}/script-details/1.0/masterscrip/file-paths`.

### 7.1 Update `nse_url_test.py`
- [ ] Get `base_url` from session
- [ ] New path: `{base_url}/script-details/1.0/masterscrip/file-paths` (verify exact path from Postman)
- [ ] Use plain token in `Authorization` header
- [ ] Test scripmaster fetch

**Files:** `nse_url_test.py`

---

## Phase 8: Other Order/Report APIs (If Used)

If you use modify, cancel, order history, order book, trade book, positions, check-margin, limits:

| API           | New Path                                      |
|---------------|-----------------------------------------------|
| Modify Order  | `{{baseUrl}}/quick/order/vr/modify`           |
| Cancel Order  | `{{baseUrl}}/quick/order/cancel`              |
| Exit Cover    | `{{baseUrl}}/quick/order/co/exit`             |
| Exit Bracket  | `{{baseUrl}}/quick/order/bo/exit`             |
| Order History | `{{baseUrl}}/quick/order/history`             |
| Order Book    | `{{baseUrl}}/quick/user/orders`               |
| Trade Book    | `{{baseUrl}}/quick/user/trades`               |
| Positions     | `{{baseUrl}}/quick/user/positions`           |
| Check Margin  | `{{baseUrl}}/quick/user/check-margin`         |
| Limits        | `{{baseUrl}}/quick/user/limits`               |

- [ ] Search codebase for these endpoints
- [ ] Replace with `base_url` + path, drop `Authorization` header

---

## Phase 9: Cleanup & Testing

### 9.1 Remove Deprecated Code
- [ ] Remove or fully deprecate `get_access_token.py` OAuth2 logic
- [ ] Remove `CLIENT_CREDENTIALS` from `.env` if unused
- [ ] Remove any `Bearer` prefix from remaining code

### 9.2 Full Flow Test
- [ ] Delete `kotak_session.json` to force fresh login
- [ ] Run `neo_main_login` → verify login with new endpoints
- [ ] Verify `base_url` saved in session
- [ ] Test: place order, get quote, portfolio, scripmaster
- [ ] Test session reuse (existing session with base_url)

### 9.3 Update memory_context.md
- [ ] Add migration completion summary
- [ ] Note any response structure changes

---

## Quick Reference: Header Rules

| API Type              | Authorization Header      | baseUrl |
|-----------------------|---------------------------|---------|
| Login (TOTP, MPIN)    | Plain token (no Bearer)   | Fixed: mis.kotaksecurities.com |
| Orders, Reports, Portfolio | **Drop** Authorization   | From MPIN response |
| Quotes, Scripmaster   | Plain token (no Bearer)   | From MPIN response |

---

## Order of Execution

1. **Phase 0** – Setup (manual)
2. **Phase 1** – Access token
3. **Phase 2** – Login endpoints
4. **Phase 3** – Session + baseUrl
5. **Phase 4** – Place order
6. **Phase 5** – Portfolio validation
7. **Phase 6** – Quotes
8. **Phase 7** – Scripmaster
9. **Phase 8** – Other APIs (if used)
10. **Phase 9** – Cleanup & test

---

## Notes

- **Postman collection:** `Client_AP_Is_postman_collection_82fa888c63.json` – optional: copy to `resource/` for project reference
- **Parallel run:** Old and new APIs work together for some time; migrate before deprecation
- **T&C:** https://bit.ly/3IELfC8
- **Portfolio holdings:** Postman uses `{{baseUrl}}/portfolio/v1/holdings` (no query). Current code has `?alt=false` – test both if validation fails
