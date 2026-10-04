"""Conservative Verilog/SystemVerilog interface importer, standard library only.

Only the selected module's interface is elaborated. Unsupported interfaces
raise DesignError; a partially parsed block is never returned.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from model import DesignError, Node, Port, Document, identifier, expression

NAME=re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*$')
# Preserve strings as one token; quote-only literals ('0/'1) and casts are tokens too.
LEX=re.compile(r'"(?:\\.|[^"\\])*"|\\[^\s]+|`[A-Za-z_][A-Za-z0-9_$]*|(?:\d+)?\s*\'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|\'[01xXzZ]|\d[\d_]*(?:\.[\d_]+)?(?:[eE][+-]?[\d_]+)?|[A-Za-z_$][A-Za-z0-9_$]*|::|\*\*|<<|>>|&&|\|\||===|!==|==|!=|<=|>=|[\s\S]')
CLOSE={'(':')','[':']','{':'}'}
DIRECTIONS={'input','output','inout','ref'}
TYPES={'wire','reg','logic','bit','var','signed','unsigned','byte','shortint','int','integer','longint','time'}
PARAM_TYPES=TYPES|{'real','realtime','shortreal','string'}

@dataclass(frozen=True)
class Token:
    text: str
    line: int
    start: int = 0
    end: int = 0


def fail(message, token=None):
    raise DesignError((f'Line {token.line}: ' if token else '')+message)


def lex(source):
    tokens=[]; pos=0; line=1
    while pos<len(source):
        if source.startswith('//',pos):
            end=source.find('\n',pos); pos=len(source) if end<0 else end; continue
        if source.startswith('/*',pos):
            end=source.find('*/',pos+2)
            if end<0: fail('Unterminated comment',Token('',line))
            line+=source[pos:end+2].count('\n'); pos=end+2; continue
        # Attributes, but not the wildcard event control @(*).
        if source.startswith('(*',pos) and not (tokens and tokens[-1].text=='@'):
            end=source.find('*)',pos+2)
            if end<0: fail('Unterminated attribute (* ... *)',Token('',line))
            line+=source[pos:end+2].count('\n'); pos=end+2; continue
        match=LEX.match(source,pos); word=match.group(0)
        if word=='"': fail('Unterminated string literal',Token(word,line))
        if not word.isspace(): tokens.append(Token(word,line,pos,match.end()))
        line+=word.count('\n'); pos=match.end()
    return tokens


def text(tokens):
    """Token-aware formatting; whitespace inside quoted strings is untouched."""
    return ' '.join(t.text for t in tokens)


def compact(tokens):
    # Expressions used in ranges are shown without lexer's incidental spaces.
    return ''.join(t.text for t in tokens)


def group(tokens,start):
    if start>=len(tokens) or tokens[start].text not in CLOSE: fail('Expected an opening bracket',tokens[start] if start<len(tokens) else None)
    stack=[CLOSE[tokens[start].text]]
    for i in range(start+1,len(tokens)):
        w=tokens[i].text
        if w in CLOSE: stack.append(CLOSE[w])
        elif w in CLOSE.values():
            if not stack or w!=stack.pop(): fail('Mismatched brackets',tokens[i])
            if not stack: return tokens[start+1:i],i+1
    fail('Unclosed bracket',tokens[start])


def split(tokens,sep=','):
    parts=[]; current=[]; i=0
    while i<len(tokens):
        if tokens[i].text in CLOSE:
            _,end=group(tokens,i); current.extend(tokens[i:end]); i=end
        elif tokens[i].text==sep:
            parts.append(current); current=[]; i+=1
        else: current.append(tokens[i]); i+=1
    parts.append(current)
    return parts


def assignment(tokens):
    pieces=split(tokens,'=')
    if len(pieces)!=2 or not pieces[0] or not pieces[1]: fail('Expected parameter NAME = value',tokens[0] if tokens else None)
    return pieces


def check_type(tokens,param=False):
    i=0; words=[]
    while i<len(tokens):
        if tokens[i].text=='[':
            dim,i=group(tokens,i)
            if ':' not in [t.text for t in dim]: fail('Expected range [msb:lsb]',tokens[i-1])
        else:
            word=tokens[i].text
            if word not in (PARAM_TYPES if param else TYPES):
                fail(f'Type \"{word}\" is not supported. typedef, struct, enum, interface and type parameters require a manually defined interface.',tokens[i])
            words.append(word); i+=1
    if len([w for w in words if w in ('reg','logic','bit','byte','shortint','int','integer','longint','time','real','realtime','shortreal','string')])>1:
        fail('Conflicting declaration types',tokens[0])


def parse_parameters(tokens,params,locals_,initial='parameter'):
    mode=initial
    for item in split(tokens):
        if not item: fail('Empty parameter declaration')
        if item[0].text in ('parameter','localparam'): mode=item[0].text; item=item[1:]
        lhs,rhs=assignment(item)
        name=lhs[-1]
        if not NAME.fullmatch(name.text): fail('Parameter arrays and type parameters are not supported',name)
        identifier(name.text); check_type(lhs[:-1],param=True)
        if name.text in params or name.text in locals_: fail(f'Duplicate parameter {name.text}',name)
        if any(t.text.startswith('`') for t in rhs): fail(f'Parameter {name.text} depends on a macro. Import preprocessed HDL.',name)
        (locals_ if mode=='localparam' else params)[name.text]=expression(text(rhs))


def collect_body_locals(tokens,params,locals_):
    # Implementation-local types/arrays must not block an otherwise simple interface.
    # Only scalar localparams referenced by port bounds/defaults are expanded later.
    for part in split(tokens[1:]):
        lhs,rhs=assignment(part)
        if not NAME.fullmatch(lhs[-1].text): continue
        name=lhs[-1].text
        if name in params or name in locals_: fail(f'Duplicate parameter {name}',lhs[-1])
        locals_[name]=text(rhs)


def parse_decl(tokens, direction=None, inherited=None, ignore_default=False):
    """One comma item, with explicit or inherited ANSI direction/type."""
    item=list(tokens)
    if not item: fail('Empty port declaration')
    explicit_direction=item[0].text in DIRECTIONS
    if explicit_direction: direction=item.pop(0).text; inherited=None
    if direction in ('inout','ref'): fail(f'Ports of type {direction} are not yet supported',tokens[0])
    if direction not in ('input','output'): fail('Expected input or output; interface/modport is not yet supported',tokens[0])
    if ignore_default:
        parts=split(item,'=')
        if len(parts)>1:
            if len(parts)!=2 or not parts[1]: fail('Expected a value after port initializer =',tokens[0])
            item=parts[0]
    if any(t.text in ('=','.') or t.text.startswith('`') for t in item): fail('Default port values, modports and macros in ports are not yet supported',tokens[0])
    # Read all top-level words; the last simple identifier before unpacked dims is the name.
    i=0; candidates=[]
    while i<len(item):
        if item[i].text=='[': _,i=group(item,i)
        else:
            if NAME.fullmatch(item[i].text): candidates.append(i)
            i+=1
    if not candidates: fail('Port name not found',tokens[0])
    index=candidates[-1]; name=item[index]; identifier(name.text)
    prefix=item[:index]; suffix=item[index+1:]
    i=0
    while i<len(suffix):
        if suffix[i].text!='[': fail('Unsupported port syntax',suffix[i])
        _,i=group(suffix,i)
    if not prefix and not explicit_direction and inherited is not None: prefix=inherited
    check_type(prefix)
    # Separate qualifiers from dimensions to keep names and Verilog keywords distinct.
    label=text(prefix)+' '+name.text+text(suffix)
    try: port=Port.parse(label.strip())
    except DesignError as exc: fail(str(exc),tokens[0])
    return direction,port,prefix


def body_declarations(tokens):
    """Ignore executable/nested scopes, including function/task argument declarations."""
    scopes={'function':'endfunction','task':'endtask','class':'endclass','covergroup':'endgroup',
            'property':'endproperty','sequence':'endsequence','clocking':'endclocking',
            'specify':'endspecify','generate':'endgenerate','begin':'end','fork':'join',
            'case':'endcase','casex':'endcase','casez':'endcase'}
    stack=[]; i=0
    while i<len(tokens):
        word=tokens[i].text
        if word in scopes:
            stack.append(scopes[word]); i+=1; continue
        if stack:
            if word==stack[-1] or (stack[-1]=='join' and word in ('join_any','join_none')): stack.pop()
            i+=1; continue
        if word in {'parameter','localparam'}|DIRECTIONS|TYPES:
            start=i; i+=1
            while i<len(tokens) and tokens[i].text!=';':
                if tokens[i].text in CLOSE: _,i=group(tokens,i)
                else: i+=1
            if i==len(tokens): fail('Unterminated declaration in module body',tokens[start])
            yield tokens[start:i]; i+=1
        elif word in CLOSE: _,i=group(tokens,i)
        else: i+=1


def inline_locals(value,locals_,active=()):
    # Expand localparams into expressions, leaving overridable parameter names symbolic.
    out=[]
    for token in lex(value):
        if token.text in locals_:
            if token.text in active: fail(f'Circular localparam reference: {token.text}',token)
            out.append('('+inline_locals(locals_[token.text],locals_,(*active,token.text))+')')
        else: out.append(token.text)
    return ' '.join(out)


@dataclass
class ModuleInterface:
    name: str
    header: list[Token]
    body: list[Token]
    line: int

    def to_node(self,instance=None):
        tokens=self.header; i=0; params={}; locals_={}
        if tokens and tokens[0].text=='#':
            param_tokens,i=group(tokens,1)
            if param_tokens: parse_parameters(param_tokens,params,locals_)
        port_tokens=[]
        if i<len(tokens) and tokens[i].text=='(': port_tokens,i=group(tokens,i)
        if i!=len(tokens): fail('Unsupported module header (for example, a package import)',tokens[i])
        for token in [*self.header,*self.body]:
            if token.text.startswith('`') and token.text in ('`ifdef','`ifndef','`elsif','`else','`endif','`include','`define','`undef'):
                fail('Preprocessor directives change the interface. Preprocess the HDL first.',token)
        declarations=list(body_declarations(self.body))
        for decl in declarations:
            if decl[0].text=='parameter': parse_parameters(decl,params,locals_)
            elif decl[0].text=='localparam': collect_body_locals(decl,params,locals_)
        ports=[]
        ansi=bool(port_tokens and port_tokens[0].text in DIRECTIONS)
        if ansi:
            direction=None; inherited=None
            for item in split(port_tokens):
                direction,p,inherited=parse_decl(item,direction,inherited,ignore_default=True); ports.append((direction,p))
            if any(d[0].text in DIRECTIONS for d in declarations): fail('Mixed ANSI/non-ANSI port declarations are not supported')
        elif port_tokens:
            order=[]
            for part in split(port_tokens):
                if len(part)!=1 or not NAME.fullmatch(part[0].text): fail('Expected a list of non-ANSI port names; interface/modport is not supported',part[0] if part else None)
                identifier(part[0].text); order.append(part[0].text)
            declared={}
            for decl in declarations:
                if decl[0].text not in DIRECTIONS: continue
                direction=None; inherited=None
                for part in split(decl):
                    direction,p,inherited=parse_decl(part,direction,inherited,ignore_default=True)
                    if p.name in declared: fail(f'Duplicate port {p.name}',part[0])
                    declared[p.name]=(direction,p)
            if len(set(order))!=len(order): fail('Duplicate names in port list')
            if set(order)!=set(declared): fail('Port list does not match input/output declarations: '+', '.join(sorted(set(order)^set(declared))))
            # Legacy output q; reg [7:0] q; declarations may carry range/sign metadata.
            for decl in declarations:
                if decl[0].text not in TYPES: continue
                inherited=None
                for part in split(decl):
                    # Skip initialized internal variables: they do not declare ports.
                    name_parts=split(part,'='); clean=name_parts[0]
                    try: _,p,inherited=parse_decl(clean,'output',inherited)
                    except DesignError:
                        # Only ignore internal declarations; never hide an unsupported port redeclaration.
                        if any(t.text in declared for t in clean): raise
                        continue
                    if p.name in declared:
                        direction,old=declared[p.name]
                        if old.span and p.span and old.span.replace(' ','')!=p.span.replace(' ',''): fail(f'Conflicting ranges for port {p.name}')
                        if not p.span: p.span=old.span; p.packed_extra=old.packed_extra
                        p.signed=p.signed or old.signed
                        if not p.unpacked: p.unpacked=old.unpacked
                        declared[p.name]=(direction,p)
            ports=[declared[name] for name in order]
        elif any(d[0].text in DIRECTIONS for d in declarations):
            fail('Ports are declared in the body but missing from the header')
        # Localparams do not become illegal #(.LOCAL(...)) instance overrides.
        for name in params: params[name]=inline_locals(params[name],locals_)
        for _,p in ports:
            p.span=compact(lex(inline_locals(p.span,locals_))) if p.span else ''
            p.packed_extra=[compact(lex(inline_locals(d,locals_))) for d in p.packed_extra]
            p.unpacked=[compact(lex(inline_locals(d,locals_))) for d in p.unpacked]
        n=Node(module=self.name,name=instance or 'u_'+self.name,params=params,
               inputs=[p for d,p in ports if d=='input'],outputs=[p for d,p in ports if d=='output'])
        n.normalize()
        try: Document(top='canvas_import_top' if self.name!='canvas_import_top' else 'canvas_import_other',nodes=[n],language='systemverilog').validate()
        except DesignError as exc: fail(f'Module {self.name}: {exc}')
        return n


def modules_from_text(source):
    tokens=lex(source); result=[]; i=0
    # Never accidentally combine mutually exclusive module variants.
    for t in tokens:
        if t.text in ('`ifdef','`ifndef','`elsif','`else','`endif'):
            fail('Conditional compilation requires the file to be preprocessed first.',t)
    while i<len(tokens):
        if tokens[i].text not in ('module','macromodule'): i+=1; continue
        start=tokens[i]; i+=1
        if i<len(tokens) and tokens[i].text in ('automatic','static'): i+=1
        if i==len(tokens): fail('Missing module name',start)
        name=tokens[i]; identifier(name.text); i+=1
        hstart=i
        while i<len(tokens) and tokens[i].text!=';':
            if tokens[i].text in CLOSE: _,i=group(tokens,i)
            else: i+=1
        if i==len(tokens): fail('Unterminated module header',start)
        header=tokens[hstart:i]; i+=1; bstart=i
        while i<len(tokens) and tokens[i].text!='endmodule':
            if tokens[i].text in ('module','macromodule'): fail('Nested modules are not supported',tokens[i])
            i+=1
        if i==len(tokens): fail('endmodule not found',start)
        result.append(ModuleInterface(name.text,header,tokens[bstart:i],start.line)); i+=1
    if not result: fail('No module … endmodule definitions found in the file')
    if len({m.name for m in result})!=len(result): fail('Multiple definitions of the same module in the file')
    return result


def load_modules(path):
    path=Path(path)
    if path.stat().st_size>20*1024*1024: fail('HDL file exceeds 20 MB')
    raw=path.read_bytes()
    try: source=raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        try: source=raw.decode('cp1251')
        except UnicodeDecodeError: fail('Could not read file: use UTF-8 or Windows-1251')
    return modules_from_text(source)
