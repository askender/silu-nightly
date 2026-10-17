"""A drop-in text-serializing workalike of llvmlite.ir for the Silu
toolchain (no llvmlite dependency, no LLVM C API - the build pipeline
ends at .ll text plus an external clang).

Written in the dual-valid style (valid Python and valid Silu): no
capturing closures, no comprehensions, no default arguments, no
keyword calls, no decorators, no inheritance. Kept byte-identical to
selfhost/llvmlite.si (test-locked).

It reproduces llvmlite.ir's exact output text, including its naming
scheme (per-function NameScope; unnamed values deduplicate to
".N") and its formatting quirks (empty flag/metadata slots still
emit their separator spaces).

Constructors are module-level factory functions (const_, func_,
gvar_, builder_, module_) because Silu's auto-generated class
constructor takes every declared field; the classes themselves stay
isinstance-able.
"""

class Value:
    pass


class Type:
    pass


# ---------- scopes ----------

class Scope:
    useset: dict
    basemap: dict


def scope_new():
    sc = Scope({}, {})
    sc.useset[""] = True
    return sc


def scope_register(sc, name):
    base = name
    while name in sc.useset:
        nxt = sc.basemap.get(base, 0) + 1
        sc.basemap[base] = nxt
        name = base + "." + str(nxt)
    sc.useset[name] = True
    return name


# ---------- hex helpers (no bin/hex/format builtins in Silu) ----------

def _hex_digit(v):
    if v < 10:
        return chr(ord("0") + v)
    return chr(ord("a") + v - 10)


def _hex2(v):
    return _hex_digit(v // 16) + _hex_digit(v % 16)


# ---------- types (interned by their text form) ----------

class TypeInfo:
    kind: str      # int/double/void/ptr/func/struct/array
    width: int     # int bits
    count: int     # array count
    var_arg: bool  # function vararg
    element: object   # array element / ptr pointee
    elements: list    # struct elements
    ret: object       # function return
    params: list      # function params
    text: str


_type_cache: dict = {}


def _mk_type(kind, width, count, var_arg, element, elements, ret, params, text):
    t = _type_cache.get(text, None)
    if t is not None:
        return t
    t = TypeInfo(kind, width, count, var_arg, element, elements, ret, params, text)
    _type_cache[text] = t
    return t


def IntType(width):
    return _mk_type("int", width, 0, False, None, [], None, [], "i" + str(width))


def DoubleType():
    return _mk_type("double", 0, 0, False, None, [], None, [], "double")


def VoidType():
    return _mk_type("void", 0, 0, False, None, [], None, [], "void")


def PointerType(pointee):
    return _mk_type("ptr", 0, 0, False, pointee, [], None, [], pointee.text + "*")


def LiteralStructType(elements):
    parts = []
    for e in elements:
        parts.append(e.text)
    return _mk_type("struct", 0, 0, False, None, list(elements), None, [],
                    "{" + ", ".join(parts) + "}")


def ArrayType(element, count):
    return _mk_type("array", 0, count, False, element, [], None, [],
                    "[" + str(count) + " x " + element.text + "]")


def FunctionType(ret, params, var_arg):
    parts = []
    for p in params:
        parts.append(p.text)
    if parts:
        joined = ", ".join(parts)
        if var_arg:
            text = ret.text + " (" + joined + ", ...)"
        else:
            text = ret.text + " (" + joined + ")"
    else:
        if var_arg:
            text = ret.text + " (...)"
        else:
            text = ret.text + " ()"
    return _mk_type("func", 0, 0, var_arg, None, [], ret, list(params), text)


class _Undefined:
    pass


Undefined = _Undefined()


# ---------- constants ----------

class Constant:
    type: object
    constant: object
    is_undef: bool


def const_(ty, val):
    c = Constant(ty, False, False)
    if val is Undefined:
        c.is_undef = True
        c.constant = None
        return c
    if val is None:
        if ty.kind == "int":
            c.constant = 0
        elif ty.kind == "double":
            c.constant = 0.0
        else:
            c.constant = None
        return c
    if isinstance(val, (bytes, bytearray)):
        c.constant = val
        return c
    if isinstance(val, Function):
        # a function value stays itself (global initializer entries)
        c.constant = val
        return c
    if isinstance(val, str) and ty.kind == "array":
        # plain-str i8 array constant (the .si path); the reference
        # printer escapes it UTF-8-aware
        c.constant = val
        return c
    if ty.kind == "struct" or ty.kind == "array":
        out = []
        idx = 0
        for v in val:
            if ty.kind == "array":
                et = ty.element
            else:
                et = ty.elements[idx]
            out.append(const_(et, v))
            idx += 1
        c.constant = out
        return c
    c.constant = val
    return c


_PRINTABLE_PUNCT = " !#$%&'()*+,-./:;<=>?@[]^_`{|}~"


def _escape_byte_val(b):
    if ((b >= ord("a") and b <= ord("z"))
            or (b >= ord("A") and b <= ord("Z"))
            or (b >= ord("0") and b <= ord("9"))
            or chr(b) in _PRINTABLE_PUNCT):
        return chr(b)
    return "\\" + _hex2(b)


def utf8_len(s):
    if isinstance(s, (bytes, bytearray)):
        return len(s)
    n = 0
    for ch in s:
        cp = ord(ch)
        if cp < 0x80:
            n += 1
        elif cp < 0x800:
            n += 2
        elif cp < 0x10000:
            n += 3
        else:
            n += 4
    return n


def _escape_str(s):
    # UTF-8 encode + LLVM c"..." escaping, from code points directly
    out = ""
    for ch in s:
        cp = ord(ch)
        if cp < 0x80:
            out += _escape_byte_val(cp)
        elif cp < 0x800:
            out += _escape_byte_val(0xC0 | (cp // 64))
            out += _escape_byte_val(0x80 | (cp & 0x3F))
        elif cp < 0x10000:
            out += _escape_byte_val(0xE0 | (cp // 4096))
            out += _escape_byte_val(0x80 | ((cp // 64) & 0x3F))
            out += _escape_byte_val(0x80 | (cp & 0x3F))
        else:
            out += _escape_byte_val(0xF0 | (cp // 262144))
            out += _escape_byte_val(0x80 | ((cp // 4096) & 0x3F))
            out += _escape_byte_val(0x80 | ((cp // 64) & 0x3F))
            out += _escape_byte_val(0x80 | (cp & 0x3F))
    return out


def _escape_bytes(data):
    out = ""
    for b in data:
        if ((b >= ord("a") and b <= ord("z"))
                or (b >= ord("A") and b <= ord("Z"))
                or (b >= ord("0") and b <= ord("9"))
                or chr(b) in _PRINTABLE_PUNCT):
            out += chr(b)
        else:
            out += "\\" + _hex2(b)
    return out


def _double_bits(value):
    # IEEE-754 double bits as 16 hex digits, without struct.pack:
    # decompose sign/exponent/mantissa by scaling (normal range).
    v = float(value)
    if v == 0.0:
        if str(v)[0] == "-":
            return " " * 6 + "0x8000000000000000"
        return " " * 13 + "0x0"
    sign_bit = 0
    if v < 0.0:
        sign_bit = 1
        v = -v
    e = 0
    while v >= 2.0:
        v = v / 2.0
        e += 1
    while v < 1.0:
        v = v * 2.0
        e -= 1
    exp = e + 1023
    mant = v - 1.0
    mant_bits = 0
    i = 0
    while i < 52:
        mant = mant * 2.0
        if mant >= 1.0:
            mant_bits = mant_bits * 2 + 1
            mant = mant - 1.0
        else:
            mant_bits = mant_bits * 2
        i += 1
    total = sign_bit
    total = total * 2048 + exp
    total = total * 4503599627370496 + mant_bits
    # llvmlite formats the bit pattern with '{:#16x}': the hex text
    # (no leading zeros) right-aligned in 16 columns
    digits = ""
    n = total
    while n >= 16:
        digits = _hex_digit(n % 16) + digits
        n = n // 16
    digits = _hex_digit(n) + digits
    s = "0x" + digits
    while len(s) < 16:
        s = " " + s
    return s


def const_reference(c):
    if c.is_undef:
        return "undef"
    v = c.constant
    if v is None:
        return "null"
    if isinstance(v, list):
        parts = []
        for x in v:
            if isinstance(x, Constant) and isinstance(x.constant, Function):
                # function pointer in a global initializer: the value
                # reference carries its own pointer type (no element
                # type prefix)
                parts.append(const_reference(x))
                continue
            if isinstance(x, Function):
                parts.append(const_reference(x))
                continue
            parts.append(x.type.text + " " + const_reference(x))
        if c.type.kind == "struct":
            return "{" + ", ".join(parts) + "}"
        return "[" + ", ".join(parts) + "]"
    if isinstance(v, (bytes, bytearray)):
        return 'c"' + _escape_bytes(v) + '"'
    if isinstance(v, str):
        return 'c"' + _escape_str(v) + '"'
    if isinstance(v, Function):
        # real llvmlite renders a function value as its own pointer
        # type (retty (params)*) followed by the @name
        return v.ftype.text + "* " + _quote_ref("@", v.name)
    ty = c.type
    if ty.kind == "double":
        return _double_bits(v)
    if isinstance(v, bool):
        if v:
            return "true"
        return "false"
    return str(v)


def const_str(c):
    return c.type.text + " " + const_reference(c)


# ---------- blocks / arguments ----------

def _quote_ref(prefix, name):
    return prefix + '"' + name + '"'


class Argument:
    type: object
    name: str


def argument_str(a):
    return a.type.text + " " + _quote_ref("%", a.name)


class Block:
    function: object
    name: str
    instructions: list
    terminator: object
    is_terminated: bool


def block_str(b):
    out = _label_text(b.name) + ":\n"
    for i in b.instructions:
        out += "  " + instr_str(i) + "\n"
    return out


def _label_text(name):
    simple = len(name) > 0
    first = True
    for ch in name:
        ok = ((ch >= "a" and ch <= "z") or (ch >= "A" and ch <= "Z")
              or ch == "-" or ch == "$" or ch == "." or ch == "_")
        if not first:
            ok = ok or (ch >= "0" and ch <= "9")
        first = False
        if not ok:
            simple = False
    if simple:
        return name
    return '"' + name + '"'


# ---------- instructions ----------

class Instr:
    block: object
    type: object
    opname: str
    name: str
    operands: list
    style: str
    pred: str
    target_ty: object
    indices: list
    callee: object
    value: object
    pointer: object
    cases: list
    incomings: list
    has_result: bool

    def add_incoming(self, value, block):
        self.incomings.append((value, block))

    def add_case(self, value, block):
        self.cases.append((value, block))


def _rstrip(s):
    while len(s) > 0:
        last = s[len(s) - 1]
        if last == " " or last == "\n" or last == "\t":
            s = s[: len(s) - 1]
        else:
            return s
    return s


def instr_str(i):
    body = _instr_body(i)
    if i.has_result:
        return _rstrip(_quote_ref("%", i.name) + " = " + body)
    return _rstrip(body)


def _op_ref(v):
    if isinstance(v, Constant):
        return const_reference(v)
    if isinstance(v, (GlobalVariable, Function)):
        return _quote_ref("@", v.name)
    return _quote_ref("%", v.name)


def _typed(v):
    if isinstance(v, Constant):
        return v.type.text + " " + const_reference(v)
    if isinstance(v, (GlobalVariable, Function)):
        return v.type.text + " " + _quote_ref("@", v.name)
    return v.type.text + " " + _quote_ref("%", v.name)


def _instr_body(i):
    s = i.style
    if s == "plain":
        parts = []
        for op in i.operands:
            parts.append(_op_ref(op))
        return i.opname + " " + i.type.text + " " + ", ".join(parts) + " \n"
    if s == "icmp":
        return ("icmp " + i.pred + " " + i.operands[0].type.text + " "
                + _op_ref(i.operands[0]) + ", " + _op_ref(i.operands[1]) + " \n")
    if s == "fcmp":
        return (i.opname + " " + i.pred + " " + i.operands[0].type.text + " "
                + _op_ref(i.operands[0]) + ", " + _op_ref(i.operands[1]) + " \n")
    if s == "cast":
        return (i.opname + " " + i.operands[0].type.text + " "
                + _op_ref(i.operands[0]) + " to " + i.type.text + " \n")
    if s == "load":
        return ("load " + i.type.text + ", " + i.operands[0].type.text + " "
                + _op_ref(i.operands[0]) + "\n")
    if s == "store":
        return ("store " + i.operands[0].type.text + " "
                + _op_ref(i.operands[0]) + ", " + i.operands[1].type.text + " "
                + _op_ref(i.operands[1]) + "\n")
    if s == "alloca":
        out = i.opname + " " + i.target_ty.text
        if len(i.operands) > 0:
            out += ", " + i.operands[0].type.text + " " + _op_ref(i.operands[0])
        return out
    if s == "gep":
        parts = []
        for idx in i.indices:
            parts.append(_typed(idx))
        return ("getelementptr " + i.target_ty.text + ", "
                + i.pointer.type.text + " " + _op_ref(i.pointer) + ", "
                + ", ".join(parts) + " \n")
    if s == "call":
        fnty = i.callee.ftype
        if fnty.var_arg:
            cty = fnty.text
        else:
            cty = fnty.ret.text
        args = []
        for a in i.operands:
            args.append(_typed(a))
        return ("call " + cty + " " + _quote_ref("@", i.callee.name)
                + "(" + ", ".join(args) + ")\n")
    if s == "ret":
        if i.value is None:
            return "ret void\n"
        return "ret " + i.value.type.text + " " + _op_ref(i.value) + "\n"
    if s == "br":
        return "br label " + _quote_ref("%", i.operands[0].name) + "\n"
    if s == "cbr":
        return ("br i1 " + _op_ref(i.operands[0]) + ", label "
                + _quote_ref("%", i.operands[1].name) + ", label "
                + _quote_ref("%", i.operands[2].name) + "\n")
    if s == "unreachable":
        return "unreachable\n"
    if s == "phi":
        parts = []
        for inc in i.incomings:
            parts.append("[" + _op_ref(inc[0]) + ", "
                         + _quote_ref("%", inc[1].name) + "]")
        return "phi  " + i.type.text + " " + ", ".join(parts) + " \n"
    if s == "select":
        return ("select  " + i.operands[0].type.text + " "
                + _op_ref(i.operands[0]) + ", " + i.operands[1].type.text + " "
                + _op_ref(i.operands[1]) + ", " + i.operands[2].type.text + " "
                + _op_ref(i.operands[2]) + " \n")
    if s == "switch":
        parts = []
        for cs in i.cases:
            parts.append(_typed(cs[0]) + ", label "
                         + _quote_ref("%", cs[1].name))
        return ("switch " + i.value.type.text + " " + _op_ref(i.value)
                + ", label " + _quote_ref("%", i.operands[0].name)
                + " [" + " ".join(parts) + "]  \n")
    if s == "ev":
        parts = []
        for x in i.indices:
            parts.append(str(x))
        return ("extractvalue " + i.operands[0].type.text + " "
                + _op_ref(i.operands[0]) + ", " + ", ".join(parts) + " \n")
    if s == "iv":
        parts = []
        for x in i.indices:
            parts.append(str(x))
        return ("insertvalue " + i.operands[0].type.text + " "
                + _op_ref(i.operands[0]) + ", " + i.operands[1].type.text + " "
                + _op_ref(i.operands[1]) + ", " + ", ".join(parts) + " \n")
    return i.opname + "\n"


# ---------- globals / functions / module ----------

class GlobalVariable:
    module: object
    value_type: object
    name: str
    initializer: object
    global_constant: bool
    unnamed_addr: bool
    linkage: str
    type: object


def gvar_(module, typ, name):
    g = GlobalVariable(module, typ, name, None, False, False, "",
                       PointerType(typ))
    module.globals[name] = g
    return g


def global_str(g):
    if g.global_constant:
        kind = "constant"
    else:
        kind = "global"
    if g.linkage == "":
        if g.initializer is None:
            linkage = "external"
        else:
            linkage = ""
    else:
        linkage = g.linkage
    out = ""
    if linkage != "":
        out += linkage + " "
    if g.unnamed_addr:
        out += "unnamed_addr "
    out += kind + " " + g.value_type.text
    if g.initializer is not None:
        out += " " + const_reference(g.initializer)
    out += "\n"
    return _rstrip(_quote_ref("@", g.name) + " = " + out)


class AttrSet:
    items: list

    def add(self, name):
        if name not in self.items:
            self.items.append(name)


class Function:
    module: object
    ftype: object
    name: str
    scope: Scope
    blocks: list
    args: tuple
    attributes: AttrSet
    linkage: str
    type: object
    entry_basic_block: object

    def append_basic_block(self, name):
        blk = Block(self, scope_register(self.scope, name), [], None, False)
        self.blocks.append(blk)
        if self.entry_basic_block is None:
            self.entry_basic_block = blk
        return blk


def func_(module, ftype, name):
    f = Function(module, ftype, name, None, [], (), AttrSet([]), "",
                 PointerType(ftype), None)
    f.scope = scope_new()
    args = []
    for t in ftype.params:
        a = Argument(t, scope_register(f.scope, ""))
        args.append(a)
    f.args = tuple(args)
    # the return value registers an empty name after the args (it
    # prints nothing for void, but still consumes a ".N" slot)
    scope_register(f.scope, "")
    module.globals[name] = f
    return f


def function_str(f):
    state = "declare"
    if f.blocks:
        state = "define"
    ret = f.ftype.ret.text
    arg_parts = []
    for a in f.args:
        arg_parts.append(argument_str(a))
    args_txt = ", ".join(arg_parts)
    if f.args:
        if f.ftype.var_arg:
            vararg = ", ..."
        else:
            vararg = ""
    else:
        if f.ftype.var_arg:
            vararg = "..."
        else:
            vararg = ""
    prefix_parts = [state]
    if f.linkage != "":
        prefix_parts.append(f.linkage)
    prefix_parts.append(ret)
    out = (" ".join(prefix_parts) + " " + _quote_ref("@", f.name)
           + "(" + args_txt + vararg + ")")
    if len(f.attributes.items) > 0:
        out += " " + " ".join(sorted(f.attributes.items))
    out += "\n"
    if f.blocks:
        out += "{\n"
        for b in f.blocks:
            out += block_str(b)
        out += "}\n"
    return out


class Module:
    name: str
    triple: str
    data_layout: str
    globals: dict


def module_(name):
    m = Module(name, "unknown-unknown-unknown", "", {})
    return m


def module_text(m):
    lines = []
    lines.append('; ModuleID = "' + m.name + '"')
    lines.append('target triple = "' + m.triple + '"')
    lines.append('target datalayout = "' + m.data_layout + '"')
    lines.append("")
    for _k in m.globals:
        g = m.globals[_k]
        if isinstance(g, Function):
            lines.append(function_str(g))
        else:
            lines.append(global_str(g))
    return "\n".join(lines)


# ---------- builder ----------

def _fcmp_pred(prefix, pred):
    if pred == "==":
        return prefix + "eq"
    if pred == "!=":
        return prefix + "ne"
    if pred == "<":
        return prefix + "lt"
    if pred == ">":
        return prefix + "gt"
    if pred == "<=":
        return prefix + "le"
    return prefix + "ge"


def _icmp_signed_pred(pred):
    if pred == "==":
        return "eq"
    if pred == "!=":
        return "ne"
    if pred == "<":
        return "slt"
    if pred == ">":
        return "sgt"
    if pred == "<=":
        return "sle"
    return "sge"


def _icmp_unsigned_pred(pred):
    if pred == "==":
        return "eq"
    if pred == "!=":
        return "ne"
    if pred == "<":
        return "ult"
    if pred == ">":
        return "ugt"
    if pred == "<=":
        return "ule"
    return "uge"


def _mk_instr(block, ty, opname, name, operands, style):
    fn = block.function
    i = Instr(block, ty, opname, scope_register(fn.scope, name),
              operands, style, "", None, [], None, None, None, [], [],
              True)
    if ty is not None and ty.kind == "void":
        i.has_result = False
    return i


def _gep_result_type(ptr, indices):
    # indices[0] offsets within the pointee (no type descent);
    # later indices descend into structs (constant field index) and
    # arrays; a scalar pointee keeps its type
    cur = ptr.type.element
    for idx in indices[1:]:
        if cur.kind == "struct":
            if isinstance(idx, Constant) and isinstance(idx.constant, int):
                cur = cur.elements[idx.constant]
            else:
                return PointerType(cur)
        elif cur.kind == "array":
            cur = cur.element
        else:
            return PointerType(cur)
    return PointerType(cur)


def _ev_result_type(agg, idx):
    if agg.type.kind == "struct":
        return agg.type.elements[idx]
    return agg.type.element


class IRBuilder:
    block: object
    function: object
    anchor: int

    def position_at_end(self, block):
        self.block = block
        self.function = block.function
        self.anchor = -1

    def position_at_start(self, block):
        self.block = block
        self.function = block.function
        self.anchor = 0

    def position_before(self, instr):
        self.block = instr.block
        self.function = instr.block.function
        pos = 0
        for x in instr.block.instructions:
            if x is instr:
                break
            pos += 1
        self.anchor = pos

    def _ins(self, i):
        if self.anchor >= 0:
            self.block.instructions.insert(self.anchor, i)
            self.anchor += 1
        else:
            self.block.instructions.append(i)
        s = i.style
        if (s == "ret" or s == "br" or s == "cbr" or s == "switch"
                or s == "unreachable"):
            self.block.terminator = i
            self.block.is_terminated = True
        return i

    def _bin(self, opname, lhs, rhs, name):
        return self._ins(_mk_instr(self.block, lhs.type, opname, name,
                                   [lhs, rhs], "plain"))

    def add(self, lhs, rhs, name):
        return self._bin("add", lhs, rhs, name)

    def sub(self, lhs, rhs, name):
        return self._bin("sub", lhs, rhs, name)

    def mul(self, lhs, rhs, name):
        return self._bin("mul", lhs, rhs, name)

    def sdiv(self, lhs, rhs, name):
        return self._bin("sdiv", lhs, rhs, name)

    def udiv(self, lhs, rhs, name):
        return self._bin("udiv", lhs, rhs, name)

    def srem(self, lhs, rhs, name):
        return self._bin("srem", lhs, rhs, name)

    def urem(self, lhs, rhs, name):
        return self._bin("urem", lhs, rhs, name)

    def fadd(self, lhs, rhs, name):
        return self._bin("fadd", lhs, rhs, name)

    def fsub(self, lhs, rhs, name):
        return self._bin("fsub", lhs, rhs, name)

    def fmul(self, lhs, rhs, name):
        return self._bin("fmul", lhs, rhs, name)

    def fdiv(self, lhs, rhs, name):
        return self._bin("fdiv", lhs, rhs, name)

    def frem(self, lhs, rhs, name):
        return self._bin("frem", lhs, rhs, name)

    def shl(self, lhs, rhs, name):
        return self._bin("shl", lhs, rhs, name)

    def lshr(self, lhs, rhs, name):
        return self._bin("lshr", lhs, rhs, name)

    def ashr(self, lhs, rhs, name):
        return self._bin("ashr", lhs, rhs, name)

    def and_(self, lhs, rhs, name):
        return self._bin("and", lhs, rhs, name)

    def or_(self, lhs, rhs, name):
        return self._bin("or", lhs, rhs, name)

    def xor(self, lhs, rhs, name):
        return self._bin("xor", lhs, rhs, name)

    def not_(self, value, name):
        rhs = const_(value.type, -1)
        return self._bin("xor", value, rhs, name)

    def icmp_signed(self, pred, lhs, rhs, name):
        i = _mk_instr(self.block, IntType(1), "icmp", name,
                      [lhs, rhs], "icmp")
        i.pred = _icmp_signed_pred(pred)
        return self._ins(i)

    def icmp_unsigned(self, pred, lhs, rhs, name):
        i = _mk_instr(self.block, IntType(1), "icmp", name,
                      [lhs, rhs], "icmp")
        i.pred = _icmp_unsigned_pred(pred)
        return self._ins(i)

    def fcmp_ordered(self, pred, lhs, rhs, name):
        i = _mk_instr(self.block, IntType(1), "fcmp", name,
                      [lhs, rhs], "fcmp")
        i.pred = _fcmp_pred("o", pred)
        return self._ins(i)

    def fcmp_unordered(self, pred, lhs, rhs, name):
        i = _mk_instr(self.block, IntType(1), "fcmp", name,
                      [lhs, rhs], "fcmp")
        i.pred = _fcmp_pred("u", pred)
        return self._ins(i)

    def _cast(self, opname, value, ty, name):
        if value.type is ty or value.type == ty:
            # llvmlite returns the operand unchanged when the target
            # type already matches
            return value
        return self._ins(_mk_instr(self.block, ty, opname, name,
                                   [value], "cast"))

    def zext(self, value, ty, name):
        return self._cast("zext", value, ty, name)

    def sext(self, value, ty, name):
        return self._cast("sext", value, ty, name)

    def trunc(self, value, ty, name):
        return self._cast("trunc", value, ty, name)

    def bitcast(self, value, ty, name):
        return self._cast("bitcast", value, ty, name)

    def ptrtoint(self, value, ty, name):
        return self._cast("ptrtoint", value, ty, name)

    def inttoptr(self, value, ty, name):
        return self._cast("inttoptr", value, ty, name)

    def sitofp(self, value, ty, name):
        return self._cast("sitofp", value, ty, name)

    def fptosi(self, value, ty, name):
        return self._cast("fptosi", value, ty, name)

    def fpext(self, value, ty, name):
        return self._cast("fpext", value, ty, name)

    def fptrunc(self, value, ty, name):
        return self._cast("fptrunc", value, ty, name)

    def load(self, ptr, name):
        i = _mk_instr(self.block, ptr.type.element, "load", name,
                      [ptr], "load")
        return self._ins(i)

    def store(self, value, ptr):
        i = _mk_instr(self.block, VoidType(), "store", "",
                      [value, ptr], "store")
        return self._ins(i)

    def alloca(self, typ, size, name):
        i = _mk_instr(self.block, PointerType(typ), "alloca", name,
                      [], "alloca")
        i.target_ty = typ
        if size is not None:
            i.operands = [size]
        return self._ins(i)

    def gep(self, ptr, indices, name):
        i = _mk_instr(self.block, _gep_result_type(ptr, indices),
                      "getelementptr", name, [], "gep")
        i.target_ty = ptr.type.element
        i.pointer = ptr
        i.indices = list(indices)
        return self._ins(i)

    def call(self, fn, args, name):
        i = _mk_instr(self.block, fn.ftype.ret, "call", name,
                      list(args), "call")
        i.callee = fn
        return self._ins(i)

    def ret(self, value):
        i = _mk_instr(self.block, VoidType(), "ret", "", [], "ret")
        i.value = value
        return self._ins(i)

    def ret_void(self):
        i = _mk_instr(self.block, VoidType(), "ret", "", [], "ret")
        i.value = None
        return self._ins(i)

    def branch(self, target):
        return self._ins(_mk_instr(self.block, VoidType(), "br", "",
                                   [target], "br"))

    def cbranch(self, cond, tblock, fblock):
        return self._ins(_mk_instr(self.block, VoidType(), "br", "",
                                   [cond, tblock, fblock], "cbr"))

    def unreachable(self):
        return self._ins(_mk_instr(self.block, VoidType(),
                                   "unreachable", "", [], "unreachable"))

    def switch(self, value, default):
        i = _mk_instr(self.block, VoidType(), "switch", "",
                      [default], "switch")
        i.value = value
        return self._ins(i)

    def phi(self, ty, name):
        return self._ins(_mk_instr(self.block, ty, "phi", name,
                                   [], "phi"))

    def select(self, cond, lhs, rhs, name):
        return self._ins(_mk_instr(self.block, lhs.type, "select",
                                   name, [cond, lhs, rhs], "select"))

    def extract_value(self, agg, idx, name):
        i = _mk_instr(self.block, _ev_result_type(agg, idx),
                      "extractvalue", name, [agg], "ev")
        i.indices = [idx]
        return self._ins(i)

    def insert_value(self, agg, value, idx, name):
        i = _mk_instr(self.block, agg.type, "insertvalue", name,
                      [agg, value], "iv")
        i.indices = [idx]
        return self._ins(i)


def builder_(block):
    b = IRBuilder(block, block.function, -1)
    return b


