"""JavaScript / TypeScript / Vue extraction (design/14)."""

from beagle.extractors.javascript.extractor import JsExtraction, extract_javascript
from beagle.extractors.javascript.vue import extract_vue

__all__ = ["JsExtraction", "extract_javascript", "extract_vue"]
