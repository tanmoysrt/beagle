"""Write the synthetic benchmark app to a directory.

App ``shop``: a few Python modules and three DocTypes, designed so every
relationship beagle should find has a known, internal target. Keep this in sync
with ``gold.py`` — the gold data enumerates exactly what these files produce.
"""

from __future__ import annotations

import json
from pathlib import Path

_FILES: dict[str, str] = {
    "shop/__init__.py": "",
    "shop/doctype/__init__.py": "",
    "shop/doctype/order/__init__.py": "",
    "shop/base.py": (
        "class BaseDoc:\n"
        "    def validate(self):\n"
        "        return True\n\n"
        "    def save(self):\n"
        "        return self.validate()\n"
    ),
    "shop/utils.py": (
        "def slugify(value):\n"
        "    return value.strip()\n\n\n"
        "def make_code(value):\n"
        "    return slugify(value)\n"
    ),
    "shop/tasks.py": (
        "def process_order(order=None):\n"
        "    return order\n"
    ),
    "shop/api.py": (
        "import frappe\n"
        "from shop.utils import make_code\n\n\n"
        "@frappe.whitelist()\n"
        "def create_order(customer):\n"
        "    code = make_code(customer)\n"
        '    doc = frappe.new_doc("Order")\n'
        '    frappe.enqueue("shop.tasks.process_order", order=code)\n'
        "    return doc\n"
    ),
    "shop/hooks.py": (
        'doc_events = {"Order": {"validate": "shop.tasks.process_order"}}\n\n'
        'scheduler_events = {"daily": ["shop.tasks.process_order"]}\n\n'
        'override_doctype_class = {"Customer": "shop.base.BaseDoc"}\n'
    ),
    "shop/doctype/order/order.py": (
        "from shop.base import BaseDoc\n"
        "from shop.utils import slugify\n\n\n"
        "class Order(BaseDoc):\n"
        "    def validate(self):\n"
        "        slugify(self.name)\n"
        "        return super().validate()\n\n"
        "    def book(self):\n"
        "        return self.validate()\n"
    ),
    "shop/doctype/order/test_order.py": (
        "from shop.doctype.order.order import Order\n\n\n"
        "class TestOrder(FrappeTestCase):\n"
        "    def test_book(self):\n"
        "        return Order().book()\n"
    ),
}

_DOCTYPES: dict[str, dict] = {
    "shop/doctype/order/order.json": {
        "doctype": "DocType", "name": "Order", "module": "Shop",
        "fields": [
            {"fieldname": "customer", "fieldtype": "Link", "options": "Customer"},
            {"fieldname": "items", "fieldtype": "Table", "options": "Order Item"},
            {"fieldname": "code", "fieldtype": "Data"},
        ],
    },
    "shop/doctype/customer/customer.json": {
        "doctype": "DocType", "name": "Customer", "module": "Shop", "fields": [],
    },
    "shop/doctype/order_item/order_item.json": {
        "doctype": "DocType", "name": "Order Item", "module": "Shop",
        "istable": 1, "fields": [],
    },
}


def write_fixture(root: Path) -> Path:
    """Create the ``shop`` app under ``root`` and return ``root``."""
    for relpath, content in _FILES.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for relpath, obj in _DOCTYPES.items():
        path = root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2))
    return root
