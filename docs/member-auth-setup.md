# Member authentication setup

The practice viewer uses Supabase Auth and PostgreSQL row-level security. The
collector and normalizer continue to use `SUPABASE_SECRET_KEY`; the viewer uses
only the browser-safe publishable key plus the signed-in user's JWT.

## 1. Apply the database schema

Run [`supabase/schema.sql`](../supabase/schema.sql) in the SIUS project's SQL
editor. The script is safe to rerun and adds:

- `sius_users`;
- `sius_member_access`;
- Auth user synchronization;
- administrator and member-access policies;
- read-only, column-limited access to authorized `sius_shots`.

Existing Auth users are backfilled as normal users. After the intended
administrator has signed up, promote that confirmed account in the SQL editor:

```sql
update public.sius_users
set role = 'admin', updated_at = now()
where email = lower('admin@example.com');
```

Confirm exactly one expected row was updated. Administrator assignment is kept
out of the web UI deliberately.

## 2. Configure viewer environment

Copy the browser-safe project URL and publishable key from the Supabase
**Connect** dialog:

```text
NEXT_PUBLIC_SUPABASE_URL=https://project-ref.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_replace_me
NEXT_PUBLIC_SITE_URL=https://shots.example.com
NEXT_PUBLIC_TURNSTILE_SITE_KEY=replace_me
SIUS_RANGE_ID=default-range
SIUS_VIEWER_TIMEZONE=America/Vancouver
```

`SIUS_RANGE_ID` is required and must match the collector's range ID. Keep
`SUPABASE_SECRET_KEY` available only to trusted ingestion and normalization
processes. Never prefix it with `NEXT_PUBLIC_`.

## 3. Configure Supabase Auth URLs and providers

In **Authentication > URL Configuration**:

1. Set the Site URL to the production viewer URL.
2. Add `https://shots.example.com/auth/callback`.
3. Add `http://127.0.0.1:3000/auth/callback` for local development.

In **Authentication > Sign In / Providers**:

1. Keep email/password enabled.
2. Require email confirmation.
3. Set the minimum password length to at least eight characters.
4. Enable Google after completing the Google OAuth setup below.
5. Leave anonymous sign-ins disabled.

### Google OAuth

Create a Web application OAuth client in Google Auth Platform:

1. Add the viewer origin, such as `https://shots.example.com`, to Authorized
   JavaScript origins.
2. Add the Supabase callback shown on its Google provider page, normally
   `https://project-ref.supabase.co/auth/v1/callback`, to Authorized redirect
   URIs.
3. Configure the consent screen for external users if members may use personal
   Gmail accounts.
4. Add only `openid`, email, and profile scopes.
5. Copy the client ID and secret into the Supabase Google provider settings.

## 4. Send Auth email through Google Workspace

Create `no-reply@rangexxx.com` as an alias on an existing licensed Workspace
user. The alias has no separate licence cost. Replies and delivery notices will
arrive in that user's mailbox.

Enable 2-Step Verification on the primary account and create a dedicated App
Password for Supabase.

In Google Admin, configure **Apps > Google Workspace > Gmail > Routing > SMTP
relay service**:

- Allowed senders: **Only addresses in my domains**
- Authentication: **Require SMTP Authentication**
- Encryption: **Require TLS**
- Do not restrict by source IP

In **Supabase > Authentication > SMTP Settings**, enable custom SMTP:

| Setting | Value |
|---|---|
| Host | `smtp-relay.gmail.com` |
| Port | `465` |
| Username | Primary email of the existing licensed Workspace user |
| Password | Dedicated Google App Password |
| Sender email | `no-reply@rangexxx.com` |
| Sender name | Range public name |

Configure Google Workspace DKIM and publish appropriate SPF and DMARC records
for the domain. Test signup confirmation and password recovery to both Gmail and
non-Gmail addresses before launch.

## 5. Enable abuse protection

Create a free Cloudflare Turnstile widget for the production viewer domain and
localhost testing domain.

1. Put its site key in `NEXT_PUBLIC_TURNSTILE_SITE_KEY`.
2. In **Supabase > Authentication > Bot and Abuse Protection**, enable
   Turnstile and enter its secret key.
3. Keep conservative signup and password-recovery rate limits. Custom SMTP
   starts with a project-wide email rate limit; raise it only after observing
   legitimate demand.

## 6. Verify the authorization boundary

Use separate test accounts for these checks:

1. A newly confirmed user sees no shots and can submit a member number.
2. The admin sees the pending request and approves it.
3. The user can see only the approved number.
4. A second number remains unavailable until separately approved.
5. Two users can both be approved for the same number.
6. Revocation removes access immediately.
7. Changing `/api/shots?memberNumber=...` cannot retrieve an unapproved number.
8. A direct Data API query with the user's JWT also returns only approved
   `sius_shots` rows.
9. The user cannot select raw events, sessions, phases, `payload`, or any other
   restricted shot columns.
