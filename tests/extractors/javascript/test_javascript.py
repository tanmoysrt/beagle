from __future__ import annotations

from beagle.extractors.javascript import extract_javascript, extract_vue

SITE_JS = '''\
import frappe from "frappe";
import { ref as r } from "./utils";

class SiteController extends frappe.ui.form.Controller {
  refresh() {
    frappe.call({ method: "app.api.deploy", args: { name: this.name } });
  }
  load() {
    frappe.db.get_list("Site", { filters: {} });
  }
}

function save_site() {
  frappe.xcall("app.api.save");
}

const loadNotes = () => createListResource({ doctype: "Note" });
'''


def _entities(result):
    return {e.qualified_name: e for e in result.entities}


def _calls(result):
    return [o.data for o in result.observations if o.kind == "js_api_call"]


def test_entities_for_class_methods_and_functions():
    result = extract_javascript("app/public/js/site.js", SITE_JS, "javascript")
    ents = _entities(result)
    assert ents["app/public/js/site.js"].kind == "js_module"
    assert ents["SiteController"].kind == "js_class"
    assert ents["SiteController.refresh"].kind == "js_method"
    assert ents["SiteController.load"].kind == "js_method"
    assert ents["save_site"].kind == "js_function"
    assert ents["loadNotes"].kind == "js_function"  # arrow const


def test_stable_ids_are_path_based_without_line_numbers():
    result = extract_javascript("app/public/js/site.js", SITE_JS, "javascript")
    ents = _entities(result)
    assert ents["SiteController.refresh"].id == (
        "js://app/public/js/site.js#SiteController.refresh"
    )


def test_import_and_inheritance_observations():
    result = extract_javascript("app/public/js/site.js", SITE_JS, "javascript")
    imports = [o.data["module"] for o in result.observations if o.kind == "js_import"]
    assert "frappe" in imports and "./utils" in imports
    inh = [o.data for o in result.observations if o.kind == "js_inheritance"]
    assert inh[0]["base_name"] == "frappe.ui.form.Controller"


def test_api_calls_capture_method_and_doctype_targets():
    calls = _calls(extract_javascript("app/public/js/site.js", SITE_JS, "javascript"))
    methods = {c["method"] for c in calls if c["target_kind"] == "method"}
    doctypes = {c["doctype"] for c in calls if c["target_kind"] == "doctype"}
    assert {"app.api.deploy", "app.api.save"} <= methods
    assert {"Site", "Note"} <= doctypes


def test_call_subject_is_enclosing_function():
    result = extract_javascript("app/public/js/site.js", SITE_JS, "javascript")
    deploy = next(
        o for o in result.observations
        if o.kind == "js_api_call" and o.data.get("method") == "app.api.deploy"
    )
    assert deploy.subject.endswith("#SiteController.refresh")


def test_computed_method_is_preserved_without_a_literal():
    js = 'function f(x){ frappe.call({ method: x }); }'
    calls = _calls(extract_javascript("a.js", js, "javascript"))
    assert calls and calls[0]["method"] is None  # fact kept, never guessed


def test_fluent_chain_callee_is_recognised():
    # frappe\n.call(...).then(...) — the callee node text carries newlines and
    # indentation; it must still classify as frappe.call, not frm.call.
    js = (
        "function login(name){\n"
        "  frappe\n"
        "    .call({ method: 'press.api.site.login', args: { name } })\n"
        "    .then((r) => r);\n"
        "}\n"
    )
    calls = _calls(extract_javascript("site.js", js, "javascript"))
    call = next(c for c in calls if c["method"] == "press.api.site.login")
    assert call["api"] == "frappe.call"
    assert call["controller_local"] is False  # resolvable, not a form-local method


VUE = '''\
<template><button @click="save">save</button></template>
<script lang="ts">
import { ref } from "vue";
export default {
  methods: {
    save() {
      frappe.call({ method: "app.api.save_doc" });
    }
  }
}
</script>
'''


def test_vue_script_block_is_parsed_with_correct_line_numbers():
    result = extract_vue("app/frontend/Note.vue", VUE)
    save = next(e for e in result.entities if e.name == "save")
    assert save.kind == "js_method"
    call = next(o for o in result.observations if o.kind == "js_api_call")
    assert call.data["method"] == "app.api.save_doc"
    # frappe.call sits on line 7 of the .vue file, not line 5 of the script body.
    assert call.source_range.start_line == 7
