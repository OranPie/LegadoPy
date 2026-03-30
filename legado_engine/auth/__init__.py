"""
auth – source authentication and discovery helpers.

Public API:
    from legado_engine.auth import (
        UiRow, LoginRow, SourceUiActionResult,
        parse_ui_rows, parse_source_ui, parse_login_ui,
        get_source_form_data, get_login_form_data,
        submit_source_form, submit_source_form_detailed,
        submit_login, submit_login_detailed,
        run_source_ui_action, execute_source_ui_action,
        run_login_button_action, execute_login_button_action,
        get_explore_kinds, get_explore_kinds_json,
    )
"""
from .login import (
    UiRow,
    LoginRow,
    SourceUiActionResult,
    parse_ui_rows,
    parse_source_ui,
    parse_login_ui,
    get_source_form_data,
    get_login_form_data,
    submit_source_form,
    submit_source_form_detailed,
    submit_login,
    submit_login_detailed,
    run_source_ui_action,
    execute_source_ui_action,
    run_login_button_action,
    execute_login_button_action,
)
from .explore import (
    get_explore_kinds,
    get_explore_kinds_json,
)

__all__ = [
    "UiRow",
    "LoginRow",
    "SourceUiActionResult",
    "parse_ui_rows",
    "parse_source_ui",
    "parse_login_ui",
    "get_source_form_data",
    "get_login_form_data",
    "submit_source_form",
    "submit_source_form_detailed",
    "submit_login",
    "submit_login_detailed",
    "run_source_ui_action",
    "execute_source_ui_action",
    "run_login_button_action",
    "execute_login_button_action",
    "get_explore_kinds",
    "get_explore_kinds_json",
]
