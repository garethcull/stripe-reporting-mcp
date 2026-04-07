# Install Modules
import pandas as pd
import stripe
import os
import re
from datetime import datetime, timezone
from collections import defaultdict
import traceback


# =============================================================================
# Variables
# =============================================================================

stripe.api_key = os.getenv('STRIPE_KEY')

# =============================================================================
# Helper Functions
# =============================================================================

def convert_timestamp(stripe_ts: int) -> datetime:
    """Convert a Stripe Unix timestamp to a Python datetime (UTC)."""
    return datetime.fromtimestamp(stripe_ts, tz=timezone.utc)


def date_to_stripe_ts(date_str: str) -> int:
    """
    Convert a date string (YYYY-MM-DD) to a Unix timestamp for Stripe filtering.
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def build_created_filter(start_date=None, end_date=None) -> dict:
    """
    Build Stripe's 'created' filter dict from optional date strings.
    Returns an empty dict if neither date is provided.
    """
    created = {}
    if start_date:
        created["gte"] = date_to_stripe_ts(start_date)
    if end_date:
        created["lte"] = date_to_stripe_ts(end_date)
    return created if created else None


def fetch_all_charges(start_date=None, end_date=None, status="succeeded") -> list:
    """
    Fetch all charges from Stripe using auto-pagination.
    Filters by status and optional date range.
    """
    params = {"limit": 100}
    if status:
        params["status"] = status
    created = build_created_filter(start_date, end_date)
    if created:
        params["created"] = created

    charges = []
    for charge in stripe.Charge.list(**params).auto_paging_iter():
        
        charges.append(charge)
    return charges


def fetch_all_payment_intents(start_date=None, end_date=None) -> list:
    """
    Fetch all succeeded PaymentIntents from Stripe using auto-pagination.
    """
    params = {"limit": 100}
    created = build_created_filter(start_date, end_date)
    if created:
        params["created"] = created

    intents = []
    for pi in stripe.PaymentIntent.list(**params).auto_paging_iter():
        if pi.status == "succeeded":
            intents.append(pi)
    return intents


def fetch_all_refunds(start_date=None, end_date=None) -> list:
    """
    Fetch all refunds from Stripe using auto-pagination.
    """
    params = {"limit": 100}
    created = build_created_filter(start_date, end_date)
    if created:
        params["created"] = created

    refunds = []
    for refund in stripe.Refund.list(**params).auto_paging_iter():
        refunds.append(refund)
    return refunds


def fetch_all_invoices(start_date=None, end_date=None, status="paid") -> list:
    """
    Fetch all invoices from Stripe using auto-pagination.
    """
    params = {"limit": 100}
    if status:
        params["status"] = status
    created = build_created_filter(start_date, end_date)
    if created:
        params["created"] = created

    invoices = []
    for inv in stripe.Invoice.list(**params).auto_paging_iter():
        invoices.append(inv)
    return invoices


# =============================================================================
# MCP Protocol Request Routing
# =============================================================================

def handle_request(method, params):
    """
    Main request router for MCP (Model Context Protocol) JSON-RPC methods.
    Supported:
      - initialize
      - tools/list
      - tools/call
    Notifications (notifications/*) are handled in app.py (204 No Content).
    """
    if method == "initialize":
        return handle_initialize()
    elif method == "tools/list":
        return handle_tools_list()
    elif method == "tools/call":
        return handle_tool_call(params)
    else:
        # Let app.py wrap unknown methods into a proper JSON-RPC error
        raise ValueError(f"Method not found: {method}")


# =============================================================================
# MCP Protocol Handlers
# =============================================================================

def handle_initialize():
    """
    JSON-RPC initialize response.
    Keep protocolVersion consistent with your current implementation.
    """
    return {
        "protocolVersion": "2024-11-05",
        "serverInfo": {
            "name": "stripe-mcp",
            "version": "0.1.0",
        },
        "capabilities": {
            "tools": {}
        },
    }

def handle_tools_list():
    """
    JSON-RPC tools/list result.
    IMPORTANT: For JSON-RPC MCP, schema field is camelCase: inputSchema
    """
    return {
        "tools": [                        
            {
                "name": "get_revenue_by_date",
                "description": (
                    "Get revenue trended over time at a specified granularity (day, week, or month). "
                    "Returns gross revenue, refunded amount, Stripe fees, net revenue, order count, "
                    "unique customers, average transaction value (ATV), and refund/dispute counts per period. "
                    "Net revenue = gross - refunds - Stripe fees. "
                    "Can be filtered by currency."
                ),
                "annotations": {"read_only": True},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_date": {
                            "type": "string",
                            "description": "Start date in YYYY-MM-DD format.",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date in YYYY-MM-DD format.",
                        },
                        "granularity": {
                            "type": "string",
                            "enum": ["day", "week", "month"],
                            "description": "Time granularity for the trend. Defaults to 'day'.",
                        },
                        "currency_filter": {
                            "type": "string",
                            "description": "Filter by currency code (e.g. 'CAD', 'USD'). If omitted, includes all currencies.",
                        },
                        "output_format": {
                            "type": "string",
                            "enum": ["json", "table"],
                            "description": "Controls output format. If LLM is requesting, please default to table."
                        }
                    },
                    "required": [
                        "start_date",
                        "end_date"                        
                    ],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_revenue_summary",
                "description": (
                    "Get a high-level revenue snapshot for a given period. "
                    "Returns gross revenue, total refunded, Stripe fees, net revenue, "
                    "total orders, unique customers, ATV (average transaction value), "
                    "gross and net AOV, refund rate, Stripe fee rate, and disputed order count. "
                    "Can be filtered by currency."
                ),
                "annotations": {"read_only": True},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_date": {
                            "type": "string",
                            "description": "Start date in YYYY-MM-DD format.",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date in YYYY-MM-DD format.",
                        },
                        "currency_filter": {
                            "type": "string",
                            "description": "Filter by currency code (e.g. 'CAD', 'USD'). If omitted, includes all currencies.",
                        },
                        "output_format": {
                            "type": "string",
                            "enum": ["json", "table"],
                            "description": "Controls output format. If LLM is requesting, please default to table."
                        }
                    },
                    "required": [
                        "start_date",
                        "end_date"                        
                    ],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_top_customers_by_spend",
                "description": (
                    "Get the top customers ranked by total spend. "
                    "Returns customer ID, email, name, gross spend, Stripe fees, "
                    "net spend, total refunded, order count, and ATV per customer. "
                    "Can be filtered by currency."
                ),
                "annotations": {"read_only": True},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of top customers to return. Defaults to 10.",
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date in YYYY-MM-DD format.",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date in YYYY-MM-DD format.",
                        },
                        "currency_filter": {
                            "type": "string",
                            "description": "Filter by currency code (e.g. 'CAD', 'USD'). If omitted, includes all currencies.",
                        },
                        "output_format": {
                            "type": "string",
                            "enum": ["json", "table"],
                            "description": "Controls output format. If LLM is requesting, please default to table."
                        }
                    },
                    "required": [
                        "start_date",
                        "end_date"                        
                    ],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_refunds_summary",
                "description": (
                    "Get a refund breakdown for a given period. "
                    "Returns total refund amount, refund count, average refund, "
                    "refund rate as percentage of gross revenue, and gross revenue. "
                    "Can be filtered by currency."
                ),
                "annotations": {"read_only": True},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_date": {
                            "type": "string",
                            "description": "Start date in YYYY-MM-DD format.",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date in YYYY-MM-DD format.",
                        },
                        "currency_filter": {
                            "type": "string",
                            "description": "Filter by currency code (e.g. 'CAD', 'USD'). If omitted, includes all currencies.",
                        },
                        "output_format": {
                            "type": "string",
                            "enum": ["json", "table"],
                            "description": "Controls output format. If LLM is requesting, please default to table."
                        }
                    },
                    "required": [
                        "start_date",
                        "end_date"                        
                    ],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_top_products_by_revenue",
                "description": (
                    "Get the top products ranked by total revenue. "
                    "Captures both subscription (invoice-based) and one-time "
                    "(checkout session / direct charge) products. "
                    "Returns product ID, product name, total revenue, units sold, "
                    "transaction count, revenue sources, and percentage of total revenue. "
                    "Can be filtered by currency."
                ),
                "annotations": {"read_only": True},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of top products to return. Defaults to 10.",
                        },
                        "start_date": {
                            "type": "string",
                            "description": "Start date in YYYY-MM-DD format.",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date in YYYY-MM-DD format.",
                        },
                        "currency_filter": {
                            "type": "string",
                            "description": "Filter by currency code (e.g. 'CAD', 'USD'). If omitted, includes all currencies.",
                        },
                        "output_format": {
                            "type": "string",
                            "enum": ["json", "table"],
                            "description": "Controls output format. If LLM is requesting, please default to table."
                        }
                    },
                    "required": [
                        "start_date",
                        "end_date"                        
                    ],
                    "additionalProperties": False,
                },
            },
            {
                "name": "get_mrr_trend",
                "description": (
                    "Get Monthly Recurring Revenue (MRR) trended by month. "
                    "Only includes subscription invoices tied to truly succeeded charges. "
                    "Returns month, MRR amount, subscription invoice count, "
                    "and unique subscription count per month. "
                    "Can be filtered by currency."
                ),
                "annotations": {"read_only": True},
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "start_date": {
                            "type": "string",
                            "description": "Start date in YYYY-MM-DD format.",
                        },
                        "end_date": {
                            "type": "string",
                            "description": "End date in YYYY-MM-DD format.",
                        },
                        "currency_filter": {
                            "type": "string",
                            "description": "Filter by currency code (e.g. 'CAD', 'USD'). If omitted, includes all currencies.",
                        },
                        "output_format": {
                            "type": "string",
                            "enum": ["json", "table"],
                            "description": "Controls output format. If LLM is requesting, please default to table."
                        }
                    },
                    "required": [
                        "start_date",
                        "end_date"                        
                    ],
                    "additionalProperties": False,
                },
            }
        ]
    }


def handle_tool_call(params):
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except Exception:
            return {
                "isError": True,
                "content": [{"type": "text", "text": "Invalid arguments: expected object or JSON string."}]
            }

    if tool_name == "get_revenue_by_date":
        try:
            df = get_revenue_by_date(
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
                granularity=arguments.get("granularity", "day"),
                currency_filter=arguments.get("currency_filter")
            )

            output_format= arguments.get("output_format", "table")

            if output_format == 'json':

                result = df.to_dict(orient='records')

            else:

                result = df
            
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": f"Error fetching revenue by date: {str(e)}"}]}

    elif tool_name == "get_revenue_summary":
        try:
            summary = get_revenue_summary(
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
                currency_filter=arguments.get("currency_filter")
            )

            # Determine the output format being requested
            output_format= arguments.get("output_format", "table")

            if output_format == 'json':

                result = summary.to_dict(orient='records')

            else:

                result = summary
            
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            error_details = traceback.format_exc()
            return {"isError": True, "content": [{"type": "text", "text": f"Error fetching revenue summary: {str(error_details)}"}]}

    elif tool_name == "get_top_customers_by_spend":
        try:
            df = get_top_customers_by_spend(
                limit=arguments.get("limit", 10),
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
                currency_filter=arguments.get("currency_filter")
            )

            # Determine the output format being requested
            output_format= arguments.get("output_format", "table")

            if output_format == 'json':

                result = df.to_dict(orient='records')

            else:

                result = df
            
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": f"Error fetching top customers: {str(e)}"}]}

    elif tool_name == "get_refunds_summary":
        try:
            summary = get_refunds_summary(
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
                currency_filter=arguments.get("currency_filter")
            )

            # Determine the output format being requested
            output_format= arguments.get("output_format", "table")

            if output_format == 'json':

                result = summary.to_dict(orient='records')

            else:

                result = summary


            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": f"Error fetching refunds summary: {str(e)}"}]}

    elif tool_name == "get_top_products_by_revenue":
        try:
            df = get_top_products_by_revenue(
                limit=arguments.get("limit", 10),
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
                currency_filter=arguments.get("currency_filter")
            )
            
            # Determine the output format being requested
            output_format= arguments.get("output_format", "table")

            if output_format == 'json':

                result = df.to_dict(orient='records')

            else:

                result = df            
            
            return {"content": [{"type": "text", "text": str(result)}]}
        except Exception as e:
            error_details = traceback.format_exc()
            return {"isError": True, "content": [{"type": "text", "text": f"Error fetching top products: {str(error_details)}"}]}

    elif tool_name == "get_mrr_trend":
        try:
            df = get_mrr_trend(
                start_date=arguments.get("start_date"),
                end_date=arguments.get("end_date"),
                currency_filter=arguments.get("currency_filter")
            )       

            # Determine the output format being requested
            output_format= arguments.get("output_format", "table")

            if output_format == 'json':

                result = df.to_dict(orient='records')

            else:

                result = df  

            return {"content": [{"type": "text", "text": str(df)}]}
        except Exception as e:
            return {"isError": True, "content": [{"type": "text", "text": f"Error fetching MRR trend: {str(e)}"}]}

    else:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Tool not found: {tool_name}"}]
        }



# =============================================================================
# Stripe Tools
# =============================================================================


# =============================================================================
# CORE: Succeeded Charges → DataFrame
# =============================================================================

def get_succeeded_charges(start_date=None, end_date=None) -> pd.DataFrame:
    """
    Pulls all succeeded charges from Stripe for a given date range.
    Includes Stripe fees from BalanceTransaction objects.
    Compatible with Stripe SDK v14+.

    Net amount = gross amount - refunds - stripe fees
    """
    params = {"limit": 100, "status": "succeeded", "expand[]": "data.balance_transaction"}

    created = {}
    if start_date:
        dt_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        created["gte"] = int(dt_start.timestamp())
    if end_date:
        dt_end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        created["lte"] = int(dt_end.timestamp()) + 86399
    if created:
        params["created"] = created

    records = []
    skipped_count = 0

    for charge in stripe.Charge.list(**params).auto_paging_iter():
        if charge["status"] != "succeeded" or not charge["paid"] or not charge["captured"]:
            skipped_count += 1
            continue

        dt = datetime.fromtimestamp(charge["created"], tz=timezone.utc)

        amount = charge["amount"] or 0
        amount_refunded = charge["amount_refunded"] or 0

        # Extract Stripe fee from the expanded balance_transaction
        stripe_fee = 0
        bt = charge["balance_transaction"]
        if bt:
            try:
                stripe_fee = bt["fee"] or 0
            except (KeyError, TypeError):
                stripe_fee = 0

        net = amount - amount_refunded - stripe_fee

        billing = charge["billing_details"]

        records.append({
            "charge_id": charge["id"],
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M:%S"),
            "year_month": dt.strftime("%Y-%m"),
            "year_week": dt.strftime("%Y-W%V"),
            "currency": (charge["currency"] or "unknown").upper(),
            "amount": round(amount / 100, 2),
            "amount_refunded": round(amount_refunded / 100, 2),
            "stripe_fee": round(stripe_fee / 100, 2),
            "net_amount": round(net / 100, 2),
            "refunded": charge["refunded"] or False,
            "disputed": charge["disputed"] or False,
            "customer_id": charge.get("customer"),
            "customer_email": billing["email"] if billing else None,
            "customer_name": billing["name"] if billing else None,
            "description": charge.get("description"),
            "invoice_id": charge.get("invoice"),
            "payment_intent_id": charge.get("payment_intent"),
            "livemode": charge["livemode"]
        })

    if skipped_count > 0:
        print(f"⚠️  Filtered out {skipped_count} non-succeeded charges that Stripe returned incorrectly.")

    df = pd.DataFrame(records)

    if df.empty:
        print("⚠️  No succeeded charges found for this period.")
        return df

    df = df.sort_values("date").reset_index(drop=True)
    return df



# =============================================================================
# CORE: Refunds → DataFrame
# =============================================================================

def get_refunds(start_date=None, end_date=None) -> pd.DataFrame:
    """
    Pulls all succeeded refunds from Stripe for a given date range.
    """
    params = {"limit": 100}

    created = {}
    if start_date:
        dt_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        created["gte"] = int(dt_start.timestamp())
    if end_date:
        dt_end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        created["lte"] = int(dt_end.timestamp()) + 86399
    if created:
        params["created"] = created

    records = []
    for refund in stripe.Refund.list(**params).auto_paging_iter():
        if refund["status"] != "succeeded":
            continue

        dt = datetime.fromtimestamp(refund["created"], tz=timezone.utc)

        records.append({
            "refund_id": refund["id"],
            "charge_id": refund.get("charge"),
            "date": dt.strftime("%Y-%m-%d"),
            "currency": (refund["currency"] or "unknown").upper(),
            "amount": round((refund["amount"] or 0) / 100, 2),
            "status": refund["status"],
            "reason": refund.get("reason")
        })

    df = pd.DataFrame(records)

    if df.empty:
        print("⚠️  No refunds found for this period.")
        return df

    df = df.sort_values("date").reset_index(drop=True)
    return df


# =============================================================================
# Revenue by Date
# =============================================================================

def get_revenue_by_date(
    start_date=None,
    end_date=None,
    granularity="day",
    currency_filter=None
) -> pd.DataFrame:
    """
    Revenue trended over time.
    Net revenue = gross - refunds - stripe fees
    """
    df = get_succeeded_charges(start_date=start_date, end_date=end_date)

    if df.empty:
        return pd.DataFrame()

    if currency_filter:
        df = df[df["currency"] == currency_filter.upper()]
        if df.empty:
            print(f"⚠️  No charges found for currency: {currency_filter.upper()}")
            return pd.DataFrame()

    granularity_map = {
        "day": "date",
        "week": "year_week",
        "month": "year_month"
    }
    if granularity not in granularity_map:
        raise ValueError(f"Invalid granularity: {granularity}. Use 'day', 'week', or 'month'.")

    group_col = granularity_map[granularity]

    result = df.groupby(group_col).agg(
        gross_revenue=("amount", "sum"),
        refunded_amount=("amount_refunded", "sum"),
        stripe_fees=("stripe_fee", "sum"),
        net_revenue=("net_amount", "sum"),
        order_count=("charge_id", "count"),
        unique_customers=("customer_id", "nunique"),
        refunded_order_count=("refunded", "sum"),
        disputed_count=("disputed", "sum")
    ).reset_index()

    result = result.rename(columns={group_col: "period"})
    result = result.sort_values("period").reset_index(drop=True)
    result["gross_revenue"] = result["gross_revenue"].round(2)
    result["refunded_amount"] = result["refunded_amount"].round(2)
    result["stripe_fees"] = result["stripe_fees"].round(2)
    result["net_revenue"] = result["net_revenue"].round(2)
    result["atv"] = (result["gross_revenue"] / result["order_count"]).round(2)
    result["refunded_order_count"] = result["refunded_order_count"].astype(int)
    result["disputed_count"] = result["disputed_count"].astype(int)

    return result


# =============================================================================
# Revenue Summary
# =============================================================================

def get_revenue_summary(start_date=None, end_date=None, currency_filter=None) -> dict:
    """
    High-level revenue snapshot including Stripe fees, unique customers, and ATV.
    """
    df = get_succeeded_charges(start_date=start_date, end_date=end_date)

    if df.empty:
        return {}

    if currency_filter:
        df = df[df["currency"] == currency_filter.upper()]

    total_gross = df["amount"].sum()
    total_refunded = df["amount_refunded"].sum()
    total_stripe_fees = df["stripe_fee"].sum()
    net_revenue = total_gross - total_refunded - total_stripe_fees
    total_orders = len(df)
    unique_customers = df["customer_id"].nunique()
    disputed_count = int(df["disputed"].sum())
    refunded_order_count = int(df["refunded"].sum())

    gross_aov = round(total_gross / total_orders, 2) if total_orders > 0 else 0.0
    net_aov = round(net_revenue / total_orders, 2) if total_orders > 0 else 0.0
    atv = round(total_gross / total_orders, 2) if total_orders > 0 else 0.0
    refund_rate = round((total_refunded / total_gross) * 100, 2) if total_gross > 0 else 0.0
    fee_rate = round((total_stripe_fees / total_gross) * 100, 2) if total_gross > 0 else 0.0

    currencies = df["currency"].unique().tolist()

    return {
        "gross_revenue": round(total_gross, 2),
        "total_refunded": round(total_refunded, 2),
        "total_stripe_fees": round(total_stripe_fees, 2),
        "net_revenue": round(net_revenue, 2),
        "total_orders": total_orders,
        "unique_customers": unique_customers,
        "refunded_orders": refunded_order_count,
        "atv": atv,
        "gross_aov": gross_aov,
        "net_aov": net_aov,
        "refund_rate": refund_rate,
        "stripe_fee_rate": fee_rate,
        "disputed_orders": disputed_count,
        "currencies": currencies,
        "currency_filter": currency_filter.upper() if currency_filter else "ALL",
        "period_start": start_date or "all time",
        "period_end": end_date or "present"
    }


# =============================================================================
# Top Customers by Spend
# =============================================================================

def get_top_customers_by_spend(
    limit=10,
    start_date=None,
    end_date=None,
    currency_filter=None
) -> pd.DataFrame:
    """
    Top customers by total spend.
    """
    df = get_succeeded_charges(start_date=start_date, end_date=end_date)

    if df.empty:
        return pd.DataFrame()

    if currency_filter:
        df = df[df["currency"] == currency_filter.upper()]

    result = df.groupby(["customer_id", "customer_email", "customer_name"]).agg(
        gross_spend=("amount", "sum"),
        stripe_fees=("stripe_fee", "sum"),
        net_spend=("net_amount", "sum"),
        total_refunded=("amount_refunded", "sum"),
        order_count=("charge_id", "count")
    ).reset_index()

    result = result.sort_values("net_spend", ascending=False).reset_index(drop=True)
    result["gross_spend"] = result["gross_spend"].round(2)
    result["stripe_fees"] = result["stripe_fees"].round(2)
    result["net_spend"] = result["net_spend"].round(2)
    result["total_refunded"] = result["total_refunded"].round(2)
    result["atv"] = (result["gross_spend"] / result["order_count"]).round(2)
    result = result.head(limit)

    return result


# =============================================================================
# Refunds Summary
# =============================================================================

def get_refunds_summary(start_date=None, end_date=None, currency_filter=None) -> dict:
    """
    Refund breakdown.
    """
    charges_df = get_succeeded_charges(start_date=start_date, end_date=end_date)
    refunds_df = get_refunds(start_date=start_date, end_date=end_date)

    if currency_filter:
        if not charges_df.empty:
            charges_df = charges_df[charges_df["currency"] == currency_filter.upper()]
        if not refunds_df.empty:
            refunds_df = refunds_df[refunds_df["currency"] == currency_filter.upper()]

    gross_revenue = charges_df["amount"].sum() if not charges_df.empty else 0
    total_refund_amount = refunds_df["amount"].sum() if not refunds_df.empty else 0
    refund_count = len(refunds_df)
    avg_refund = round(total_refund_amount / refund_count, 2) if refund_count > 0 else 0.0
    refund_rate = round((total_refund_amount / gross_revenue) * 100, 2) if gross_revenue > 0 else 0.0

    return {
        "total_refund_amount": round(total_refund_amount, 2),
        "refund_count": refund_count,
        "average_refund": avg_refund,
        "refund_rate": refund_rate,
        "gross_revenue": round(gross_revenue, 2),
        "period_start": start_date or "all time",
        "period_end": end_date or "present"
    }


# =============================================================================
# Top Products by Revenue
# =============================================================================




def _get_invoice_payment_intent(invoice):
    """
    Extract payment_intent ID from a v14 invoice object.
    In v14, it's nested under payments.data[].payment.payment_intent
    Must expand=["payments"] when retrieving the invoice.
    """
    payments = invoice.get("payments")
    if payments and payments["data"]:
        for p in payments["data"]:
            payment_obj = p.get("payment")
            if payment_obj and isinstance(payment_obj, dict):
                pi = payment_obj.get("payment_intent")
                if pi:
                    return pi
            elif payment_obj:
                pi = payment_obj.get("payment_intent")
                if pi:
                    return pi
    # Fallback: regex search the string representation
    pi_matches = re.findall(r'pi_[A-Za-z0-9]+', str(invoice))
    return pi_matches[0] if pi_matches else None


def _extract_from_string(obj, prefix):
    """
    Extract an ID from a Stripe object's string representation.
    e.g. prefix='prod_' returns 'prod_SGJovtBcXDDyb8'
    """
    matches = re.findall(rf'{prefix}[A-Za-z0-9]+', str(obj))
    return matches[0] if matches else None


def get_top_products_by_revenue(
    limit=10,
    start_date=None,
    end_date=None,
    currency_filter=None
) -> pd.DataFrame:
    """
    Top products by revenue. Captures BOTH subscription (invoice-based)
    and one-time (checkout session / direct charge) products.
    Compatible with Stripe SDK v14.
    """
    charges_df = get_succeeded_charges(start_date=start_date, end_date=end_date)

    if charges_df.empty:
        return pd.DataFrame()

    if currency_filter:
        charges_df = charges_df[charges_df["currency"] == currency_filter.upper()]
        if charges_df.empty:
            print(f"⚠️  No charges found for currency: {currency_filter.upper()}")
            return pd.DataFrame()

    product_cache = {}
    records = []
    attributed_charge_ids = set()

    # Build lookup: payment_intent_id -> charge_id
    pi_to_charge = {}
    for _, row in charges_df.iterrows():
        if row["payment_intent_id"]:
            pi_to_charge[row["payment_intent_id"]] = row["charge_id"]

    valid_pi_ids = set(pi_to_charge.keys())

    print(f"📄 Scanning invoices... ({len(valid_pi_ids)} payment intents to match)")

    # -----------------------------------------------------------------
    # SOURCE 1: Invoice line items (subscriptions + invoice-based sales)
    # -----------------------------------------------------------------
    inv_params = {"limit": 100, "status": "paid", "expand[]": "data.payments"}

    created = {}
    if start_date:
        dt_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        created["gte"] = int(dt_start.timestamp())
    if end_date:
        dt_end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        created["lte"] = int(dt_end.timestamp()) + 86399
    if created:
        inv_params["created"] = created

    invoice_count = 0

    for invoice in stripe.Invoice.list(**inv_params).auto_paging_iter():
        # Extract payment_intent from the payments sub-object
        inv_pi = _get_invoice_payment_intent(invoice)

        # Match to a charge via payment_intent
        matched_charge_id = pi_to_charge.get(inv_pi) if inv_pi else None

        if not matched_charge_id:
            continue

        inv_dt = datetime.fromtimestamp(invoice["created"], tz=timezone.utc)
        inv_currency = (invoice["currency"] or "unknown").upper()

        if currency_filter and inv_currency != currency_filter.upper():
            continue

        invoice_count += 1
        attributed_charge_ids.add(matched_charge_id)

        for item in invoice["lines"].auto_paging_iter():
            product_id = None
            product_name = item.get("description") or "Unknown"

            # Try normal access first
            item_price = item.get("price")
            item_plan = item.get("plan")

            if item_price and item_price.get("product"):
                product_id = item_price["product"]
            elif item_plan and item_plan.get("product"):
                product_id = item_plan["product"]

            # Fallback: extract from string representation
            if not product_id:
                product_id = _extract_from_string(item, "prod_")

            if product_id and product_id not in product_cache:
                try:
                    prod = stripe.Product.retrieve(product_id)
                    product_cache[product_id] = prod["name"]
                except Exception:
                    product_cache[product_id] = product_id

            if product_id:
                product_name = product_cache.get(product_id, product_id)

            records.append({
                "charge_id": matched_charge_id,
                "date": inv_dt.strftime("%Y-%m-%d"),
                "currency": inv_currency,
                "product_id": product_id,
                "product_name": product_name,
                "amount": round((item["amount"] or 0) / 100, 2),
                "quantity": item.get("quantity") or 1,
                "source": "invoice"
            })

    print(f"   Processed {invoice_count} invoices")

    # -----------------------------------------------------------------
    # SOURCE 2: Non-invoice charges
    # -----------------------------------------------------------------
    non_invoice_charges = charges_df[~charges_df["charge_id"].isin(attributed_charge_ids)]

    print(f"\n🛒 Found {len(non_invoice_charges)} charges not covered by invoices (${non_invoice_charges['amount'].sum():,.2f} revenue)")

    if not non_invoice_charges.empty:
        session_found = 0
        from_charge = 0

        for _, row in non_invoice_charges.iterrows():
            pi_id = row["payment_intent_id"]
            charge_id = row["charge_id"]
            attributed = False

            if pi_id:
                try:
                    sessions = stripe.checkout.Session.list(payment_intent=pi_id, limit=1)

                    if sessions.data:
                        session = sessions.data[0]

                        try:
                            session_expanded = stripe.checkout.Session.retrieve(
                                session["id"],
                                expand=["line_items"]
                            )

                            line_items = session_expanded.get("line_items")

                            if line_items and line_items["data"]:
                                for item in line_items["data"]:
                                    product_id = None
                                    product_name = item.get("description") or "Unknown"

                                    item_price = item.get("price")
                                    if item_price and item_price.get("product"):
                                        product_id = item_price["product"]

                                    if not product_id:
                                        product_id = _extract_from_string(item, "prod_")

                                    if product_id and product_id not in product_cache:
                                        try:
                                            prod = stripe.Product.retrieve(product_id)
                                            product_cache[product_id] = prod["name"]
                                        except Exception:
                                            product_cache[product_id] = product_id

                                    if product_id:
                                        product_name = product_cache.get(product_id, product_id)

                                    records.append({
                                        "charge_id": charge_id,
                                        "date": row["date"],
                                        "currency": row["currency"],
                                        "product_id": product_id,
                                        "product_name": product_name,
                                        "amount": round((item.get("amount_total") or 0) / 100, 2),
                                        "quantity": item.get("quantity") or 1,
                                        "source": "checkout_session"
                                    })

                                attributed_charge_ids.add(charge_id)
                                session_found += 1
                                attributed = True

                        except Exception:
                            pass

                except Exception:
                    pass

            if not attributed:
                product_id = None
                product_name = row["description"] or "One-time Purchase"

                if pi_id:
                    try:
                        pi = stripe.PaymentIntent.retrieve(pi_id)
                        pi_metadata = pi.get("metadata") or {}
                        if pi_metadata:
                            product_id = pi_metadata.get("product_id")
                            if not product_id:
                                product_id = pi_metadata.get("product")
                            meta_name = pi_metadata.get("product_name")
                            if meta_name:
                                product_name = meta_name
                    except Exception:
                        pass

                if product_id and product_id not in product_cache:
                    try:
                        prod = stripe.Product.retrieve(product_id)
                        product_cache[product_id] = prod["name"]
                    except Exception:
                        product_cache[product_id] = product_id

                if product_id:
                    product_name = product_cache.get(product_id, product_id)

                records.append({
                    "charge_id": charge_id,
                    "date": row["date"],
                    "currency": row["currency"],
                    "product_id": product_id,
                    "product_name": product_name,
                    "amount": row["amount"],
                    "quantity": 1,
                    "source": "direct_charge"
                })

                attributed_charge_ids.add(charge_id)
                from_charge += 1

        print(f"   ✅ Checkout sessions found: {session_found}")
        print(f"   📦 From charge data:        {from_charge}")

    # -----------------------------------------------------------------
    # RECONCILIATION CHECK
    # -----------------------------------------------------------------
    unattributed = charges_df[~charges_df["charge_id"].isin(attributed_charge_ids)]
    if not unattributed.empty:
        print(f"\n⚠️  {len(unattributed)} charges still unattributed — adding as fallback")
        for _, row in unattributed.iterrows():
            records.append({
                "charge_id": row["charge_id"],
                "date": row["date"],
                "currency": row["currency"],
                "product_id": None,
                "product_name": row["description"] or "Unattributed",
                "amount": row["amount"],
                "quantity": 1,
                "source": "fallback"
            })

    # -----------------------------------------------------------------
    # Build DataFrame
    # -----------------------------------------------------------------
    df = pd.DataFrame(records)

    if df.empty:
        print("⚠️  No product line items found.")
        return pd.DataFrame()

    charges_total = charges_df["amount"].sum()
    records_total = df["amount"].sum()
    diff = round(charges_total - records_total, 2)

    print(f"\n📊 Revenue Reconciliation:")
    print(f"   Charges gross total:    ${charges_total:,.2f}")
    print(f"   Product records total:  ${records_total:,.2f}")
    print(f"   Difference:             ${diff:,.2f}")

    source_summary = df.groupby("source").agg(
        count=("charge_id", "count"),
        revenue=("amount", "sum")
    ).round(2)
    print(f"\n   Revenue by source:")
    for source, srow in source_summary.iterrows():
        print(f"     {source:<30} {int(srow['count']):>5} items  ${srow['revenue']:>12,.2f}")

    result = df.groupby(["product_id", "product_name"]).agg(
        total_revenue=("amount", "sum"),
        units_sold=("quantity", "sum"),
        transaction_count=("charge_id", "nunique"),
        sources=("source", lambda x: sorted(list(x.unique())))
    ).reset_index()

    result = result.sort_values("total_revenue", ascending=False).reset_index(drop=True)
    result["total_revenue"] = result["total_revenue"].round(2)
    result["pct_of_total"] = (result["total_revenue"] / result["total_revenue"].sum() * 100).round(1)
    result = result.head(limit)

    return result


def get_mrr_trend(start_date=None, end_date=None, currency_filter=None) -> pd.DataFrame:
    """
    Monthly Recurring Revenue trended by month.
    Compatible with Stripe SDK v14.
    """
    charges_df = get_succeeded_charges(start_date=start_date, end_date=end_date)

    if charges_df.empty:
        return pd.DataFrame()

    if currency_filter:
        charges_df = charges_df[charges_df["currency"] == currency_filter.upper()]

    # Build lookup: payment_intent_id -> charge_id
    pi_to_charge = {}
    for _, row in charges_df.iterrows():
        if row["payment_intent_id"]:
            pi_to_charge[row["payment_intent_id"]] = row["charge_id"]

    valid_pi_ids = set(pi_to_charge.keys())

    params = {"limit": 100, "status": "paid", "expand[]": "data.payments"}

    created = {}
    if start_date:
        dt_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        created["gte"] = int(dt_start.timestamp())
    if end_date:
        dt_end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        created["lte"] = int(dt_end.timestamp()) + 86399
    if created:
        params["created"] = created

    records = []
    for inv in stripe.Invoice.list(**params).auto_paging_iter():
        # Extract payment_intent from payments sub-object
        inv_pi = _get_invoice_payment_intent(inv)

        # Match to a valid charge
        if not inv_pi or inv_pi not in valid_pi_ids:
            continue

        # Check if subscription invoice
        inv_billing_reason = inv.get("billing_reason") or ""
        inv_subscription = inv.get("subscription")

        # Fallback: extract subscription from string
        if not inv_subscription:
            inv_subscription = _extract_from_string(inv, "sub_")

        is_subscription = bool(inv_subscription) or "subscription" in inv_billing_reason

        if not is_subscription:
            continue

        dt = datetime.fromtimestamp(inv["created"], tz=timezone.utc)
        inv_currency = (inv["currency"] or "unknown").upper()

        if currency_filter and inv_currency != currency_filter.upper():
            continue

        inv_amount_paid = inv["amount_paid"] or 0

        records.append({
            "invoice_id": inv["id"],
            "month": dt.strftime("%Y-%m"),
            "currency": inv_currency,
            "amount_paid": round(inv_amount_paid / 100, 2),
            "subscription_id": inv_subscription
        })

    df = pd.DataFrame(records)

    if df.empty:
        print("⚠️  No subscription invoices found.")
        return pd.DataFrame()

    result = df.groupby("month").agg(
        mrr=("amount_paid", "sum"),
        subscription_invoices=("invoice_id", "count"),
        unique_subscriptions=("subscription_id", "nunique")
    ).reset_index()

    result = result.sort_values("month").reset_index(drop=True)
    result["mrr"] = result["mrr"].round(2)

    return result








