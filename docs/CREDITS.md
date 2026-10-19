# Credits and USDT payment setup

This guide preserves the payment setup instructions for use when you are ready.
The application currently runs on a Mac with a local FastAPI backend and Vite
frontend. Payment setup is deferred: these instructions do not mean that the
migration, merchant configuration, public tunnel, or real payments have been
verified on your machine.

The checked-out code is the source of truth. See also the
[README credits overview](../README.md#personal-credits-and-usdt-payments).

## Current behavior

- Each user has an individual wallet scoped to their tenant. Administrators
  cannot browse or fund another user's wallet through their own checkout.
- USDT payments use NOWPayments. Credit card payments are not implemented.
- One usable credit covers US$1 of reported OpenRouter provider cost.
- Purchases add a 5.5% service fee, rounded half-up to the nearest cent. For
  example, $10 usable credits costs $10.55, $25 costs $26.38, and $100 costs
  $105.50. There is no additional application markup when answers consume credit.
- Gateway/settlement fees come out of that surcharge. The sending wallet or
  exchange may charge network fees separately. Check current provider fees
  before going live; the surcharge is not a guarantee of net profit.
- Top-ups accept $10–$1,000 usable credits with at most two decimal places.
  Provider minimums and network availability can impose further restrictions.
- Available network choices are USDT on Tron (TRC-20), BNB Smart Chain (BEP-20),
  and Ethereum (ERC-20). Send the exact quoted crypto amount on the specified
  network; USDT should not be assumed to equal exactly US$1.
- Creating an order does not credit the wallet. Only a verified, fully paid
  `finished` payment adds the purchased usable credits.
- Sandbox and live balances are isolated. Sandbox credit cannot fund real
  generation. Payments and prepaid enforcement are disabled by default.
- Monthly tenant/user budgets remain separate. A purchase does not raise a
  monthly limit or unpause an account.
- Customer payments fund application wallets. The operator must fund the
  OpenRouter account separately.

## 1. Prepare the merchant account

Create/configure your NOWPayments merchant account and payout wallet. Confirm
eligibility for your Laos business directly with the provider before accepting
live payments. This guide does not establish merchant approval or local legal
eligibility.

Obtain separate sandbox and live credentials:

| Credential | Purpose |
| --- | --- |
| Sandbox API key | Create/check simulated payments using the sandbox API. |
| Sandbox IPN secret | Verify sandbox payment notifications. |
| Live API key | Create/check real payments using the live API. |
| Live IPN secret | Verify live payment notifications. |

Configure these privately on the backend. Never put secrets in `VITE_*`
variables, commit them, paste them into chat, or include them in screenshots.
Preserve the rest of your existing `.env`; do not replace it with `.env.example`.

References: [merchant account setup](https://nowpayments.io/help/about-nowpayments/how-to-start/how-to-set-up-an-account),
[API documentation](https://documenter.getpostman.com/view/7907941/S1a32n38),
[IPN configuration and verification](https://nowpayments.zendesk.com/hc/en-us/articles/21395546303389-IPN-and-how-to-setup),
and [current provider fees](https://nowpayments.io/help/about-nowpayments/about/what-are-your-fees).

## 2. Prepare credits storage

The API does not apply migrations automatically. If credits storage has not been
created, take a database backup and stop the API and ingestion workers for
approved maintenance. Existing security, accounts, and credit-budget migrations
must already be applied.

From the project root, run:

```bash
source .venv/bin/activate
python -m scripts.migrate_credits
```

The repeatable migration creates these five tables and their indexes, including
an ownership index on existing credit reservations:

- `credit_wallets`
- `credit_payment_orders`
- `credit_wallet_holds`
- `credit_wallet_ledger`
- `credit_payment_notifications`

It does not fund accounts, charge historical usage, or rewrite documents,
sessions, or existing reservations. Do not reset Docker volumes or recreate the
database to enable payments.

## 3. Expose only payment callbacks from your Mac

NOWPayments cannot deliver notifications to localhost. For a controlled test,
use a public HTTPS tunnel to the callback endpoints while keeping the UI local:

```text
Browser -> http://127.0.0.1:5173 -> Vite /api proxy -> FastAPI :8000
NOWPayments -> public HTTPS tunnel -> FastAPI payment callback :8000
```

You do not need a purchased domain, Caddy, a frontend production build, router
port forwarding, or an API bound to `0.0.0.0` for this setup.

### Install and authenticate ngrok

If Homebrew is installed:

```bash
brew install ngrok
```

Create an [ngrok account](https://dashboard.ngrok.com/signup) and follow its
dashboard instructions to configure your authtoken locally. Keep that token
private. Find the development domain assigned to your account.

Official instructions: [ngrok for macOS](https://ngrok.com/download/mac-os).
Free accounts include an assigned development domain and HTTPS tunneling, subject
to [plan limits](https://ngrok.com/docs/pricing-limits/free-plan-limits).

### Create a callback-only traffic policy

Create a file outside the repository:

```bash
nano ~/rag-payment-callbacks.yml
```

Paste:

```yaml
on_http_request:
  - expressions:
      - "req.method != 'POST' || (req.url.path != '/payments/nowpayments/sandbox/ipn' && req.url.path != '/payments/nowpayments/live/ipn')"
    actions:
      - type: custom-response
        config:
          status_code: 404
          body: "Not found"
          headers:
            content-type: text/plain
```

Save with Control+O, Enter, then exit with Control+X. This policy permits POSTs
to the two callback paths and rejects other requests before they reach FastAPI.
The application still requires a valid mode-specific HMAC signature for callbacks.
Do not add browser login, Basic Auth, or OAuth to those callbacks: the provider
must be able to POST without a user session.

Policy reference: [ngrok custom-response action](https://ngrok.com/docs/gateway/traffic-policy/actions/custom-response).

### Start the tunnel

Replace the example hostname below with your exact assigned domain, including
its actual suffix:

```bash
ngrok http http://127.0.0.1:8000 \
  --url https://YOUR-ASSIGNED-DOMAIN.ngrok-free.app \
  --traffic-policy-file "$HOME/rag-payment-callbacks.yml"
```

Leave this terminal running. Resolve any policy/plan error before continuing;
do not remove the policy to work around it. Keep tunnel inspection data private
because it can contain payment details and notification signatures.

## 4. Configure sandbox mode

Privately update the following entries in your existing `.env`, replacing the
placeholders with your domain and sandbox credentials:

```dotenv
RAG_PAYMENTS_MODE=sandbox
RAG_WALLET_ENFORCEMENT=false
RAG_PAYMENTS_CALLBACK_BASE_URL=https://YOUR-ASSIGNED-DOMAIN.ngrok-free.app
NOWPAYMENTS_SANDBOX_API_KEY=YOUR_SANDBOX_API_KEY
NOWPAYMENTS_SANDBOX_IPN_SECRET=YOUR_SANDBOX_IPN_SECRET
```

**Do not append `/api` to this tunnel callback base URL.** ngrok forwards directly
to FastAPI, whose callback paths have no `/api` prefix. The application adds the
remaining path automatically:

```text
https://YOUR-ASSIGNED-DOMAIN.ngrok-free.app/payments/nowpayments/sandbox/ipn
```

The README's example ending in `/api` applies when an external callback passes
through the frontend/web reverse proxy that strips that prefix. Use the base URL
matching the actual deployment; do not include the full callback path in the
base URL setting.

The sandbox adapter uses `https://api-sandbox.nowpayments.io/v1/payment` with
the simulated `success` case. Never send real cryptocurrency to sandbox addresses.

## 5. Start the local application

Restart the API after changing `.env`; do not rely on reload detecting it. From
the project root:

```bash
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Omit `--reload` during the live payment test to avoid file edits restarting the
API mid-request. Stop an existing API with Control+C in its terminal before
starting its replacement.

In a separate terminal, from the project root:

```bash
cd frontend
npm run dev
```

Open `http://127.0.0.1:5173/credits` and sign in. Continue using the local URL;
the tunnel root is intentionally blocked.

The ingestion worker can run in another terminal when document processing is
needed:

```bash
source .venv/bin/activate
python -m scripts.ingestion_worker
```

The worker is separate from FastAPI and is not required to process payment
callbacks. Keep the API, frontend, and ngrok running for the payment test.

## 6. Verify the tunnel and sandbox flow

Replace the hostname before running these checks. With the sandbox IPN secret
configured and the API restarted:

```bash
curl -i -X POST \
  https://YOUR-ASSIGNED-DOMAIN.ngrok-free.app/payments/nowpayments/sandbox/ipn \
  -H 'Content-Type: application/json' \
  --data '{}'
```

Expect HTTP `401` with `{"detail":"Invalid payment signature"}`. This confirms
the callback reaches the application and unsigned requests are rejected. It
does not create an order or add credit.

Verify another route is blocked:

```bash
curl -i https://YOUR-ASSIGNED-DOMAIN.ngrok-free.app/docs
```

Expect HTTP `404` with `Not found`. The same restriction applies to `/ask`,
`/documents`, `/health`, and GET requests to callback paths. Use localhost for
ordinary API requests. ngrok's free-tier browser interstitial does not normally
affect programmatic API traffic; see its plan documentation linked above.

On the local Credits page:

1. Confirm sandbox mode is displayed.
2. Create a simulated top-up; do not send real funds.
3. Verify the order becomes `finished` and its usable amount appears once.
4. Use **Check status** again and confirm neither the balance nor ledger gains
   a duplicate credit.

A successfully processed, correctly signed callback returns HTTP `204` with no
body. A local unsigned curl check alone does not verify provider delivery or
successful settlement; complete the sandbox flow before switching to live.

## 7. Enable a small live test

Proceed after merchant eligibility, fees, sandbox callbacks, and reconciliation
are verified. Privately configure separate live credentials:

```dotenv
RAG_PAYMENTS_MODE=live
RAG_WALLET_ENFORCEMENT=true
LLM_PROVIDER=openrouter
RAG_PAYMENTS_CALLBACK_BASE_URL=https://YOUR-ASSIGNED-DOMAIN.ngrok-free.app
NOWPAYMENTS_API_KEY=YOUR_LIVE_API_KEY
NOWPAYMENTS_IPN_SECRET=YOUR_LIVE_IPN_SECRET
```

Keep sandbox credentials available for outstanding sandbox notifications.
Restart FastAPI. Sandbox balances do not transfer to live, and new live wallets
start at zero. With enforcement enabled, all roles need their own available live
balance to ask paid questions. Enforcement requires live mode and OpenRouter;
unsupported combinations fail closed. Leaving enforcement `false` permits usage
without requiring a purchased wallet balance, subject to existing monthly budgets.

For the first real purchase:

1. Sign in as the user whose wallet should receive the funds.
2. Choose $10 usable credit, if permitted by the selected network's provider
   minimum. The application USD quote is $10.55 including the service fee.
3. Send exactly the quoted USDT amount on the displayed network before expiry.
   Account for the sender's separate network fee; do not deduct it from the
   required payment amount.
4. Wait for `finished`; confirmations can take time. Do not send again just
   because the order is still confirming.
5. Verify exactly $10 usable credit and one top-up ledger entry appear.
6. Use **Check status** and verify there is no duplicate credit.
7. Ask a question with authorized sources and verify its reported provider cost
   is deducted. Confirm that the operator's OpenRouter account is funded.

Keep the Mac awake, online, and the tunnel/API running until settlement. A Mac
tunnel is suitable for this controlled test; a public launch needs an always-on
HTTPS deployment and operational verification.

## Accounting and security behavior

- API keys and IPN secrets stay on the backend. Wallet/history endpoints require
  authentication and scope access to the requesting tenant/user.
- Public callbacks require `x-nowpayments-sig` HMAC-SHA512 verification, bounded
  payloads, matching order/payment/quote details, and transactional replay
  protection. Final payment/refund states are also checked with the provider.
- Repeated callbacks and manual checks cannot credit the same order twice.
  Creating an order or receiving an intermediate status grants no credit.
- Full verified refunds reverse the original credit once. Partial refunds and
  inconsistent/partial payments require operator review. The application does
  not initiate crypto refunds or payouts.
- Upfront wallet holds and monthly budget reservations are atomic. Retrieval
  failures and empty-source answers release unused holds. Reported provider
  costs settle usage and release holds together.
- If generation may have occurred but its cost is unreported, the hold remains;
  it is not silently treated as zero and does not expire at a month boundary.
- Actual costs above the reservation, or refunds after spending credit, can
  create a negative balance that blocks further reservations.

## Troubleshooting and recovery

| Symptom | Action |
| --- | --- |
| API reports address already in use | Stop the existing API in its terminal. Inspect with `lsof -nP -iTCP:8000 -sTCP:LISTEN` if necessary; do not start a second copy. |
| `Credits storage unavailable` | Verify database connectivity and that the credits migration and prerequisites were applied. Do not recreate the database. |
| `USDT payments are not enabled or configured` | Check payment mode, credentials for that mode, HTTPS callback base URL, then restart FastAPI. |
| Unsigned callback curl returns `503` | Configure the mode's IPN secret and restart the API; the expected unsigned response is `401`. |
| Real callbacks return `401` | Check the mode-specific IPN secret and provider signature setup. Preserve signature verification. |
| Tunnel connection/upstream error | Check that ngrok and FastAPI are running, the upstream is port 8000, and the Mac is awake/online. |
| Callback returns `404` | Check the exact path, POST method, domain, traffic policy, and absence of `/api` for this direct tunnel. |
| Pending payment does not update | Use the existing order's **Check status**. Visible pending orders poll application storage; this button queries the provider. |
| Order creation times out or enters `review` | Do not blindly create/pay another order. Locate the app order UUID in the provider dashboard; a payment may already exist. |
| Creation failed before a provider ID was stored | Review the matching order in the provider dashboard and request an IPN resend after locating it. Do not manually edit balances. |
| Balance exists but questions are blocked | Check available versus held credit, selected mode, monthly limits, paused policies, account permissions, and provider funding. |
| Sandbox funds disappear after switching modes | Expected: sandbox and live wallets are isolated. |

Order creation attempts are limited to five per user/mode in 15 minutes.
Automatic provider POST retries are deliberately avoided because a timed-out
request may already have created an order.

Stopping ngrok does not cancel a blockchain payment. Keep the same public URL
working for pending orders: each order records its callback URL when created.
Changing `.env` affects new orders, not callback URLs already sent to the
provider. Use **Check status** for an existing order with a known provider ID,
or request a provider IPN resend when appropriate. Never delete historical
reservations, receipts, or ledger entries to force reconciliation.

## Pause or roll back activation

Review pending payments and unknown-cost holds. Stop accepting new work and let
in-flight generation settle before changing payment mode: wallet finalization
depends on live mode. After that, to disable new purchases and prepaid deductions:

```dotenv
RAG_PAYMENTS_MODE=disabled
RAG_WALLET_ENFORCEMENT=false
```

Restart the API. Disabling enforcement allows existing generation behavior under
monthly budgets; it is not a general spending pause. Use the existing budget
pause controls if generation must stop.

Keep credentials, the callback endpoint, and its public URL available for
outstanding payments. Signed notifications can still settle orders in their
original sandbox/live mode even when new purchases are disabled. Preserve all
wallet, hold, order, receipt, and ledger tables; no destructive rollback is
required.

## Validation status and relevant checks

Automated payment coverage uses mocked database/provider operations. It does
not establish live PostgreSQL migration compatibility, merchant approval,
network availability, sandbox delivery, or successful real-money settlement.
Complete the checks in this guide on the actual deployment before activation.

For future code changes, run relevant tests from the project root:

```bash
source .venv/bin/activate
python -m pytest tests/test_credits.py tests/test_nowpayments.py tests/test_credit_budgets.py -q
```

Frontend Credits coverage is in `frontend/src/CreditsPanel.test.tsx`, with
navigation/API coverage in `App.test.tsx` and `api.test.ts`:

```bash
cd frontend
npm test -- src/CreditsPanel.test.tsx src/App.test.tsx src/api.test.ts
```

Relevant implementation files: `app/credits_api.py`, `app/credit_payments.py`,
`app/credit_wallets.py`, `app/credit_budgets.py`, `app/nowpayments.py`,
`app/settings.py`, `scripts/migrate_credits.py`, and
`frontend/src/CreditsPanel.tsx`.
