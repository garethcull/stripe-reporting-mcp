# Stripe Reporting MCP Server

A Model Context Protocol (MCP) server that exposes Stripe revenue and monetization reporting as tools consumable by MCP clients such as OpenAI Responses API, Cursor, or the prototypr.ai MCP Client.

This MCP Server was built as a Flask application and is deployable to Google Cloud Run or your own infrastructure.

It is designed to help agents and applications answer practical business questions such as:

- How much gross and net revenue did we generate over time?
- What were our Stripe fees and refund rates?
- Who are our top customers by spend?
- Which products generated the most revenue?
- What is our monthly recurring revenue trend?

---

# MCP Features

This Stripe Reporting MCP Server currently exposes six MCP tools:

### get_revenue_by_date
Get revenue trended over time at a specified granularity (`day`, `week`, or `month`).

Returns:
- gross revenue
- refunded amount
- Stripe fees
- net revenue
- order count
- unique customers
- ATV
- refunded order count
- disputed order count

Net revenue is calculated as:

`gross revenue - refunds - Stripe fees`

### get_revenue_summary
Get a high-level revenue snapshot for a given period.

Returns:
- gross revenue
- total refunded
- Stripe fees
- net revenue
- total orders
- unique customers
- refunded orders
- ATV
- gross AOV
- net AOV
- refund rate
- Stripe fee rate
- disputed orders

### get_top_customers_by_spend
Get the top customers ranked by total spend.

Returns:
- customer ID
- email
- name
- gross spend
- Stripe fees
- net spend
- total refunded
- order count
- ATV

### get_refunds_summary
Get a refund breakdown for a given period.

Returns:
- total refund amount
- refund count
- average refund
- refund rate
- gross revenue for comparison

### get_top_products_by_revenue
Get the top products ranked by total revenue.

This tool attempts to reconcile revenue from:
- invoice line items
- checkout session line items
- direct charges
- fallback unattributed charges

Returns:
- product ID
- product name
- total revenue
- units sold
- transaction count
- revenue sources
- percent of total revenue

### get_mrr_trend
Get Monthly Recurring Revenue (MRR) trended by month.

This tool only includes subscription invoices tied to truly succeeded charges.

Returns:
- month
- MRR
- subscription invoice count
- unique subscription count

---

# How it Works

This server connects to Stripe using your Stripe secret key and exposes reporting tools through MCP JSON-RPC methods.

Natural language requests are routed to the appropriate Stripe reporting tool, which then interacts with Stripe objects such as:

- Charges
- Refunds
- PaymentIntents
- Invoices
- Checkout Sessions
- Products
- Balance Transactions

Response data is then fed back to the requesting user or agent as a formatted string.

A key design choice in this server is that reporting is grounded primarily in **succeeded charges** and their associated Stripe balance transactions so that:
- gross revenue reflects real captured payments
- Stripe fees are included when available
- net revenue is more realistic
- refunds and disputes are surfaced explicitly

---

# MCP Architecture

This MCP server contains two files:

1. `app.py` - main Python file which authenticates and delegates requests to `mcp_helper.py`
2. `mcp_helper.py` - helper functions for MCP routing, Stripe data extraction, reconciliation, and reporting logic

### app.py
- Flask app with `POST /mcp`
- Handles JSON-RPC notifications by returning `204 No Content`
- Enforces Bearer token authentication
- Delegates MCP logic to `mcp_helper.py`

### mcp_helper.py
- `handle_request` routes `initialize`, `tools/list`, and `tools/call`
- `handle_tool_call` parses arguments, dispatches tool calls, and returns MCP-shaped responses
- Stripe helper functions fetch and normalize charges, refunds, invoices, and payment intents
- Reporting functions aggregate results into tables or JSON-friendly output

---

# Endpoints and Protocol

**JSON-RPC MCP (preferred by this server)**

<pre>
POST /mcp
Content-Type: application/json
Auth: Authorization: Bearer MCP_TOKEN
</pre>

### Methods
- `initialize` → returns protocolVersion, serverInfo, capabilities
- `tools/list` → returns tools with `inputSchema`
- `tools/call` → executes a tool and returns result with content array
- `notifications/initialized` → must NOT return a JSON-RPC body; respond `204`

---

# Environment Variables

This MCP server requires the following environment variables:

| Variable | Description |
|---|---|
| `MCP_TOKEN` | Shared secret used in the Authorization header |
| `STRIPE_KEY` | Your Stripe secret API key |

Example:

<pre><code class="language-bash">
export MCP_TOKEN="your-shared-token"
export STRIPE_KEY="sk_live_or_test_key_here"
</code></pre>

---

# Stripe Permissions

Your Stripe API key needs permission to read the resources used by this server, including:

- Charges
- Refunds
- Invoices
- PaymentIntents
- Checkout Sessions
- Products
- Balance Transactions

In most Stripe setups, a standard secret key with read access to these resources is sufficient.

---

# Local Setup

### Python environment

I typically use Anaconda Navigator to create and manage Python environments.

Open Anaconda Navigator, create a new environment using Python 3.11+, then open the terminal for that environment.

Navigate to the folder where you cloned this repo and install the requirements.

<pre><code class="language-bash">
pip install -r requirements.txt
</code></pre>

### Environment variables

Set the environment variables locally before running the app.

<pre><code class="language-bash">
export MCP_TOKEN="your-shared-token"
export STRIPE_KEY="your-stripe-secret-key"
</code></pre>

### Run locally

With your environment loaded, launch the Flask app locally:

<pre><code class="language-bash">
flask run --debugger -h localhost -p 3000
</code></pre>

---

# Quick Test of the MCP Server

I use a small Python helper to test that a given tool is working correctly.

This example calls `get_revenue_summary`.

<pre><code class="language-python">
import os
import requests

def call_tool(base_url):
    token = os.environ.get("MCP_TOKEN")
    url = f"{base_url}/mcp"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "get_revenue_summary",
            "arguments": {
                "start_date": "2026-01-01",
                "end_date": "2026-03-31",
                "currency_filter": "USD",
                "output_format": "json"
            }
        },
        "id": 1
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)

    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, resp.text
</code></pre>

You can adapt the tool name and arguments to test any of the available reporting tools.

---

# Available Tool Inputs

## Common Inputs

Most tools support:

| Input | Type | Description |
|---|---|---|
| `start_date` | string | Start date in `YYYY-MM-DD` format |
| `end_date` | string | End date in `YYYY-MM-DD` format |
| `currency_filter` | string | Optional currency code such as `USD` or `CAD` |
| `output_format` | string | `json` or `table` |

## Tool-Specific Inputs

### get_revenue_by_date
- `granularity`: `day`, `week`, or `month`

### get_top_customers_by_spend
- `limit`: integer, defaults to 10

### get_top_products_by_revenue
- `limit`: integer, defaults to 10

---

# OpenAI Responses API Tool Configuration

This MCP server was initially designed to work with OpenAI Responses API as part of the prototypr.ai MCP Client.

For more details about OpenAI's Responses API and MCP:
https://cookbook.openai.com/examples/mcp/mcp_tool_guide

Configure an MCP tool in your Responses API request and point `server_url` to your `/mcp` endpoint.

<pre><code class="language-python">
tools = [
  {
    "type": "mcp",
    "server_label": "stripe-reporting-mcp",
    "server_url": "https://<your-cloud-run-host>/mcp",
    "headers": { "Authorization": "Bearer <your-mcp-token>" },
    "require_approval": "never"
  }
]
</code></pre>

---

# How to Connect this Server to Your MCP Client

If you want to connect this server to the prototypr.ai MCP client or another MCP-compatible client, use a config similar to the following:

<pre><code class="language-json">
{
  "stripe-reporting-mcp": {
    "description": "An MCP server that exposes Stripe revenue and reporting tools",
    "displayName": "Stripe Reporting MCP",
    "headers": {
      "Authorization": "Bearer <INSERT MCP_TOKEN>"
    },
    "icon": "<ADD ICON URL>",
    "transport": "stdio",
    "url": "https://<your-cloud-run-host>/mcp"
  }
}
</code></pre>

---

# Reporting Logic Notes

A few implementation details are worth knowing:

## Revenue Source of Truth
This server primarily builds reporting off succeeded charges returned by Stripe.

A charge is included only if it is:
- `status == succeeded`
- paid
- captured

This helps prevent false positives from incomplete or non-finalized payment records.

## Stripe Fees
Where available, Stripe fees are pulled from expanded `balance_transaction` objects.

## Net Revenue
Net revenue is calculated as:

`gross revenue - refunded amount - Stripe fees`

## Product Attribution
The `get_top_products_by_revenue` tool tries multiple attribution paths:

1. Invoice line items
2. Checkout session line items
3. PaymentIntent metadata
4. Charge description fallback
5. Final unattributed fallback bucket

This makes it more robust across mixed Stripe implementations, especially if your account uses both subscriptions and one-time payments.

## MRR Logic
MRR is based on paid subscription invoices tied to valid succeeded charges. It is not a forward-looking subscription-state MRR model. It is a recognized recurring revenue trend based on actual invoiced payments.

---

# Known Limitations

A few things to keep in mind:

- Product attribution quality depends on how consistently products, prices, metadata, checkout sessions, and invoice line items are configured in your Stripe account.
- Mixed-currency reporting is supported, but combining currencies into a single total may not be meaningful unless filtered.
- MRR here reflects paid subscription invoice revenue, not contracted MRR or subscription schedule projections.
- Refund reporting is based on Stripe refund objects with `status == succeeded`.
- In very large Stripe accounts, some reports may take longer due to pagination and reconciliation logic.

---

# Security Considerations

- Always require `Authorization: Bearer MCP_TOKEN` on `/mcp`
- Never commit your `STRIPE_KEY` to source control
- Use restricted infrastructure and secrets management in production
- Keep tool outputs to a reasonable size if connecting to LLM clients
- Consider using separate test and production Stripe keys for safer development

---

# Deploying to Google Cloud Run

I initially built MCP servers like this to run on Google Cloud Run.

Google Cloud Run is serverless, scales well, and is straightforward to deploy.

You will need:
- a Google Cloud project with billing enabled
- a deployable Flask app
- your environment variables configured in Cloud Run

At minimum, make sure these environment variables are added to your Cloud Run service:
- `MCP_TOKEN`
- `STRIPE_KEY`

Helpful resource:
- Deploy a Python service to Cloud Run: https://docs.cloud.google.com/run/docs/quickstarts/build-and-deploy/deploy-python-service

---

# Suggested Use Cases

This MCP server is useful for:

- AI agents that need access to Stripe revenue context
- Internal analytics assistants
- Growth reporting workflows
- Weekly business summaries
- Productized reporting features inside SaaS apps
- Founders and growth teams who want conversational access to Stripe data

---

# License

MIT (or your preferred license).

---

# Contributions & Support

Feedback, issues, and PRs are welcome.

Due to bandwidth constraints, I can't offer timelines for free updates to this codebase.

If you need help customizing this MCP server or integrating it into your own reporting stack, I am available for paid consulting and freelance projects.

Feel free to connect with me on LinkedIn:
https://www.linkedin.com/in/garethcull/

Thanks for checking out this Stripe Reporting MCP Server.

I hope it helps you build more useful revenue reporting workflows and AI-powered business tools.
