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

@frappe.whitelist()
def get_generate_invoice_options():
    field = frappe.get_doc(
        "DocField",
        {
            "fieldname": "generate_invoice_at",
            "parent": "Subscription",  # Replace with actual parent DocType
        },
    )

    options = field.options.split("\n") if field.options else []
    return {"options": options}


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


def str_to_bool(value):
    return str(value).lower() in ("true", "1", "yes")


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
                "generate_invoice_at": data.get(
                    "generate_invoice_at", "End of the current subscription period"
                ),
                "start_date": data["start_date"],
                "end_date": data["end_date"],
                "trial_period_start": data.get("trial_period_start"),
                "trial_period_end": data.get("trial_period_end"),
                "days_until_due": data.get("days_until_due"),
                "generate_new_invoices_past_due_date": str_to_bool(
                    data.get("generate_new_invoices_past_due_date")
                ),
                "cancel_at_period_end": str_to_bool(data.get("cancel_at_period_end")),
                "submit_invoice": str_to_bool(data.get("submit_invoice")),
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


@frappe.whitelist(allow_guest=True)
def delete_subscription(subscription_id):
    """
    Delete a Subscription by ID.
    """
    try:
        if not subscription_id:
            return {"status": "error", "message": "Missing subscription_id"}

        if not frappe.db.exists("Subscription", subscription_id):
            return {
                "status": "error",
                "message": f"Subscription '{subscription_id}' does not exist",
            }

        # Load and delete the Subscription
        sub_doc = frappe.get_doc("Subscription", subscription_id)
        sub_doc.delete(ignore_permissions=True)
        frappe.db.commit()

        return {
            "status": "success",
            "message": f"Subscription '{subscription_id}' deleted successfully",
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Delete Subscription API Error")
        return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=True)
def update_subscription(data):
    """
    Update a Subscription:
    - company
    - generate_invoice_at
    - plans (create plan + item if not exist, replace old plans)
    """
    try:
        if isinstance(data, str):
            data = frappe.parse_json(data)

        subscription_id = data.get("subscription_id")
        if not subscription_id:
            return {"status": "error", "message": "Missing 'subscription_id'"}

        if not frappe.db.exists("Subscription", subscription_id):
            return {
                "status": "error",
                "message": f"Subscription '{subscription_id}' does not exist",
            }

        subscription = frappe.get_doc("Subscription", subscription_id)

        # Update company
        if "company" in data:
            subscription.company = data["company"]

        # Update generate_invoice_at
        if "generate_invoice_at" in data:
            subscription.generate_invoice_at = data["generate_invoice_at"]

        if "generate_new_invoices_past_due_date" in data:
            subscription.generate_new_invoices_past_due_date = str_to_bool(data[
                "generate_new_invoices_past_due_date"
            ])

        if "cancel_at_period_end" in data:
            subscription.cancel_at_period_end = str_to_bool(data["cancel_at_period_end"])

        if "submit_invoice" in data:
            subscription.submit_invoice = str_to_bool(data["submit_invoice"])

        updated_plans = []
        for plan_data in data.get("plans", []):
            plan_name = plan_data.get("name")
            item_code = plan_data.get("item_code")
            quantity = plan_data.get("quantity", 1)

            if not plan_name or not item_code:
                return {
                    "status": "error",
                    "message": "Each plan must include 'name' and 'item_code'",
                }

            # Create Item if it doesn't exist
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

            # Create Subscription Plan if it doesn't exist
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

            # Add to updated plan list
            updated_plans.append({"plan": plan_name, "qty": quantity})

        # Replace existing plans
        if updated_plans:
            subscription.set("plans", [])  # clear
            for plan in updated_plans:
                subscription.append("plans", plan)

        subscription.save(ignore_permissions=True)
        frappe.db.commit()

        return {
            "status": "success",
            "message": f"Subscription '{subscription_id}' updated successfully",
            "updated_plans": updated_plans,
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Update Subscription API Error")
        return {"status": "error", "message": str(e)}
