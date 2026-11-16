"""The match-statement compilation methods of TypedCodegen.

Split out of silu/typed_codegen.py (module step C of the
modularization plan): class-pattern narrowing (v1.7.0), the
value/or/capture/wildcard pattern set, and the match statement
emitter. tools/flatten_codegen.py splices these blocks back at
their historical positions, keeping the flattened output
byte-identical - the acceptance gate is the fixed-point test.
"""

from typing import Any, Tuple

from silu.ir_iface import ir
from silu.typed_helpers import (
    F64, I1, I64, OBJ, RAWSTR, INSTANCE, LLVM_KIND_TYPES,
)


class TypedMatchMixin:

    def _match_pattern_parts(self, pattern, subject_kind, subject_tv) -> Tuple:
        """(condition_or_None, capture_name_or_None). A None condition
        means the pattern always matches (capture/wildcard)."""
        if not isinstance(pattern, (list, tuple)) or not pattern:
            raise NotImplementedError("unsupported match pattern")
        kind_tag = pattern[0]
        if kind_tag == "match_value":
            return self._match_value_condition(pattern[1], subject_kind, subject_tv), None
        if kind_tag == "match_or":
            cond = None
            for alt in pattern[1]:
                alt_cond, capture = self._match_pattern_parts(alt, subject_kind, subject_tv)
                if capture is not None:
                    raise NotImplementedError(
                        "capture inside an or-pattern is not supported "
                        "in compiled code"
                    )
                cond = (
                    alt_cond
                    if cond is None
                    else self.current_builder.or_(cond, alt_cond)
                )
            return cond, None
        if kind_tag == "match_singleton":
            # True / False (None stays interpreter-only)
            value = pattern[1]
            if not isinstance(value, bool):
                raise NotImplementedError(
                    "compiled match does not support None patterns"
                )
            return self._match_value_condition(["const", int(value)], subject_kind, subject_tv), None
        if kind_tag == "match_as":
            nested, capture = pattern[1], pattern[2]
            if nested is not None:
                raise NotImplementedError(
                    "compiled match does not support nested capture "
                    "patterns"
                )
            return None, capture  # capture may be None (wildcard)
        raise NotImplementedError(
            f"compiled match does not support '{kind_tag}' patterns "
            "(value / or / capture / wildcard / guard only)"
        )


    def _match_class_head(self, pattern, subject_tv) -> Tuple:
        """(cid condition, [(capture_name, field_index, field_tuple)])
        for a match_class pattern against a dynamic subject box."""
        cls_node = pattern[1]
        if (
            not isinstance(cls_node, (list, tuple))
            or len(cls_node) < 2
            or cls_node[0] != "name"
            or cls_node[1] not in self._class_layouts
        ):
            raise NotImplementedError(
                "class patterns need a known class name, got "
                + str(cls_node)
            )
        cls = cls_node[1]
        fields = self._class_layouts[cls]["fields"]
        field_index = {}
        for fi, ftup in enumerate(fields):
            field_index[ftup[0]] = fi

        def check_sub(sub):
            # returns the capture name or None; nested defs cannot
            # raise (the hoister treats builtins as captures)
            if (
                isinstance(sub, (list, tuple))
                and len(sub) >= 3
                and sub[0] == "match_as"
                and sub[1] is None
                and sub[2] is not None
            ):
                return sub[2]
            return None

        bindings = []
        for index, sub in enumerate(pattern[2] or ()):
            name = check_sub(sub)
            if name is None:
                raise NotImplementedError(
                    "class patterns support simple captures "
                    "(case C(x) / C(k=x))"
                )
            if index >= len(fields):
                raise TypeError(
                    f"class pattern for '{cls}' binds more captures "
                    f"than the class has fields"
                )
            bindings.append((name, index, fields[index]))
        kwd_attrs = pattern[3] if len(pattern) > 3 else []
        kwd_pats = pattern[4] if len(pattern) > 4 else []
        for attr, sub in zip(kwd_attrs, kwd_pats):
            if attr not in field_index:
                raise TypeError(
                    f"class pattern for '{cls}' references unknown "
                    f"field '{attr}'"
                )
            kname = check_sub(sub)
            if kname is None:
                raise NotImplementedError(
                    "class patterns support simple captures "
                    "(case C(x) / C(k=x))"
                )
            bindings.append((kname, field_index[attr],
                             fields[field_index[attr]]))
        cid = self.current_builder.call(
            self.pyobj_instance_cid, [subject_tv[1]]
        )
        cond = self.current_builder.icmp_signed(
            "==", cid,
            ir.const_(ir.IntType(64), self._class_ids[cls]),
        )
        return cond, bindings

    def _bind_match_class_fields(self, bindings, subject_tv) -> None:
        """Inside a matched class-pattern arm: load each captured field
        with its declared kind (str fields copy on read, exactly like
        attribute reads on known instances)."""
        inst = self.current_builder.call(
            self.pyobj_instance_ptr, [subject_tv[1]]
        )
        for name, index, __ftup in bindings:
            field_name, kind, _default, fclass = __ftup
            slot = self._field_slot(inst, index, kind)
            value = self.current_builder.load(slot)
            if kind == RAWSTR:
                value = self.current_builder.call(
                    self.rawstr_copy, [value]
                )
            # bare list/dict fields carry kind None; normalize like
            # _field_slot so the declared slot matches the loaded one
            if kind is None or (
                kind != INSTANCE and kind not in LLVM_KIND_TYPES
            ):
                kind = OBJ
            if kind == INSTANCE and fclass:
                self._var_class[name] = fclass
            self._declare_var(name, kind)
            self.current_builder.store(value, self.variables[name])

    def _match_value_condition(self, value_node, subject_kind, subject_tv) -> Any:
        """i1 condition: subject == the pattern's value."""
        if subject_kind == RAWSTR:
            if (
                isinstance(value_node, list)
                and len(value_node) >= 2
                and value_node[0] == "const"
                and isinstance(value_node[1], str)
            ):
                text = value_node[1]
                return self.current_builder.call(
                    self.rawstr_eq_cstr,
                    [
                        subject_tv[1],
                        self._create_global_string(text),
                        ir.const_(
                            ir.IntType(64), len(text.encode("utf-8"))
                        ),
                    ],
                )
            value_tv = self._coerce(self._convert_node(value_node), RAWSTR)
            cond = self.current_builder.call(
                self.rawstr_eq, [subject_tv[1], value_tv[1]]
            )
            self.current_builder.call(self.rawstr_free, [value_tv[1]])
            return cond
        target_kind = I64 if subject_kind == I1 else subject_kind
        value_tv = self._coerce(
            self._convert_node(value_node), target_kind
        )
        if subject_kind == F64:
            return self.current_builder.fcmp_ordered(
                "==", subject_tv[1], value_tv[1]
            )
        if subject_kind == I1:
            subject_i64 = self.current_builder.zext(
                subject_tv[1], ir.IntType(64)
            )
            return self.current_builder.icmp_signed(
                "==", subject_i64, value_tv[1]
            )
        return self.current_builder.icmp_signed(
            "==", subject_tv[1], value_tv[1]
        )

    def _match_switch_arms(self, node):
        """([(int_value, body)...], wildcard_body) when the match is
        switch-eligible, else None. Structural rules the Rust twin
        replicates verbatim (reference/PROPOSALS.md P8): every case is
        a non-bool int const value pattern or the TRAILING unnamed
        wildcard, no guards, no duplicate values, at least one value
        arm. Written in the selfhost-safe subset (no zip, no nested
        tuple unpacking, no set) - this file is spliced into
        typed_codegen_flat.si and compiled by silu itself."""
        cases = node[2]
        if not cases:
            return None
        arms = []
        wild_body = None
        for ci, case in enumerate(cases):
            if (
                not isinstance(case, (list, tuple))
                or len(case) < 4
                or case[0] != "match_case"
            ):
                return None
            pattern = case[1]
            guard = case[2]
            body = case[3]
            if guard is not None:
                return None
            if (
                isinstance(pattern, (list, tuple))
                and len(pattern) >= 3
                and pattern[0] == "match_as"
                and pattern[1] is None
                and pattern[2] is None
            ):
                if wild_body is not None or ci != len(cases) - 1:
                    return None
                wild_body = body
                continue
            if (
                isinstance(pattern, (list, tuple))
                and len(pattern) >= 2
                and pattern[0] == "match_value"
                and isinstance(pattern[1], (list, tuple))
                and len(pattern[1]) >= 2
                and pattern[1][0] == "const"
                and isinstance(pattern[1][1], int)
                and not isinstance(pattern[1][1], bool)
            ):
                value = pattern[1][1]
                dup = False
                for prev in arms:
                    if prev[0] == value:
                        dup = True
                if dup:
                    return None
                arms.append((value, body))
                continue
            return None
        if not arms:
            return None
        return (arms, wild_body)

    def _convert_match_switch(self, node, sw_arms, subject_tv):
        """P8 switch fast path: block creation order (default, cases in
        source order, end) is part of the byte contract with the Rust
        twin; llvmlite renders the switch as ONE line
        `switch i64 %v, label %d [i64 1, label %c i64 5, label %c.1]`
        and consumes one anonymous slot like br."""
        arms = sw_arms[0]
        wild_body = sw_arms[1]
        func = self.current_function
        default_block = func.append_basic_block("match_default")
        case_blocks = []
        k = 0
        while k < len(arms):
            case_blocks.append(func.append_basic_block("match_case"))
            k += 1
        end_block = func.append_basic_block("match_end")
        # positional only: the .si llvmlite twin has no keyword calls
        sw = self.current_builder.switch(subject_tv[1], default_block)
        k = 0
        while k < len(arms):
            sw.add_case(
                ir.const_(ir.IntType(64), arms[k][0]), case_blocks[k]
            )
            k += 1
        k = 0
        while k < len(arms):
            self.current_builder.position_at_end(case_blocks[k])
            body = arms[k][1]
            for stmt in body:
                self._convert_statement(stmt)
                if self.current_builder.block.is_terminated:
                    break
            if not self.current_builder.block.is_terminated:
                self.current_builder.branch(end_block)
            k += 1
        self.current_builder.position_at_end(default_block)
        if wild_body is not None:
            for stmt in wild_body:
                self._convert_statement(stmt)
                if self.current_builder.block.is_terminated:
                    break
        if not self.current_builder.block.is_terminated:
            self.current_builder.branch(end_block)
        self.current_builder.position_at_end(end_block)

    def _convert_match(self, node: list):
        """match statement over a statically-typed scalar/str subject.

        Supported patterns: value literals (incl. enum members, they
        fold to constants), or-patterns, capture (case n), wildcard
        (case _), guards (case n if n > 0). Sequence/mapping/class
        patterns stay interpreter-only. First match wins; no match is
        a no-op (Python semantics)."""
        subject_tv = self._convert_node(node[1])
        subject_kind = subject_tv[0]
        if subject_kind not in (I64, I1, F64, RAWSTR, OBJ):
            raise NotImplementedError(
                "compiled match needs a statically typed subject "
                "(annotate it: x: int / float / bool / str)"
            )
        if subject_kind == I64:
            sw_arms = self._match_switch_arms(node)
            if sw_arms is not None:
                self._convert_match_switch(node, sw_arms, subject_tv)
                return
        func = self.current_function
        end_block = func.append_basic_block("match_end")

        for case in node[2]:
            if (
                not isinstance(case, (list, tuple))
                or len(case) < 4
                or case[0] != "match_case"
            ):
                continue
            pattern, guard_node, body = case[1], case[2], case[3]
            body_block = func.append_basic_block("case_body")
            next_block = func.append_basic_block("case_next")

            if (
                isinstance(pattern, (list, tuple))
                and pattern
                and pattern[0] == "match_class"
            ):
                # class pattern over a dynamic subject: the cid check
                # branches first, then the arm binds the payload fields
                # with their DECLARED kinds - the narrowing
                cond, bindings = self._match_class_head(pattern, subject_tv)
                guard_blk = (
                    func.append_basic_block("case_guard")
                    if guard_node is not None
                    else body_block
                )
                self.current_builder.cbranch(cond, guard_blk, next_block)
                self.current_builder.position_at_end(guard_blk)
                self._bind_match_class_fields(bindings, subject_tv)
                if guard_node is not None:
                    guard_cond = self._to_i1_cond(
                        self._convert_node(guard_node)
                    )
                    self.current_builder.cbranch(
                        guard_cond, body_block, next_block
                    )
                self.current_builder.position_at_end(body_block)
                for stmt in body:
                    self._convert_statement(stmt)
                    if self.current_builder.block.is_terminated:
                        break
                if not self.current_builder.block.is_terminated:
                    self.current_builder.branch(end_block)
                self.current_builder.position_at_end(next_block)
                continue

            if subject_kind == OBJ and (
                not isinstance(pattern, (list, tuple))
                or not pattern
                or pattern[0] not in ("match_as",)
            ):
                raise NotImplementedError(
                    "a dynamic (untyped) match subject supports class "
                    "patterns and captures/wildcards only - annotate "
                    "the subject to match values against it"
                )
            cond, capture = self._match_pattern_parts(pattern, subject_kind, subject_tv)
            if capture is not None:
                # bind before the guard (guard may reference it)
                if subject_kind == RAWSTR:
                    self._declare_var(capture, RAWSTR)
                    self._store_rawstr(
                        capture,
                        self.current_builder.call(
                            self.rawstr_copy, [subject_tv[1]]
                        ),
                    )
                else:
                    self._declare_var(capture, subject_kind)
                    self.current_builder.store(
                        subject_tv[1], self.variables[capture]
                    )
            if cond is not None:
                guard_blk = (
                    func.append_basic_block("case_guard")
                    if guard_node is not None
                    else body_block
                )
                self.current_builder.cbranch(cond, guard_blk, next_block)
                self.current_builder.position_at_end(guard_blk)
            if guard_node is not None:
                guard_cond = self._to_i1_cond(self._convert_node(guard_node))
                self.current_builder.cbranch(guard_cond, body_block, next_block)
            if cond is None and guard_node is None:
                self.current_builder.branch(body_block)

            self.current_builder.position_at_end(body_block)
            for stmt in body:
                self._convert_statement(stmt)
                if self.current_builder.block.is_terminated:
                    break
            if not self.current_builder.block.is_terminated:
                self.current_builder.branch(end_block)

            self.current_builder.position_at_end(next_block)

        self.current_builder.branch(end_block)
        self.current_builder.position_at_end(end_block)
