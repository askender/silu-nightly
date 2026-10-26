"""Part 2: the three dynamic-dispatch emitters + hooks (clean control
flow: the cell block branches into the check chain BEFORE the panic
block is terminated)."""

import ast

src = open("silu/typed_codegen.py").read()


def rep(old, new, n=1):
    global src
    assert src.count(old) == n, "MISS(%d): %s" % (src.count(old), old[:70])
    src = src.replace(old, new, n)


helpers = '''    def _dyn_member_classes(self, attr, methods):
        """Classes having attr as a field (or method name), sorted for
        deterministic emission."""
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
        """Prologue: tag-6 check, then cid + instance from the side
        cell. Returns (b, cid, inst); the current block is the
        dispatch-entry (unterminated)."""
        b = self.current_builder
        func = self.current_function
        obj = recv_tv[1]
        tag = b.load(b.gep(obj, [ir.const_(ir.IntType(32), 0),
                                 ir.const_(ir.IntType(32), 0)]))
        is_inst = b.icmp_signed("==", tag, ir.const_(ir.IntType(32), 6))
        bad = func.append_basic_block("dyn_bad")
        cell = func.append_basic_block("dyn_cell")
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
        b, cid, inst = self._dyn_dispatch_head(recv_tv, "getattr")
        func = self.current_function
        classes = self._dyn_member_classes(attr, methods=False)
        merge = func.append_basic_block("ga_merge")
        none_blk = func.append_basic_block("ga_none")
        phis = []
        entry = b.block
        for cls_name in classes:
            check = func.append_basic_block("ga_chk")
            body = func.append_basic_block("ga_body")
            nxt = func.append_basic_block("ga_nxt")
            b.position_at_end(entry)
            b.branch(check)
            b.position_at_end(check)
            hit = b.icmp_signed(
                "==", cid,
                ir.const_(ir.IntType(64), self._class_ids[cls_name]),
            )
            b.cbranch(hit, body, nxt)
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
            entry = nxt
        b.position_at_end(entry)
        b.branch(none_blk)
        b.position_at_end(none_blk)
        msg = self._create_global_string_with_builder(
            "AttributeError: no field '" + attr + "'", b
        )
        self._emit_panic(b, msg)
        b.position_at_end(merge)
        phi = b.phi(ir.PointerType(self.pyobj.pyobj_type))
        for val, blk in phis:
            phi.add_incoming(val, blk)
        return (OBJ, phi)

    def _emit_dyn_attr_write(self, recv_tv, attr, value_tv):
        b, cid, inst = self._dyn_dispatch_head(recv_tv, "setattr")
        func = self.current_function
        classes = self._dyn_member_classes(attr, methods=False)
        done = func.append_basic_block("sa_done")
        none_blk = func.append_basic_block("sa_none")
        entry = b.block
        for cls_name in classes:
            check = func.append_basic_block("sa_chk")
            body = func.append_basic_block("sa_body")
            nxt = func.append_basic_block("sa_nxt")
            b.position_at_end(entry)
            b.branch(check)
            b.position_at_end(check)
            hit = b.icmp_signed(
                "==", cid,
                ir.const_(ir.IntType(64), self._class_ids[cls_name]),
            )
            b.cbranch(hit, body, nxt)
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
            entry = nxt
        b.position_at_end(entry)
        b.branch(none_blk)
        b.position_at_end(none_blk)
        msg = self._create_global_string_with_builder(
            "AttributeError: no field '" + attr + "'", b
        )
        self._emit_panic(b, msg)
        b.position_at_end(done)
        return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

    def _emit_dyn_method_call(self, recv_tv, method_name, args_node):
        b, cid, inst = self._dyn_dispatch_head(recv_tv, "method")
        func = self.current_function
        classes = self._dyn_member_classes(method_name, methods=True)
        merge = func.append_basic_block("mc_merge")
        none_blk = func.append_basic_block("mc_none")
        phis = []
        entry = b.block
        inst_i8 = b.bitcast(inst, ir.PointerType(ir.IntType(8)))
        for cls_name in classes:
            check = func.append_basic_block("mc_chk")
            body = func.append_basic_block("mc_body")
            nxt = func.append_basic_block("mc_nxt")
            b.position_at_end(entry)
            b.branch(check)
            b.position_at_end(check)
            hit = b.icmp_signed(
                "==", cid,
                ir.const_(ir.IntType(64), self._class_ids[cls_name]),
            )
            b.cbranch(hit, body, nxt)
            b.position_at_end(body)
            mangled = self._class_layouts[cls_name]["methods"][method_name]
            mfn = self.functions.get(mangled)
            if mfn is None:
                mfn = self.static_funcs.get(mangled, (None, None, None))[2]
            if mfn is None:
                b.branch(nxt)
                entry = nxt
                continue
            arg_vals = [inst_i8]
            for an in args_node:
                atv = self._convert_node(an)
                arg_vals.append(self._box(atv))
            result = b.call(mfn, arg_vals, "")
            b.branch(merge)
            ret_ty = mfn.ftype.ret
            if ret_ty is not None and str(ret_ty) != "void":
                phis.append((result, b.block))
            entry = nxt
        b.position_at_end(entry)
        b.branch(none_blk)
        b.position_at_end(none_blk)
        msg = self._create_global_string_with_builder(
            "AttributeError: no method '" + method_name + "'", b
        )
        self._emit_panic(b, msg)
        b.position_at_end(merge)
        if not phis:
            return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))
        first_ty = phis[0][0].type
        if all(p[0].type == first_ty for p in phis):
            if str(first_ty) == "void":
                return (OBJ, ir.const_(
                    ir.PointerType(self.pyobj.pyobj_type), None
                ))
            phi = b.phi(first_ty)
            for val, blk in phis:
                phi.add_incoming(val, blk)
            return ("func:__dynret", phi)
        return (OBJ, ir.const_(ir.PointerType(self.pyobj.pyobj_type), None))

'''
anchor = "    def _emit_field_read(self, obj_node: Any, attr: str) -> Tuple[str, Any]:"
assert src.count(anchor) == 1
src = src.replace(anchor, helpers + anchor, 1)

# hooks
rep('''                # obj.attr = value on a class instance
                if self._class_of_node(target[1]) is None:
                    raise NotImplementedError(
                        "attribute assignment is only supported on class "
                        "instances"
                    )''',
    '''                # obj.attr = value on a class instance
                if self._class_of_node(target[1]) is None:
                    recv_tv = self._convert_node(target[1])
                    if recv_tv[0] == OBJ:
                        value_tv = self._convert_node(value_node)
                        self._emit_dyn_attr_write(
                            recv_tv, target[2], value_tv
                        )
                        return (OBJ, null_obj)
                    raise NotImplementedError(
                        "attribute assignment is only supported on class "
                        "instances"
                    )''')

rep('''        cls = self._class_of_node(obj_node)
        mangled = self._class_layouts[cls]["methods"].get(method_name)
        if mangled is None:''',
    '''        cls = self._class_of_node(obj_node)
        if cls is None:
            recv_tv_probe = self._convert_node(obj_node)
            if recv_tv_probe[0] == OBJ:
                return self._emit_dyn_method_call(
                    recv_tv_probe, method_name, args_node
                )
            raise AttributeError(
                f"method '{method_name}' on non-instance receiver"
            )
        mangled = self._class_layouts[cls]["methods"].get(method_name)
        if mangled is None:''')

rep('''            if self._class_of_node(node[1]) is not None:
                return self._emit_field_read(node[1], node[2])
            # dynamic attribute access stays unsupported (null)
            return (OBJ, null_obj)

        if op == "attribute_aug_assign" and len(node) >= 5:''',
    '''            if self._class_of_node(node[1]) is not None:
                return self._emit_field_read(node[1], node[2])
            recv_tv = self._convert_node(node[1])
            if recv_tv[0] == OBJ:
                return self._emit_dyn_attr_read(recv_tv, node[2])
            # dynamic attribute access stays unsupported (null)
            return (OBJ, null_obj)

        if op == "attribute_aug_assign" and len(node) >= 5:''')

ast.parse(src)
open("silu/typed_codegen.py", "w").write(src)
print("part 2 ok")
