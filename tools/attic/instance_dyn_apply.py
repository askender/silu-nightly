"""One-shot: instance boxes in the dynamic layer (tag 6 + class-id side
cell) and compile-time class-id dispatch for attribute reads/writes and
method calls on boxed receivers. Applied to a clean d3cdfe2 checkout;
gate: .ll baseline byte-identical + full suite + the .si compile."""

import ast

PY = "/opt/homebrew/Caskroom/miniforge/base/envs/py312/bin/python3"

# ---------------- silu/silu_ir_to_llvm.py ----------------
src = open("silu/silu_ir_to_llvm.py").read()


def rep(old, new, n=1):
    global src
    assert src.count(old) == n, "BASE MISS(%d): %s" % (src.count(old), old[:70])
    src = src.replace(old, new, n)


# runtime: instance box + accessors
rep('''    def _create_pyobj_print(self):
        """Create PyObject print function."""
        self._create_float_repr_runtime()''',
    '''    def _create_instance_runtime(self):
        """Boxed class instances ride tag 6 with data pointing at a
        {i64 class_id, i8* instance} side cell. Dynamic attribute and
        method dispatch switch on the class id; the converter emits
        those switches from its layout table."""
        pyobj_ptr = ir.PointerType(self.pyobj.pyobj_type)
        i8p = ir.PointerType(ir.IntType(8))
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        cell_ty = ir.LiteralStructType([i64, i8p])
        self.inst_cell_ty = cell_ty

        # PObj* pyobj_make_instance(i64 cid, i8* inst)
        self.pyobj_make_instance = ir.func_(
            self.module, ir.FunctionType(pyobj_ptr, [i64, i8p], False),
            "pyobj_make_instance",
        )
        b = ir.builder_(self.pyobj_make_instance.append_basic_block("entry"))
        cid_arg, inst_arg = self.pyobj_make_instance.args
        cell = b.call(self.malloc, [ir.const_(i64, 16)])
        cellp = b.bitcast(cell, ir.PointerType(cell_ty))
        b.store(cid_arg, b.gep(cellp, [ir.const_(i32, 0), ir.const_(i32, 0)]))
        b.store(
            b.bitcast(inst_arg, i8p),
            b.gep(cellp, [ir.const_(i32, 0), ir.const_(i32, 1)]),
        )
        box_raw = b.call(self.malloc, [ir.const_(i64, 16)])
        box = b.bitcast(box_raw, ir.PointerType(self.pyobj.pyobj_type))
        b.store(
            ir.const_(i32, 6),
            b.gep(box, [ir.const_(i32, 0), ir.const_(i32, 0)]),
        )
        b.store(
            b.bitcast(cell, i8p),
            b.gep(box, [ir.const_(i32, 0), ir.const_(i32, 1)]),
        )
        b.ret(box)

        # i8* pyobj_instance_ptr(PObj* o)
        self.pyobj_instance_ptr = ir.func_(
            self.module, ir.FunctionType(i8p, [pyobj_ptr], False),
            "pyobj_instance_ptr",
        )
        b = ir.builder_(self.pyobj_instance_ptr.append_basic_block("entry"))
        (o_arg,) = self.pyobj_instance_ptr.args
        data = b.load(b.gep(o_arg, [ir.const_(i32, 0), ir.const_(i32, 1)]))
        cellp = b.bitcast(data, ir.PointerType(cell_ty))
        inst = b.load(b.gep(cellp, [ir.const_(i32, 0), ir.const_(i32, 1)]))
        b.ret(inst)

        # i64 pyobj_instance_cid(PObj* o)
        self.pyobj_instance_cid = ir.func_(
            self.module, ir.FunctionType(i64, [pyobj_ptr], False),
            "pyobj_instance_cid",
        )
        b = ir.builder_(self.pyobj_instance_cid.append_basic_block("entry"))
        (o_arg,) = self.pyobj_instance_cid.args
        data = b.load(b.gep(o_arg, [ir.const_(i32, 0), ir.const_(i32, 1)]))
        cellp = b.bitcast(data, ir.PointerType(cell_ty))
        cid = b.load(b.gep(cellp, [ir.const_(i32, 0), ir.const_(i32, 0)]))
        b.ret(cid)

    def _create_pyobj_print(self):
        """Create PyObject print function."""
        self._create_instance_runtime()
        self._create_float_repr_runtime()''')

ast.parse(src)
open("silu/silu_ir_to_llvm.py", "w").write(src)
print("base runtime ok")

# ---------------- silu/typed_codegen.py ----------------
src = open("silu/typed_codegen.py").read()


def rep2(old, new, n=1):
    global src
    assert src.count(old) == n, "TYP MISS(%d): %s" % (src.count(old), old[:70])
    src = src.replace(old, new, n)


# init: class ids + per-value class tracking
rep2('''        LLVM_KIND_TYPES[OBJ] = ir.PointerType(self.pyobj.pyobj_type)
        self._char_idxerr = None''',
     '''        LLVM_KIND_TYPES[OBJ] = ir.PointerType(self.pyobj.pyobj_type)
        # boxed instances: class-id table + per-value class tracking
        # (keyed by llvm value identity, populated at the producer
        # sites: construct, field read, param bind)
        self._class_ids = {}
        self._inst_class = {}
        self._char_idxerr = None''')

# register ids
rep2('''        self._class_layouts[name] = {"fields": fields, "methods": methods}''',
     '''        self._class_layouts[name] = {"fields": fields, "methods": methods}
        if name not in self._class_ids:
            self._class_ids[name] = len(self._class_ids) + 1''')

# producers: construct
rep2('''        return (INSTANCE, inst_ptr)''',
     '''        self._inst_class[id(inst_ptr)] = class_name
        return (INSTANCE, inst_ptr)''')

# producers: field read records instance field class
rep2('''                if kind is None:
                    return (OBJ, value)
                return (kind, value)
        raise AttributeError(f"'{cls}' object has no attribute '{attr}'")''',
     '''                if kind is None:
                    return (OBJ, value)
                if kind == INSTANCE and _fclass:
                    self._inst_class[id(value)] = _fclass
                return (kind, value)
        raise AttributeError(f"'{cls}' object has no attribute '{attr}'")''')

# box INSTANCE with cid
rep2('''        if kind == INSTANCE:
            # opaque box: the instance pointer as its address (identity
            # equality; the dynamic layer only passes instances around,
            # it never inspects them)
            addr = self.current_builder.ptrtoint(
                value, ir.IntType(64)
            )
            return self.current_builder.call(self.create_int, [addr])''',
     '''        if kind == INSTANCE:
            # tag-6 box with a {class_id, instance} side cell: dynamic
            # attribute/method dispatch switches on the class id
            cls = self._inst_class.get(id(value))
            if cls is not None and cls in self._class_ids:
                cid = ir.const_(ir.IntType(64), self._class_ids[cls])
            else:
                cid = ir.const_(ir.IntType(64), -1)
            return self.current_builder.call(
                self.pyobj_make_instance,
                [cid, self.current_builder.bitcast(
                    value, ir.PointerType(ir.IntType(8))
                )],
            )''')

# dynamic dispatch helpers, inserted before _emit_field_read
helpers = '''    def _dyn_member_classes(self, attr, methods):
        """Classes having attr as a field (or method when methods=True),
        in a deterministic order."""
        out = []
        for cls_name in sorted(self._class_layouts):
            layout = self._class_layouts[cls_name]
            if methods:
                if attr in layout["methods"]:
                    out.append(cls_name)
            else:
                for fname, _k, _d, _fc in layout["fields"]:
                    if fname == attr:
                        out.append(cls_name)
                        break
        return out

    def _dyn_dispatch_head(self, recv_tv, what):
        """Shared prologue: check tag 6, load cid + instance pointer.
        Returns (b, cid, inst, bad_block, cell_block)."""
        b = self.current_builder
        func = self.current_function
        obj = recv_tv[1]
        tag = b.load(b.gep(obj, [ir.const_(ir.IntType(32), 0),
                                 ir.const_(ir.IntType(32), 0)]))
        is_inst = b.icmp_signed("==", tag, ir.const_(ir.IntType(32), 6))
        bad = func.append_basic_block("dyn_" + what + "_bad")
        cell = func.append_basic_block("dyn_" + what + "_cell")
        b.cbranch(is_inst, cell, bad)
        b.position_at_end(bad)
        msg = self._create_global_string_with_builder(
            "TypeError: dynamic " + what + " on non-instance", b
        )
        self._emit_panic(b, msg)
        b.position_at_end(cell)
        cid = b.call(self.pyobj_instance_cid, [obj])
        inst = b.call(self.pyobj_instance_ptr, [obj])
        return b, cid, inst

    def _emit_dyn_attr_read(self, recv_tv, attr):
        """obj.attr on a boxed receiver: class-id chain reads the
        matching field; the result is boxed."""
        b, cid, inst = self._dyn_dispatch_head(recv_tv, "getattr")
        func = self.current_function
        classes = self._dyn_member_classes(attr, methods=False)
        merge = func.append_basic_block("ga_merge")
        none_blk = func.append_basic_block("ga_none")
        b.position_at_end(none_blk)
        msg = self._create_global_string_with_builder(
            "AttributeError: no field '" + attr + "'", b
        )
        self._emit_panic(b, msg)
        phis = []
        for cls_name in classes:
            check = func.append_basic_block("ga_chk")
            body = func.append_basic_block("ga_body")
            b.branch(check)
            b.position_at_end(check)
            hit = b.icmp_signed(
                "==", cid,
                ir.const_(ir.IntType(64), self._class_ids[cls_name]),
            )
            b.cbranch(hit, body, check_next := func.append_basic_block("ga_nxt"))
            b.position_at_end(body)
            layout = self._class_layouts[cls_name]
            for idx, (fname, fkind, _d, _fc) in enumerate(layout["fields"]):
                if fname != attr:
                    continue
                slot = self._field_slot(inst, idx, fkind)
                value = b.load(slot)
                if fkind is None:
                    fkind = OBJ
                boxed = self._box((fkind, value))
                b.branch(merge)
                phis.append((boxed, b.block))
                break
            b.position_at_end(check_next)
        b.branch(merge)
        b.position_at_end(merge)
        phi = b.phi(ir.PointerType(self.pyobj.pyobj_type))
        for val, blk in phis:
            phi.add_incoming(val, blk)
        return (OBJ, phi)

    def _emit_dyn_attr_write(self, recv_tv, attr, value_tv):
        """obj.attr = value on a boxed receiver: class-id chain stores
        into the matching field (value coerced per class)."""
        b, cid, inst = self._dyn_dispatch_head(recv_tv, "setattr")
        func = self.current_function
        classes = self._dyn_member_classes(attr, methods=False)
        done = func.append_basic_block("sa_done")
        none_blk = func.append_basic_block("sa_none")
        b.position_at_end(none_blk)
        msg = self._create_global_string_with_builder(
            "AttributeError: no field '" + attr + "'", b
        )
        self._emit_panic(b, msg)
        for cls_name in classes:
            check = func.append_basic_block("sa_chk")
            body = func.append_basic_block("sa_body")
            b.branch(check)
            b.position_at_end(check)
            hit = b.icmp_signed(
                "==", cid,
                ir.const_(ir.IntType(64), self._class_ids[cls_name]),
            )
            b.cbranch(hit, body, check_next := func.append_basic_block("sa_nxt"))
            b.position_at_end(body)
            layout = self._class_layouts[cls_name]
            for idx, (fname, fkind, _d, _fc) in enumerate(layout["fields"]):
                if fname != attr:
                    continue
                coerced = self._coerce(value_tv, fkind)
                slot = self._field_slot(inst, idx, fkind)
                b.store(coerced[1], slot)
                b.branch(done)
                break
            b.position_at_end(check_next)
        b.branch(done)
        b.position_at_end(done)
        return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

    def _emit_dyn_method_call(self, recv_tv, method_name, args_node):
        """obj.m(args) on a boxed receiver: class-id chain calls the
        compiled method with the unboxed instance as self; boxed
        arguments pass through (methods with object params)."""
        b, cid, inst = self._dyn_dispatch_head(recv_tv, "method")
        func = self.current_function
        classes = self._dyn_member_classes(method_name, methods=True)
        merge = func.append_basic_block("mc_merge")
        none_blk = func.append_basic_block("mc_none")
        b.position_at_end(none_blk)
        msg = self._create_global_string_with_builder(
            "AttributeError: no method '" + method_name + "'", b
        )
        self._emit_panic(b, msg)
        phis = []
        for cls_name in classes:
            check = func.append_basic_block("mc_chk")
            body = func.append_basic_block("mc_body")
            b.branch(check)
            b.position_at_end(check)
            hit = b.icmp_signed(
                "==", cid,
                ir.const_(ir.IntType(64), self._class_ids[cls_name]),
            )
            b.cbranch(hit, body, check_next := func.append_basic_block("mc_nxt"))
            b.position_at_end(body)
            mangled = self._class_layouts[cls_name]["methods"][method_name]
            mfn = self.functions.get(mangled) or self.static_funcs.get(
                mangled, (None, None, None)
            )[2]
            if mfn is None:
                b.position_at_end(check_next)
                continue
            # evaluate args fresh per matching class (single-class
            # programs dominate; multi-class re-evaluates - side
            # effects already committed in earlier chains are a known
            # limitation)
            arg_vals = []
            for an in args_node:
                atv = self._convert_node(an)
                arg_vals.append(self._box(atv))
            inst_cast = b.bitcast(
                inst, ir.PointerType(ir.IntType(8))
            )
            result = b.call(mfn, [inst_cast] + arg_vals, "")
            if mfn.ftype.ret is not None and str(mfn.ftype.ret) != "void":
                phis.append((result, b.block))
            b.branch(merge)
            b.position_at_end(check_next)
        b.branch(merge)
        b.position_at_end(merge)
        if not phis:
            return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))
        first_ty = phis[0][0].type
        if all(p[0].type == first_ty for p in phis):
            if str(first_ty) == "void":
                return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))
            phi = b.phi(first_ty)
            for val, blk in phis:
                phi.add_incoming(val, blk)
            return ("func:__dynret", phi)
        return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

'''
anchor = "    def _emit_field_read(self, obj_node: Any, attr: str) -> Tuple[str, Any]:"
assert src.count(anchor) == 1
src = src.replace(anchor, helpers + anchor, 1)
ast.parse(src)
open("silu/typed_codegen.py", "w").write(src)
print("typed helpers ok")
