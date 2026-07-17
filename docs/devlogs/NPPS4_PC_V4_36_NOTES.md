# v4.36 CN batch schema diagnostic fix

Continues from v4.35. This build targets the home-entry crash that happens after tutorial completion or after closing the announcement WebView.

Changes:

- Add the missing `unlocked_multi_unit_scenario_ids` field to `multiunit/multiunitscenarioStatus`, matching honoka-chan's CN-era response schema.
- Return a CN/honoka-style `item/list` schema in CN compatibility mode: `general_item_list` items now include `use_button_flag` and `general_item_type`; `buff_item_list` items now include `buff_type`; NPPS4-only reinforce fields are omitted in CN mode.
- Add per-batch-item diagnostic logging for CN `/main.php/api`: each result logs status, response type, and top-level keys so the next logcat can identify the exact response that triggers a client-side Lua fatal.

No masterdata, resource archive, WebUI translation, or database migration logic was changed.
