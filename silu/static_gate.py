"""The --static gate: refuse programs whose compiled code touches the
dynamic (pyobj) world.

The typed backend compiles unannotated / conflicting names to PyObject
storage - a SILENT fallback. This gate turns that into a loud error:
after conversion, every runtime symbol the user part references is
censused against a whitelist of the statically-typed families.

Allowed (statically typed native code):
    silu_panic, float_repr, view_ord   - scalars need these
    rawstr_* / rawlist_* / rawdict_* / rawutf8_* - TYPED str/list/dict
        variables use the native struct families, no boxing

Forbidden (the dynamic world): create_* boxing, pyobj_* dispatch,
unbox_*, the boxed dict_*/list_*/str_* method families, and the
pyobj<->native bridges. A program that only binds scalars references
none of them (fib references exactly one runtime symbol: silu_panic).
"""

import re

_ALLOWED_EXACT = {"silu_panic", "float_repr", "view_ord"}
_ALLOWED_PREFIXES = ("rawstr_", "rawlist_", "rawdict_", "rawutf8_")


def _is_allowed(name):
    return name in _ALLOWED_EXACT or name.startswith(_ALLOWED_PREFIXES)


def static_violations(full_ll):
    """Runtime symbols the program's own code references that belong
    to the dynamic world. Empty list == pure static (by this gate's
    definition: typed str/list/dict count as static)."""
    from silu import runtime_cache

    rt_ll, user_ll = runtime_cache.split(full_ll)
    rt_defined = set(
        re.findall(r'^define[^@]*@"([A-Za-z0-9_.$]+)"',
                   runtime_cache._body(rt_ll), re.M)
    )
    user_body = runtime_cache._body(user_ll)
    refs = set(re.findall(r'@"([A-Za-z0-9_.$]+)"', user_body))
    user_defined = set(
        re.findall(r'^define\s+[^\n]*@"([A-Za-z0-9_.$]+)"', user_body, re.M)
    ) | set(re.findall(r'^@"([A-Za-z0-9_.$]+)"\s*=', user_body, re.M))
    used_runtime = (refs - user_defined) & rt_defined
    return sorted(n for n in used_runtime if not _is_allowed(n))


def static_gate_error(violations):
    """The user-facing error text for a failed gate."""
    return (
        "--static: program is not pure static - compiled code "
        "references the dynamic (pyobj) runtime: "
        + ", ".join(violations[:12])
        + (f" (+{len(violations) - 12} more)" if len(violations) > 12 else "")
        + ". Drop --static, or make the offending values statically "
        "typed (annotations / no rebinding across types)."
    )
