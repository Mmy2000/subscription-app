import frappe
from frappe import _

@frappe.whitelist(allow_guest=False)
def get_all_subscriptions():
    """
    Fetch all subscriptions from the database.
    """
    return frappe.get_all(
        "Subscription",
        fields=["*"],
        order_by="start_date desc"
    )

@frappe.whitelist(allow_guest=False)
def get_party_type():
    """
    Fetch all unique party types from Subscription.
    """
    return frappe.db.get_all(
        "Subscription",
        fields=["distinct party_type"],
        order_by="party_type"
    )

@frappe.whitelist(allow_guest=True)
def create_subscription(data):
    """
    Create a Subscription, and optionally create Item + Subscription Plan.
    If the party (Customer/Supplier) doesn't exist, create it.
    """
    try:
        if isinstance(data, str):
            data = frappe.parse_json(data)

        required_fields = ["party_type", "party", "start_date", "end_date", "plan"]
        for field in required_fields:
            if not data.get(field):
                return {
                    "status": "error",
                    "message": f"Missing required field: {field}",
                }

        party_type = data["party_type"]
        party_name = data["party"]

        # 0. Create Customer or Supplier if it doesn't exist
        if party_type.lower() == "customer":
            if not frappe.db.exists("Customer", party_name):
                customer_doc = frappe.get_doc(
                    {
                        "doctype": "Customer",
                        "customer_name": party_name,
                        "customer_type": "Individual",  # or "Company"
                        "customer_group": "Individual",
                        "territory": "All Territories",
                    }
                )
                customer_doc.insert(ignore_permissions=True)
                frappe.db.commit()
        elif party_type.lower() == "supplier":
            if not frappe.db.exists("Supplier", party_name):
                supplier_doc = frappe.get_doc(
                    {
                        "doctype": "Supplier",
                        "supplier_name": party_name,
                        "supplier_type": "Company",  # or "Individual"
                        "supplier_group": "All Supplier Groups",
                    }
                )
                supplier_doc.insert(ignore_permissions=True)
                frappe.db.commit()

        # Extract plan details
        plan_data = data["plan"]
        plan_name = plan_data.get("name")
        item_code = plan_data.get("item_code")
        quantity = plan_data.get("quantity", 1)

        if not plan_name or not item_code:
            return {
                "status": "error",
                "message": "Plan must include 'name' and 'item_code'.",
            }

        item_created = False
        plan_created = False

        # 1. Create Item if it doesn't exist
        if not frappe.db.exists("Item", item_code):
            item_doc = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": item_code,
                    "item_name": plan_name,
                    "item_group": "All Item Groups",
                    "stock_uom": "Nos",
                    "is_stock_item": 0,
                    "disabled": 0,
                    "description": f"Auto-generated item for {plan_name}",
                }
            )
            item_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            item_created = True

        # 2. Create Subscription Plan if it doesn't exist
        if not frappe.db.exists("Subscription Plan", plan_name):
            plan_doc = frappe.get_doc(
                {
                    "doctype": "Subscription Plan",
                    "plan_name": plan_name,
                    "name": plan_name,
                    "item": item_code,
                    "billing_interval": plan_data.get("billing_interval", "Month"),
                    "billing_interval_count": plan_data.get(
                        "billing_interval_count", 1
                    ),
                    "cost": plan_data.get("rate", 0.0),
                    "price_determination": "Fixed Rate",
                    "description": plan_data.get(
                        "description", f"Auto-created plan for {plan_name}"
                    ),
                }
            )
            plan_doc.insert(ignore_permissions=True)
            frappe.db.commit()
            plan_created = True

        # 3. Create Subscription with child plan row
        subscription = frappe.get_doc(
            {
                "doctype": "Subscription",
                "party_type": party_type,
                "party": party_name,
                "generate_invoice_at": "End of the current subscription period",
                "start_date": data["start_date"],
                "end_date": data["end_date"],
                "plans": [{"plan": plan_name, "qty": quantity}],
            }
        )
        subscription.insert(ignore_permissions=True)
        frappe.db.commit()

        return {
            "status": "success",
            "subscription_id": subscription.name,
            "item_created": item_created,
            "plan_created": plan_created,
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Create Subscription API Error")
        return {"status": "error", "message": str(e)}
