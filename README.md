# Basket Brief

Basket Brief is a grocery price tracker built for a cheap serverless stack:

- Frontend: static app on Vercel
- Backend: AWS Lambda + API Gateway + DynamoDB on-demand + S3 for receipt uploads
- Optional receipt OCR: AWS Textract, only invoked when you use photo scanning

## What the app does

- Dashboard with this month's spend vs last month
- Unique item count
- Fake special detection based on your own price history
- Spend breakdown by store
- Five most recent entries with price movement arrows
- Manual item logging
- Bulk receipt import from pasted text like `Bananas   R24.99`
- Photo scanning scaffold with signed S3 upload URLs and a Textract-backed scan endpoint

## Why this stays low-cost

- No always-on servers
- Lambda runs only when the app is used
- DynamoDB uses on-demand billing
- S3 stores receipt images cheaply
- Textract is only used if you trigger image scanning

For a personal project or light usage, this should stay very inexpensive compared with running EC2, ECS, or a traditional database server.

## Project layout

- [index.html](/Users/romanomoses/Documents/romano_github_repos/grocery_app/index.html): static Vercel frontend shell
- [app.js](/Users/romanomoses/Documents/romano_github_repos/grocery_app/app.js): frontend data fetching and UI rendering
- [styles.css](/Users/romanomoses/Documents/romano_github_repos/grocery_app/styles.css): app styling
- [api/config.js](/Users/romanomoses/Documents/romano_github_repos/grocery_app/api/config.js): Vercel function that exposes the AWS API URL to the browser
- [cdk_app.py](/Users/romanomoses/Documents/romano_github_repos/grocery_app/cdk_app.py): CDK app entrypoint
- [grocery_app/grocery_app_stack.py](/Users/romanomoses/Documents/romano_github_repos/grocery_app/grocery_app/grocery_app_stack.py): AWS infrastructure
- [grocery_app/lambda/api/handler.py](/Users/romanomoses/Documents/romano_github_repos/grocery_app/grocery_app/lambda/api/handler.py): backend CRUD, summary, specials logic, receipt text import, signed uploads
- [grocery_app/lambda/ocr_scan/handler.py](/Users/romanomoses/Documents/romano_github_repos/grocery_app/grocery_app/lambda/ocr_scan/handler.py): optional receipt OCR flow

## Backend deploy

1. Create a Python virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Bootstrap CDK once per AWS environment:

```bash
cdk bootstrap
```

3. Deploy the backend. Replace the origin with your real Vercel production URL:

```bash
cdk deploy --context frontend_origin=https://your-app.vercel.app
```

4. Copy the `ApiUrl` output from the deploy result.

## Frontend deploy on Vercel

1. Import this repo into Vercel.
2. Set the environment variable:

```bash
GROCERY_API_BASE_URL=https://your-api-id.execute-api.region.amazonaws.com
```

3. Deploy.

The frontend calls `/api/config` on Vercel, which returns that backend URL at runtime.

## Local development

You can open the static frontend locally with a simple server:

```bash
python3 -m http.server 4173
```

Then visit `http://localhost:4173`.

For local frontend testing against the deployed backend, create a Vercel project env with `GROCERY_API_BASE_URL`, or temporarily edit [api/config.js](/Users/romanomoses/Documents/romano_github_repos/grocery_app/api/config.js) for local experimentation.

## Backend API routes

- `GET /summary`
- `GET /entries`
- `POST /entries`
- `POST /entries/bulk`
- `POST /receipts/text`
- `POST /upload-url`
- `POST /receipts/scan`

## Notes

- The current backend uses a single demo user partition. That keeps the MVP simple and cheap.
- If you want multi-user support next, the natural next step is adding Clerk, Supabase Auth, or Cognito and switching the partition key from a demo user to a real user id.
- Textract can add noticeable cost if you scan lots of images, so keeping text paste import as the default is the cheapest path.
