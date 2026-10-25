# Basecoat launch checklist

This package is prepared for a first always-on deployment to Render. It is not yet live. The owner must create the hosting and payment accounts and set private secrets in their dashboards.

## Hosting setup

1. Create a private GitHub repository. Upload the app source and render.yaml. Keep basecoat.db, the uploads folder, .env files, passwords, and Stripe keys out of the repository. .gitignore lists the local data and secret files.
2. Create a Render account, connect the private repository, and deploy its Blueprint from render.yaml. The configuration uses a paid, always-on web service and a persistent disk. The Render free web plan can sleep and does not meet the always-on request.
3. Set the initial owner email, name, and a unique password of at least 14 characters when Render asks for the BASECOAT_OWNER_* values. Keep the generated BASECOAT_SECRET. Do not copy the local demo database into production.
4. After Render assigns the site's HTTPS address, set BASECOAT_PUBLIC_URL to that exact address and redeploy. A custom domain can be connected later.
5. The first production database starts without demo workers, customers, sample jobs, or the local 321 password. Sign in as the bootstrapped owner, change the password if desired, and create real worker and customer accounts under Accounts. Share temporary passwords privately; users can change them under Change password.

## Google sign-in

1. In Google Cloud Console, create an OAuth 2.0 Web application client. Add the deployed HTTPS origin as an authorized JavaScript origin and `https://YOUR-SITE/auth/google/callback` as an authorized redirect URI.
2. Add the resulting client ID and client secret to Render as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Never put these values in the source repository or chat.
3. Test sign-in with both customer and worker choices. Google uses a verified email and its stable account identifier to find/link accounts. A new worker remains pending until the owner approves them under Accounts and sets their rank and hourly rate. Existing owner-created accounts stay active.

## Worker location sharing

Workers can choose to share location from the shift screen. The browser asks for permission; updates are sent only while clocked in and the app page is visible, and are removed when the worker clocks out. A site owner can set a site's center by using “Set site boundary” while physically at the job site; 500 feet is the starting radius. The owner-only Shift Tracking screen marks readings outside that boundary or older than two minutes. Browser location depends on device permission, signal, and the page staying available; it can report stale or missing data and cannot prevent someone from leaving. Tell workers clearly how this is used and get Michigan employment/privacy advice before using it for official decisions.

## Stripe setup

1. Create and verify the business's Stripe account and configure its payout bank account.
2. Start with Stripe test-mode keys. Add the test secret key as STRIPE_SECRET_KEY in Render.
3. In Stripe, create a webhook endpoint at https://YOUR-SITE/api/stripe/webhook and subscribe to checkout.session.completed and checkout.session.async_payment_succeeded. Put its signing secret in Render as STRIPE_WEBHOOK_SECRET.
4. Test the whole flow: link a customer account to a job, mark the job Complete, request final payment from Payments, sign in to the customer account, and pay through Stripe test checkout. Confirm the invoice changes to Paid only after Stripe confirms the payment.
5. Switch to live-mode keys only after test checkout and webhook delivery both succeed. Keep all Stripe secrets in Render, never in this repository or in chat.

The customer can see a payment request in the app after signing in. This build does not send payment-request emails or SMS. Stripe Checkout collects the remaining invoice balance; it does not handle worker payroll or automatically charge a customer before the owner requests payment.

## Data and operating limits

This initial deployment uses SQLite and uploaded files on one attached persistent disk. It stays online when the owner's PC is off, but the service must remain at one instance; the disk prevents horizontal scaling. Start with the configured 1 GB disk and monitor usage, especially inspection and job photos. Back up/export business records regularly. A larger business should move the database to managed PostgreSQL and photos to private object storage before adding multiple app instances.

The current Michigan Terms of Service is a draft, not a reviewed construction contract. Before signing customers, have a Michigan construction attorney review the contract and notices, and confirm company identity, licensing, insurance, warranties, cancellation rights, payment schedule, and lien language.

## Expected charges

Render lists its Starter compute plan at $6/month and persistent disk storage at $0.25 per GB/month; the current Blueprint requests a 1 GB disk. Bandwidth or other account charges may add to that amount. Stripe's standard US pricing currently lists 2.9% + 30¢ per successful domestic-card transaction. Check the providers' current pricing before activating live service.
