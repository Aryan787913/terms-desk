# Security

Terms Desk is a hackathon prototype that runs against the **PayPal Sandbox only**.

- No real money, no real customer data. All clients and payment history in this repo are fictional demo data.
- The agent refuses to start when `PAYPAL_ENV=live`.
- Credentials are read from a local `.env` file, which is git-ignored. No keys are stored in this repository.
- The live demo (GitHub Pages) is a static page. It makes no network calls to PayPal and holds no credentials. A Content Security Policy limits it to its own files.

## Reporting a problem

Please open a private report via GitHub's "Report a vulnerability" button on the Security tab, rather than a public issue.
