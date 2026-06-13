from __future__ import annotations

from beagle.extractors.python import extract_python

SOURCE = '''\
"""Module doc."""
import frappe
from frappe.model.document import Document as Doc

CONST = make_const()


class Site(Doc):
    """A site."""

    status: str

    def __init__(self):
        self.agent = Agent()

    def deploy(self):
        helper()
        return self.agent.run()


def helper():
    return run_deployment()


class TestSite(FrappeTestCase):
    def test_deploy(self):
        assert True
'''


def by_id(extraction, suffix):
    return next(e for e in extraction.entities if e.id.endswith(suffix))


def obs(extraction, kind):
    return [o for o in extraction.observations if o.kind == kind]


def test_entities_and_kinds():
    ex = extract_python("press/site.py", SOURCE)
    kinds = {e.qualified_name: e.kind for e in ex.entities}
    assert kinds["press.site"] == "module"
    assert kinds["press.site.Site"] == "class"
    assert kinds["press.site.Site.deploy"] == "method"
    assert kinds["press.site.helper"] == "function"
    assert kinds["press.site.TestSite"] == "test_class"
    assert kinds["press.site.TestSite.test_deploy"] == "test_function"


def test_stable_ids_have_no_line_numbers():
    ex = extract_python("press/site.py", SOURCE)
    deploy = by_id(ex, "#Site.deploy")
    assert deploy.id == "python://press.site#Site.deploy"


def test_inheritance_observation():
    ex = extract_python("press/site.py", SOURCE)
    bases = obs(ex, "inheritance")
    site_base = next(o for o in bases if o.subject.endswith("#Site"))
    assert site_base.data["base_name"] == "Doc"


def test_call_observations_subject_is_enclosing():
    ex = extract_python("press/site.py", SOURCE)
    calls = obs(ex, "call")
    deploy_calls = [c for c in calls if c.subject.endswith("#Site.deploy")]
    names = {c.data["func_code"] for c in deploy_calls}
    assert "helper" in names
    assert "self.agent.run" in names


def test_import_observations():
    ex = extract_python("press/site.py", SOURCE)
    imports = obs(ex, "import")
    froms = [o for o in imports if o.data["style"] == "from"]
    assert any(
        o.data["module"] == "frappe.model.document"
        and o.data["names"][0]["name"] == "Document"
        and o.data["names"][0]["asname"] == "Doc"
        for o in froms
    )


def test_constructor_assignment_recorded():
    ex = extract_python("press/site.py", SOURCE)
    assigns = obs(ex, "assignment")
    agent = next(a for a in assigns if a.data["target_code"] == "self.agent")
    assert agent.data["value_callee"] == "Agent"


def test_syntax_error_yields_nothing():
    ex = extract_python("bad.py", "def (:\n")
    assert ex.entities == []
