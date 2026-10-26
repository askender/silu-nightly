# ruff: noqa: E741 - archived one-off analysis script
"""One-shot replay of the layer-2 cleanup for silu/silu_ir_to_llvm.py.

Idempotent-by-construction (runs from a clean HEAD checkout): hoists
the 17 capturing closures, drops default arguments and keyword call
sites, rewrites the two comprehensions, moves the four staticmethods
to module level. Gate: .ll byte-parity on all 16 programs.
"""

import ast
import re

PATH = "silu/silu_ir_to_llvm.py"
src = open(PATH).read()


def rep(old, new, n=1):
    global src
    assert src.count(old) == n, "MISS(%d): %s" % (src.count(old), old[:70])
    src = src.replace(old, new, n)


def cut_def(marker):
    """Remove a nested def block; return its raw lines."""
    global src
    lines = src.split("\n")
    s = next(i for i, l in enumerate(lines) if marker in l)
    ind = len(lines[s]) - len(lines[s].lstrip())
    e = s + 1
    while e < len(lines):
        l = lines[e]
        if l.strip() and (len(l) - len(l.lstrip())) <= ind:
            break
        e += 1
    blk = lines[s:e]
    del lines[s:e]
    src = "\n".join(lines)
    return blk


def dedent4(blk):
    return [l[4:] if l.strip() else l for l in blk]


methods = []

# ---- batch 1: string/list loop helpers ----
rep('''        def load_string_parts(obj):
            data_ptr = builder.gep(obj, [zero32, one32])
            data = builder.load(data_ptr)
            str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
            str_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
            chars = builder.load(builder.gep(str_struct, [zero32, one32]))
            return str_len, chars

''', "")
src = src.replace("left_len, left_chars = load_string_parts(left)",
                  "left_len, left_chars = self._pyobj_string_parts(builder, left, zero32, one32)")
src = src.replace("right_len, right_chars = load_string_parts(right)",
                  "right_len, right_chars = self._pyobj_string_parts(builder, right, zero32, one32)")

rep('''        def for_i64_loop(builder, func, prefix, start, stop):
            """Emit a counting loop header; caller fills body, then closes."""
            idx_ptr = builder.alloca(i64, None, f'{prefix}_i')
            builder.store(start, idx_ptr)
            cond = func.append_basic_block(f"{prefix}_cond")
            body = func.append_basic_block(f"{prefix}_body")
            done = func.append_basic_block(f"{prefix}_done")
            builder.branch(cond)
            builder.position_at_end(cond)
            current = builder.load(idx_ptr)
            more = builder.icmp_signed("<", current, stop)
            builder.cbranch(more, body, done)
            builder.position_at_end(body)
            return idx_ptr, cond, body, done

        def close_loop(builder, idx_ptr, cond):
            builder.store(builder.add(builder.load(idx_ptr), one64), idx_ptr)
            builder.branch(cond)

        def load_list_parts(builder, func, obj, prefix):
            """Return (struct_ptr, length, items) with items loop-ready."""
            struct_ptr = self._load_list_struct(builder, obj)
            length = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
            items = builder.load(builder.gep(struct_ptr, [zero32, ir.const_(i32, 2)]))
            return struct_ptr, length, items

''', "")
src = src.replace("close_loop(builder, idx_ptr, cond)",
                  "self._close_i64_loop(builder, idx_ptr, cond, one64)")
src = src.replace("for_i64_loop(", "self._for_i64_loop(i64, ")
src = src.replace("load_list_parts(", "self._list_parts(builder, ")
src = src.replace("self._for_i64_loop(i64, self._for_i64_loop(i64, ",
                  "self._for_i64_loop(i64, ")

methods.append('''    def _pyobj_string_parts(self, builder, obj, zero32, one32):
        data_ptr = builder.gep(obj, [zero32, one32])
        data = builder.load(data_ptr)
        str_struct = builder.bitcast(data, ir.PointerType(self.pyobj.string_type))
        str_len = builder.load(builder.gep(str_struct, [zero32, zero32]))
        chars = builder.load(builder.gep(str_struct, [zero32, one32]))
        return str_len, chars
''')
methods.append('''    def _for_i64_loop(self, i64, builder, func, prefix, start, stop):
        """Emit a counting loop header; caller fills body, then closes."""
        idx_ptr = builder.alloca(i64, None, f'{prefix}_i')
        builder.store(start, idx_ptr)
        cond = func.append_basic_block(f"{prefix}_cond")
        body = func.append_basic_block(f"{prefix}_body")
        done = func.append_basic_block(f"{prefix}_done")
        builder.branch(cond)
        builder.position_at_end(cond)
        current = builder.load(idx_ptr)
        more = builder.icmp_signed("<", current, stop)
        builder.cbranch(more, body, done)
        builder.position_at_end(body)
        return idx_ptr, cond, body, done
''')
methods.append('''    def _close_i64_loop(self, builder, idx_ptr, cond, one64):
        builder.store(builder.add(builder.load(idx_ptr), one64), idx_ptr)
        builder.branch(cond)
''')
methods.append('''    def _list_parts(self, builder, func, obj, prefix):
        """Return (struct_ptr, length, items) with items loop-ready."""
        zero32 = ir.const_(ir.IntType(32), 0)
        struct_ptr = self._load_list_struct(builder, obj)
        length = builder.load(builder.gep(struct_ptr, [zero32, zero32]))
        items = builder.load(builder.gep(struct_ptr, [zero32, ir.const_(ir.IntType(32), 2)]))
        return struct_ptr, length, items
''')

# ---- batch 2: case_fold ----
cf = cut_def("def emit_case_fold(")
rep('''        emit_case_fold(
            ir.builder_(self.str_upper.append_basic_block("entry")),
            self.str_upper,
            to_upper=True,
        )''',
'''        self._emit_case_fold(
            ir.builder_(self.str_upper.append_basic_block("entry")),
            self.str_upper,
            True,
            i32, i64, one32, one64, zero32, zero64,
        )''')
rep('''        emit_case_fold(
            ir.builder_(self.str_lower.append_basic_block("entry")),
            self.str_lower,
            to_upper=False,
        )''',
'''        self._emit_case_fold(
            ir.builder_(self.str_lower.append_basic_block("entry")),
            self.str_lower,
            False,
            i32, i64, one32, one64, zero32, zero64,
        )''')
cf_m = ["    def _emit_case_fold(self, builder, func, to_upper, "
        "i32, i64, one32, one64, zero32, zero64):"]
cf_m.extend(dedent4(cf[1:]))
methods.append("\n".join(cf_m))

# ---- batch 3: str_pred ----
sp = cut_def("def emit_str_pred(")
rep('''        self.str_isdigit = emit_str_pred("str_isdigit", [(ord("0"), ord("9"))])
        self.str_isalpha = emit_str_pred(
            "str_isalpha", [(ord("A"), ord("Z")), (ord("a"), ord("z"))]
        )
        self.str_isspace = emit_str_pred(
            "str_isspace", [], extra_bytes=(0x20, 0x09, 0x0A, 0x0B, 0x0C, 0x0D)
        )''',
'''        self.str_isdigit = self._emit_str_pred(
            "str_isdigit", [(ord("0"), ord("9"))], (),
            i64, one32, one64, zero32, zero64, pyobj_ptr,
        )
        self.str_isalpha = self._emit_str_pred(
            "str_isalpha", [(ord("A"), ord("Z")), (ord("a"), ord("z"))], (),
            i64, one32, one64, zero32, zero64, pyobj_ptr,
        )
        self.str_isspace = self._emit_str_pred(
            "str_isspace", [], (0x20, 0x09, 0x0A, 0x0B, 0x0C, 0x0D),
            i64, one32, one64, zero32, zero64, pyobj_ptr,
        )''')
sp_m = ["    def _emit_str_pred(self, name, lo_hi_pairs, extra_bytes, "
        "i64, one32, one64, zero32, zero64, pyobj_ptr):"]
for l in dedent4(sp[1:]):
    sp_m.append(l)
sp_text = "\n".join(sp_m)
sp_text = sp_text.replace(
    "def _emit_str_pred(self, name: str, lo_hi_pairs, extra_bytes=()):",
    "def _emit_str_pred(self, name, lo_hi_pairs, extra_bytes, "
    "i64, one32, one64, zero32, zero64, pyobj_ptr):")
methods.append(sp_text)

# ---- batch 4: sub_search (nested string_parts inlined) ----
ss = cut_def("def emit_sub_search(")
# drop its nested string_parts def from the block
ss_lines = ss
out = []
skip = False
for i, l in enumerate(ss_lines):
    if l.strip().startswith("def string_parts(obj):"):
        skip = True
        continue
    if skip:
        if l.strip() and (len(l) - len(l.lstrip())) <= 12:
            skip = False
        else:
            continue
    out.append(l)
ss = out
rep('''        emit_sub_search(
            ir.builder_(self.str_find.append_basic_block("entry")),
            self.str_find,
            False,
        )''',
'''        self._emit_sub_search(
            ir.builder_(self.str_find.append_basic_block("entry")),
            self.str_find,
            False,
            i32, i64, one32, one64, zero32, zero64,
        )''')
src = src.replace('''        emit_sub_search(
            ir.builder_(self.str_rfind.append_basic_block("entry")),
            self.str_rfind,
            True,
        )''',
'''        self._emit_sub_search(
            ir.builder_(self.str_rfind.append_basic_block("entry")),
            self.str_rfind,
            True,
            i32, i64, one32, one64, zero32, zero64,
        )''')
ss_m = ["    def _emit_sub_search(self, builder, func, from_right, "
        "i32, i64, one32, one64, zero32, zero64):"]
ss_m.append("        s_arg, sub_arg = func.args")
ss_m.append("        s_len_raw, s_chars = self._pyobj_string_parts(builder, s_arg, zero32, one32)")
ss_m.append("        sub_len_raw, sub_chars = self._pyobj_string_parts(builder, sub_arg, zero32, one32)")
ss_m.append("        s_len = builder.sext(s_len_raw, i64)")
ss_m.append("        sub_len = builder.sext(sub_len_raw, i64)")
# append the original body AFTER the string_parts section: find the
# first line past it in the cut block
start_after = next(i for i, l in enumerate(ss)
                   if l.strip().startswith("too_long = builder.icmp_signed"))
for l in dedent4(ss[start_after:]):
    ss_m.append(l)
methods.append("\n".join(ss_m))

# ---- batch 5: dict_field / load_dict_parts ----
rep('''        def dict_field(builder, struct_ptr, index):
            return builder.gep(
                struct_ptr,
                [zero32, ir.const_(i32, index)],
            )

        def load_dict_parts(builder, obj):
            """Return (struct_ptr, count, used, mask, itable, entries)."""
            data = builder.load(builder.gep(obj, [zero32, one32]))
            struct_ptr = builder.bitcast(data, ir.PointerType(self.dict_struct_type))
            count = builder.load(dict_field(builder, struct_ptr, 0))
            used = builder.load(dict_field(builder, struct_ptr, 1))
            mask = builder.load(dict_field(builder, struct_ptr, 2))
            itable = builder.load(dict_field(builder, struct_ptr, 3))
            entries = builder.load(dict_field(builder, struct_ptr, 4))
            return struct_ptr, count, used, mask, itable, entries
''', "        dict_field = _dict_field\n")
src = re.sub(r"load_dict_parts\(builder, (\w+)\)",
             r"self._load_dict_parts(builder, \1, zero32, one32)", src)
methods.append('''    def _load_dict_parts(self, builder, obj, zero32, one32):
        """Return (struct_ptr, count, used, mask, itable, entries)."""
        data = builder.load(builder.gep(obj, [zero32, one32]))
        struct_ptr = builder.bitcast(data, ir.PointerType(self.dict_struct_type))
        count = builder.load(_dict_field(builder, struct_ptr, 0))
        used = builder.load(_dict_field(builder, struct_ptr, 1))
        mask = builder.load(_dict_field(builder, struct_ptr, 2))
        itable = builder.load(_dict_field(builder, struct_ptr, 3))
        entries = builder.load(_dict_field(builder, struct_ptr, 4))
        return struct_ptr, count, used, mask, itable, entries
''')

# ---- batch 6: clamp_bound ----
cb = cut_def("def clamp_bound(")
rep('''        lo_eff = clamp_bound(
            builder, lo_arg, has_lo,
            builder.select(neg_step, len_m1, zero64),
            zero64,
            builder.select(neg_step, len_m1, s_len),
        )''',
'''        lo_eff = self._slice_clamp_bound(
            builder, lo_arg, has_lo,
            builder.select(neg_step, len_m1, zero64),
            zero64,
            builder.select(neg_step, len_m1, s_len),
            s_len, zero64,
        )''')
rep('''        hi_eff = clamp_bound(
            builder, hi_arg, has_hi,
            builder.select(neg_step, ir.const_(i64, -1), s_len),
            builder.select(neg_step, ir.const_(i64, -1), zero64),
            builder.select(neg_step, len_m1, s_len),
        )''',
'''        hi_eff = self._slice_clamp_bound(
            builder, hi_arg, has_hi,
            builder.select(neg_step, ir.const_(i64, -1), s_len),
            builder.select(neg_step, ir.const_(i64, -1), zero64),
            builder.select(neg_step, len_m1, s_len),
            s_len, zero64,
        )''')
cb_m = ["    def _slice_clamp_bound(self, b, bound, has, default, floor, ceil, s_len, zero64):"]
cb_m.extend(dedent4(cb[1:]))
methods.append("\n".join(cb_m))

# ---- batch 7: float repr closures ----
fe = cut_def("def emit(fmt):")
fp = cut_def("def parsed_back(buf):")
fm = cut_def("def is_float_marker(buf, ch):")
rep('buf1 = emit("%.15g")', 'buf1 = self._float_emit_fmt(builder, value, "%.15g")')
rep("ok1 = parsed_back(buf1)", "ok1 = self._float_parsed_back(builder, value, i8p, buf1)")
rep('buf2 = emit("%.16g")', 'buf2 = self._float_emit_fmt(builder, value, "%.16g")')
rep("ok2 = parsed_back(buf2)", "ok2 = self._float_parsed_back(builder, value, i8p, buf2)")
rep('buf3 = emit("%.17g")', 'buf3 = self._float_emit_fmt(builder, value, "%.17g")')
for ch in ('". "', 'e', 'n', 'i'):
    pass
src = src.replace('is_float_marker(buf, ".")', 'self._float_is_marker(builder, i8p, buf, ".")')
src = src.replace('is_float_marker(buf, "e")', 'self._float_is_marker(builder, i8p, buf, "e")')
src = src.replace('is_float_marker(buf, "n")', 'self._float_is_marker(builder, i8p, buf, "n")')
src = src.replace('is_float_marker(buf, "i")', 'self._float_is_marker(builder, i8p, buf, "i")')

fe_m = ["    def _float_emit_fmt(self, builder, value, fmt):"]
fe_m.extend(dedent4(fe[1:]))
methods.append("\n".join(fe_m))
fp_m = ["    def _float_parsed_back(self, builder, value, i8p, buf):"]
fp_m.extend(dedent4(fp[1:]))
methods.append("\n".join(fp_m))
fm_m = ["    def _float_is_marker(self, builder, i8p, buf, ch):"]
fm_m.extend(dedent4(fm[1:]))
methods.append("\n".join(fm_m))

# ---- batch 8: tag closures ----
mi = cut_def("def is_intish(tag):")
ms = cut_def("def is_str(tag):")
src = re.sub(r"(?<![\w.])is_intish\(", "self._tag_is_intish(builder, ", src)
src = re.sub(r"(?<![\w.])is_str\(", "self._tag_is_str(builder, ", src)
mi_m = ["    def _tag_is_intish(self, builder, tag):"]
mi_m.extend(dedent4(mi[1:]))
methods.append("\n".join(mi_m))
ms_m = ["    def _tag_is_str(self, builder, tag):"]
ms_m.extend(dedent4(ms[1:]))
methods.append("\n".join(ms_m))

# ---- batch 9: bool_result string_parts ----
rep('''        def string_parts(obj):
            data = builder.load(builder.gep(obj, [zero32, one32]))
            str_struct = builder.bitcast(
                data, ir.PointerType(self.pyobj.string_type)
            )
            length = builder.load(builder.gep(str_struct, [zero32, zero32]))
            chars = builder.load(builder.gep(str_struct, [zero32, one32]))
            return length, chars

        left_len, left_chars = string_parts(left)
        right_len, right_chars = string_parts(right)''',
'''        left_len, left_chars = self._pyobj_string_parts(builder, left, zero32, one32)
        right_len, right_chars = self._pyobj_string_parts(builder, right, zero32, one32)''')

# ---- defaults / kwargs ----
rep('''    def _create_numeric_binary_function(
        self,
        func_name: str,
        int_apply=None,
        float_apply=None,
        str_int_apply=None,
        zero_check=False,
        overflow_check=False,
    ) -> ir.Function:''',
'''    def _create_numeric_binary_function(
        self,
        func_name,
        int_apply,
        float_apply,
        str_int_apply,
        zero_check,
        overflow_check,
    ) -> ir.Function:''')
rep('''        self.pyobj_sub = self._create_numeric_binary_function(
            "sub",
            int_apply=lambda b, left, right: b.sub(left, right),
            float_apply=lambda b, left, right: b.fsub(left, right),
            overflow_check=True,
        )''',
'''        self.pyobj_sub = self._create_numeric_binary_function(
            "sub",
            lambda b, left, right: b.sub(left, right),
            lambda b, left, right: b.fsub(left, right),
            None,
            False,
            True,
        )''')
rep('''        self.pyobj_mul = self._create_numeric_binary_function(
            "mul",
            int_apply=lambda b, left, right: b.mul(left, right),
            float_apply=lambda b, left, right: b.fmul(left, right),
            str_int_apply=lambda b, s, n: b.call(self.str_repeat, [s, n]),
            overflow_check=True,
        )''',
'''        self.pyobj_mul = self._create_numeric_binary_function(
            "mul",
            lambda b, left, right: b.mul(left, right),
            lambda b, left, right: b.fmul(left, right),
            lambda b, s, n: b.call(self.str_repeat, [s, n]),
            False,
            True,
        )''')
rep('''        self.pyobj_truediv = self._create_numeric_binary_function(
            "truediv",
            float_apply=lambda b, left, right: b.fdiv(left, right),
            zero_check=True,
        )''',
'''        self.pyobj_truediv = self._create_numeric_binary_function(
            "truediv",
            None,
            lambda b, left, right: b.fdiv(left, right),
            None,
            True,
            False,
        )''')
rep('''        self.pyobj_floordiv = self._create_numeric_binary_function(
            "floordiv",
            int_apply=self._floor_div_apply,
            float_apply=self._float_floordiv_apply,
            zero_check=True,
        )''',
'''        self.pyobj_floordiv = self._create_numeric_binary_function(
            "floordiv",
            self._floor_div_apply,
            self._float_floordiv_apply,
            None,
            True,
            False,
        )''')
rep('''        self.pyobj_mod = self._create_numeric_binary_function(
            "mod",
            int_apply=self._py_mod_apply,
            float_apply=self._float_mod_apply,
            zero_check=True,
        )''',
'''        self.pyobj_mod = self._create_numeric_binary_function(
            "mod",
            self._py_mod_apply,
            self._float_mod_apply,
            None,
            True,
            False,
        )''')

rep('''    def _convert_node(
        self, node: Any, skip_func_defs: bool = False
    ) -> Optional[ir.Value]:''',
'''    def _convert_node(
        self, node, skip_func_defs
    ) -> Optional[ir.Value]:''')
rep("self._convert_node(node, skip_func_defs=True)",
    "self._convert_node(node, True)")
src = src.replace("self._convert_node(stmt)", "self._convert_node(stmt, False)")

rep("return [SiluToLLVMConverter._normalize_ir(item) for item in node]",
    '''out = []
        for item in node:
            out.append(SiluToLLVMConverter._normalize_ir(item))
        return out''')
rep('''                    arg_vals = [
                        self._convert_node(arg_node)
                        for arg_node in args_node[:arg_count]
                    ]''',
'''                    arg_vals = []
                    for arg_node in args_node[:arg_count]:
                        arg_vals.append(self._convert_node(arg_node))''')

# ---- staticmethods to module level ----
tree = ast.parse(src)
lines = src.split("\n")
cls = next(n for n in tree.body
           if isinstance(n, ast.ClassDef) and n.name == "SiluToLLVMConverter")
moved = []
blocks = []
for item in cls.body:
    if isinstance(item, ast.FunctionDef) and item.decorator_list:
        start = min(d.lineno - 1 for d in item.decorator_list)
        blocks.append((item.name, start, item.end_lineno))
for name, s, e in sorted(blocks, key=lambda b: -b[1]):
    blk = lines[s:e]
    del lines[s:e]
    out = []
    for l in blk:
        if l.strip() == "@staticmethod":
            continue
        out.append(l[4:] if l.strip() else l)
    moved.append((name, "\n".join(out)))
src = "\n".join(lines)
for name, _ in moved:
    src = src.replace("self." + name + "(", name + "(")

# assemble: methods into the class, module helpers before it
mod_helpers = ["def _dict_field(builder, struct_ptr, index):",
               "    return builder.gep(",
               "        struct_ptr,",
               "        [ir.const_(ir.IntType(32), 0), ir.const_(ir.IntType(32), index)],",
               "    )",
               ""]
for name, text in moved:
    mod_helpers.append(text)
    mod_helpers.append("")
    mod_helpers.append("")
cls_anchor = "class SiluToLLVMConverter:"
assert src.count(cls_anchor) == 1
src = src.replace(cls_anchor, "\n".join(mod_helpers) + "\n" + cls_anchor, 1)

method_anchor = "    def _create_pyobj_print(self):"
assert src.count(method_anchor) == 1
src = src.replace(method_anchor, "\n\n".join(methods) + "\n\n" + method_anchor, 1)

ast.parse(src)
open(PATH, "w").write(src)
print("layer-2 replay complete:", len(methods), "methods hoisted,",
      len(moved), "staticmethods moved")
