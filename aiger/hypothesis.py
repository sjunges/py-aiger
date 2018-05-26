from uuid import uuid1

import hypothesis.strategies as st
from lenses import bind

from aiger.common import AAG, Header, and_gate, bit_flipper
from hypothesis_cfg import ContextFreeGrammarStrategy
from parsimonious import Grammar, NodeVisitor


CIRC_GRAMMAR = Grammar(u'''
phi =  and / neg / AP
and = "(" _ phi _ "&" _ phi _ ")"
neg = "~" _ phi

_ = ~r" "*
AP = ~r"[a-zA-z]" ~r"[a-zA-Z\d]*"
EOL = "\\n"
''')


def atomic_pred(a, out=None):
    if out is None:
        out = f'l{uuid1()}'

    return AAG(
        header=Header(1, 1, 0, 1, 0),
        inputs={a: 2},
        outputs={out: 2},
        latches={},
        gates=[],
        comments=[''])


class CircVisitor(NodeVisitor):
    def generic_visit(self, _, children):
        return children

    def visit_phi(self, _, children):
        return children[0]

    def visit_AP(self, node, _):
        return atomic_pred(node.text)

    def visit_and(self, _, children):
        _, _, left, _, _, _, right, _, _ = children
        combined = left | right
        return combined >> and_gate(combined.outputs, str(uuid1()))

    def visit_neg(self, _, children):
        _, _, phi = children
        return phi >> bit_flipper(phi.outputs)


def parse(circ_str: str):
    return CircVisitor().visit(CIRC_GRAMMAR.parse(circ_str))


GRAMMAR = {
    'psi': (('(', 'psi', ' & ', 'psi', ')'), ('~ ', 'psi'), ('AP', )),
    'AP': (
        ('a', ),
        ('b', ),
        ('c', ),
        ('d', ),
        ('e', ),
        ('f', ),
        ('g', ),
        ('h', ),
        ('i', ),
        ('j', ),
        ('k', ),
        ('l', ),
    ),
}


def make_circuit(term):
    circ_str = ''.join(term)
    return bind(parse(circ_str)).comments.set([circ_str])


Circuits = st.builds(make_circuit,
                     ContextFreeGrammarStrategy(
                         GRAMMAR, max_length=15, start='psi'))