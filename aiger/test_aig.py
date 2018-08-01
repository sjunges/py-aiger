import hypothesis.strategies as st
from hypothesis import given

import aiger
from aiger import bv
from aiger import bv_utils
from aiger import common
from aiger import hypothesis as aigh


@given(aigh.Circuits, st.data())
def test_aig_to_aag(circ, data):
    circ2 = circ._to_aag()._to_aig()
    assert circ.inputs == circ2.inputs
    assert circ.outputs == circ2.outputs
    test_input = {f'{i}': data.draw(st.booleans()) for i in circ.inputs}
    assert circ(test_input) == circ2(test_input)


def test_aig_to_aag2():
    expr = abs(bv.BV(2, 'x'))
    circ = expr.aig
    circ2 = circ._to_aag()._to_aig()
    assert circ.inputs == circ2.inputs
    assert circ.outputs == circ2.outputs

    bv_utils.simplify(expr)  # smoke test


def test_sink_aag():
    circ = aiger.common.sink(['x', 'y'])
    assert len(circ._to_aag().inputs) != 0
    assert len(circ._to_aag().outputs) == 0
    assert len(circ._to_aag().latches) == 0
    circ2 = circ._to_aag()._to_aig()
    assert circ.inputs == circ2.inputs
    assert circ.outputs == circ2.outputs


@given(aigh.Circuits, st.data())
def test_dummylatches_aag(circ, ddata):
    circ2 = circ._replace(
        latch2init={common._fresh(): False}
    )
    circ3 = circ._to_aag()._to_aig()
    assert circ2.inputs == circ3.inputs
    assert circ3.outputs == circ3.outputs
    assert circ3.latches == circ3.latches
