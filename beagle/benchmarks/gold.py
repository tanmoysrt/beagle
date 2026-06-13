"""Enumerated ground truth for the ``shop`` fixture.

Every expected symbol, resolved edge, and retrieval answer is listed here. The
fixture is small enough that these sets are *complete*, so precision can count
false positives (anything produced but not listed) and recall can count misses.
Keep in lockstep with ``fixture.py``.
"""

from __future__ import annotations

# --- symbols (kinds: module/class/function/method/test_*) ---------------

SYMBOLS: set[str] = {
    "python://shop",
    "python://shop.doctype",
    "python://shop.doctype.order",
    "python://shop.base",
    "python://shop.utils",
    "python://shop.tasks",
    "python://shop.api",
    "python://shop.hooks",
    "python://shop.doctype.order.order",
    "python://shop.doctype.order.test_order",
    "python://shop.base#BaseDoc",
    "python://shop.base#BaseDoc.validate",
    "python://shop.base#BaseDoc.save",
    "python://shop.utils#slugify",
    "python://shop.utils#make_code",
    "python://shop.tasks#process_order",
    "python://shop.api#create_order",
    "python://shop.doctype.order.order#Order",
    "python://shop.doctype.order.order#Order.validate",
    "python://shop.doctype.order.order#Order.book",
    "python://shop.doctype.order.test_order#TestOrder",
    "python://shop.doctype.order.test_order#TestOrder.test_book",
}
SYMBOL_KINDS = ("module", "class", "function", "method", "test_class", "test_function")

# --- resolved imports (source module id -> target id) -------------------

IMPORTS: set[tuple[str, str]] = {
    ("python://shop.doctype.order.order", "python://shop.base#BaseDoc"),
    ("python://shop.doctype.order.order", "python://shop.utils#slugify"),
    ("python://shop.api", "python://shop.utils#make_code"),
    ("python://shop.doctype.order.test_order", "python://shop.doctype.order.order#Order"),
}

# --- resolved direct calls (source id -> target id) ---------------------

CALLS: set[tuple[str, str]] = {
    ("python://shop.utils#make_code", "python://shop.utils#slugify"),
    ("python://shop.api#create_order", "python://shop.utils#make_code"),
    ("python://shop.base#BaseDoc.save", "python://shop.base#BaseDoc.validate"),
    ("python://shop.doctype.order.order#Order.validate", "python://shop.utils#slugify"),
    ("python://shop.doctype.order.order#Order.validate", "python://shop.base#BaseDoc.validate"),
    ("python://shop.doctype.order.order#Order.book", "python://shop.doctype.order.order#Order.validate"),
    ("python://shop.doctype.order.test_order#TestOrder.test_book", "python://shop.doctype.order.order#Order"),
    ("python://shop.doctype.order.test_order#TestOrder.test_book", "python://shop.doctype.order.order#Order.book"),
}

# --- Frappe relationships (source, relationship, target) ----------------

FRAPPE_RELATIONSHIPS = (
    "HAS_FIELD", "LINKS_TO", "CONTAINS_CHILD", "HAS_CONTROLLER", "TESTS",
    "EXPOSES_ENDPOINT", "CREATES_DOCTYPE", "READS_DOCTYPE", "WRITES_DOCTYPE",
    "DELETES_DOCTYPE", "ENQUEUES", "INVOKES",
)

FRAPPE: set[tuple[str, str, str]] = {
    ("doctype://shop/Order", "HAS_FIELD", "doctype-field://shop/Order#customer"),
    ("doctype://shop/Order", "HAS_FIELD", "doctype-field://shop/Order#items"),
    ("doctype://shop/Order", "HAS_FIELD", "doctype-field://shop/Order#code"),
    ("doctype-field://shop/Order#customer", "LINKS_TO", "doctype://shop/Customer"),
    ("doctype://shop/Order", "CONTAINS_CHILD", "doctype://shop/Order Item"),
    ("doctype://shop/Order", "HAS_CONTROLLER", "python://shop.doctype.order.order#Order"),
    ("doctype://shop/Customer", "HAS_CONTROLLER", "python://shop.base#BaseDoc"),
    ("python://shop.doctype.order.test_order#TestOrder", "TESTS", "doctype://shop/Order"),
    ("python://shop.api#create_order", "EXPOSES_ENDPOINT", "endpoint://shop.api.create_order"),
    ("python://shop.api#create_order", "CREATES_DOCTYPE", "doctype://shop/Order"),
    ("python://shop.api#create_order", "ENQUEUES", "job://shop.tasks.process_order"),
    ("job://shop.tasks.process_order", "INVOKES", "python://shop.tasks#process_order"),
    ("doctype://shop/Order", "INVOKES", "python://shop.tasks#process_order"),
    ("python://shop.hooks", "INVOKES", "python://shop.tasks#process_order"),
}

# --- inheritance / overrides (must exist; not a precision metric) -------

INHERITS_OVERRIDES: set[tuple[str, str, str]] = {
    ("python://shop.doctype.order.order#Order", "INHERITS", "python://shop.base#BaseDoc"),
    ("python://shop.doctype.order.order#Order.validate", "OVERRIDES", "python://shop.base#BaseDoc.validate"),
}

# --- retrieval cases ----------------------------------------------------

EXACT_SYMBOL: list[tuple[str, str]] = [
    ("Order", "doctype://shop/Order"),
    ("slugify", "python://shop.utils#slugify"),
    ("make_code", "python://shop.utils#make_code"),
    ("BaseDoc", "python://shop.base#BaseDoc"),
    ("create_order", "python://shop.api#create_order"),
    ("process_order", "python://shop.tasks#process_order"),
    ("TestOrder", "python://shop.doctype.order.test_order#TestOrder"),
    ("Order.book", "python://shop.doctype.order.order#Order.book"),
]

TOP5: list[tuple[str, str]] = [
    ("slugify value strip", "python://shop.utils#slugify"),
    ("make_code value", "python://shop.utils#make_code"),
    ("create order customer", "python://shop.api#create_order"),
    ("process order task", "python://shop.tasks#process_order"),
]

# context cases: (intent, query, must_include, relevant_allowlist)
CONTEXT_CASES: list[tuple[str, str, set[str], set[str]]] = [
    (
        "understand",
        "How does Order validation work?",
        {
            "python://shop.doctype.order.order#Order",
            "python://shop.doctype.order.order#Order.validate",
            "python://shop.base#BaseDoc",
        },
        {
            "doctype://shop/Order",
            "python://shop.doctype.order.order#Order",
            "python://shop.doctype.order.order#Order.validate",
            "python://shop.doctype.order.order#Order.book",
            "python://shop.base#BaseDoc",
            "python://shop.base#BaseDoc.validate",
            "python://shop.base#BaseDoc.save",
            "python://shop.utils#slugify",
            "doctype-field://shop/Order#customer",
            "doctype-field://shop/Order#items",
            "doctype-field://shop/Order#code",
            "doctype://shop/Customer",
            "doctype://shop/Order Item",
            # genuinely related: validate doc_event handler, tests, creator
            "python://shop.tasks#process_order",
            "python://shop.doctype.order.test_order#TestOrder",
            "python://shop.doctype.order.test_order#TestOrder.test_book",
            "python://shop.api#create_order",
        },
    ),
    (
        "change",
        "Change the Order book method",
        {
            "python://shop.doctype.order.order#Order.book",
        },
        {
            "doctype://shop/Order",
            "python://shop.doctype.order.order#Order",
            "python://shop.doctype.order.order#Order.book",
            "python://shop.doctype.order.order#Order.validate",
            "python://shop.doctype.order.test_order#TestOrder",
            "python://shop.doctype.order.test_order#TestOrder.test_book",
            "python://shop.base#BaseDoc",
            "doctype-field://shop/Order#customer",
            "doctype-field://shop/Order#items",
            "doctype-field://shop/Order#code",
            "doctype://shop/Customer",
            "doctype://shop/Order Item",
            "python://shop.tasks#process_order",
        },
    ),
]

# --- design/05 targets (percentages, and the zero-stale-facts gate) -----

TARGETS = {
    "symbol_precision": 99.0,
    "symbol_recall": 98.0,
    "import_precision": 97.0,
    "import_recall": 93.0,
    "call_precision": 92.0,
    "call_recall": 82.0,
    "frappe_precision": 97.0,
    "frappe_recall": 90.0,
    "exact_symbol": 98.0,
    "top5": 95.0,
    "must_include": 90.0,
    "irrelevant_max": 20.0,
}
