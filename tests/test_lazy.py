import funcy as fn
import hypothesis.strategies as st
from hypothesis import given
import pytest

import aiger
from aiger import hypothesis as aigh
from aiger.lazy import lazy
from aiger.common import _fresh


def test_lazy_call_smoke():
    x = aiger.atom('x')

    circ = x.aig
    lcirc = lazy(circ)

    assert lcirc({'x': True}) == circ({'x': True})


def test_lazy_flatten_smoke():
    x = aiger.atom('x')

    circ = x.aig
    circ2 = lazy(circ).aig

    assert circ2.inputs == circ.inputs
    assert circ2.outputs == circ.outputs
    assert len(circ2.__iter_nodes__()) == 1


def test_lazy_seq_compose_smoke():
    x, y, z = aiger.atoms('x', 'y', 'z')

    circ = (x & y).with_output('z').aig
    lcirc1 = lazy(circ)
    lcirc2 = lazy(z.aig)
    lcirc3 = lcirc1 >> lcirc2

    assert lcirc3.inputs == {'x', 'y'}
    assert lcirc3.outputs == {z.output}

    expr = aiger.BoolExpr(lcirc3)
    assert expr({'x': True, 'y': True})
    assert not expr({'x': False, 'y': True})
    assert not expr({'x': True, 'y': False})
    assert not expr({'x': False, 'y': False})

    assert len(fn.lcat(expr.aig.__iter_nodes__())) == 3

    lcirc4 = lazy(aiger.source({'x': True, 'y': True})) >> lcirc3
    assert len(fn.lcat(lcirc4.aig.__iter_nodes__())) == 2

    lcirc4 = lazy(aiger.source({'x': False, 'y': True})) >> lcirc3
    assert len(fn.lcat(lcirc4.aig.__iter_nodes__())) == 1


def test_lazy_seq_compose_smoke2():
    x, y, z = aiger.atoms('x', 'y', 'z')

    circ = (x & y).with_output('z').aig
    lcirc1 = lazy(circ)
    lcirc2 = lazy(z.aig)
    lcirc3 = lcirc1 >> lcirc2
    circ3 = lcirc3.aig  # check that it can be flattened.
    assert len(fn.lcat(circ3.__iter_nodes__())) == 3

    lcirc4 = lazy(z.with_output('x').aig) >> lcirc1
    lcirc4.aig


def test_lazy_par_compose_smoke():
    x, y = aiger.atoms('x', 'y')

    lcirc1 = lazy(x.with_output('x').aig)
    lcirc2 = lazy(y.with_output('y').aig)
    lcirc12 = lcirc1 | lcirc2

    assert lcirc12.inputs == {'x', 'y'}
    assert lcirc12.outputs == {'x', 'y'}

    assert lcirc12({'x': True, 'y': True})[0] == {'x': True, 'y': True}


def test_lazy_relabel_smoke():
    x, y = aiger.atoms('x', 'y')

    lcirc = lazy((x & y).with_output('z').aig)

    assert lcirc['i', {'x': 'z'}].inputs == {'z', 'y'}
    assert lcirc['o', {'z': 'w'}].outputs == {'w'}
    assert len(fn.lcat(lcirc.aig.__iter_nodes__())) == 3


def test_lazy_cutlatches_smoke():
    lcirc = lazy(aiger.delay(['x'], [True]))

    lcirc2, l_map = lcirc.cutlatches()
    lcirc2.aig

    assert {'x'} < lcirc2.inputs
    assert len(lcirc2.inputs) == 2

    assert {'x'} < lcirc2.outputs
    assert len(lcirc2.outputs) == 2

    assert len(lcirc2.latches) == 0


def test_lazy_loopback_smoke():
    x, y = aiger.atoms('x', 'y')

    lcirc = lazy((x & y).with_output('z').aig)
    lcirc2 = lcirc.loopback({
        'input': 'x', 'output': 'z',
    })
    lcirc2.aig

    assert lcirc2.inputs == {'y'}
    assert lcirc2.outputs == {'z'}
    assert len(lcirc2.latches) == 1

    lcirc2 = lcirc.loopback({
        'input': 'x', 'output': 'z',
        'keep_output': False,
    })
    lcirc2.aig

    assert lcirc2.inputs == {'y'}
    assert lcirc2.outputs == set()
    assert len(lcirc2.latches) == 1


def test_lazy_unroll_smoke():
    x, y = aiger.atoms('x', 'y')

    lcirc = lazy((x & y).with_output('z').aig)
    lcirc2 = lazy(lcirc).loopback({
        'input': 'x', 'output': 'z', 'init': True,
    })
    circ2 = lcirc2.aig

    lcirc3 = lazy(circ2).unroll(2)
    assert lcirc3.inputs == {'y##time_0', 'y##time_1'}
    assert lcirc3.outputs == {'z##time_1', 'z##time_2'}
    assert lcirc3.latches == set()
    lcirc3.aig

    lcirc3 = lcirc2.aig.unroll(2, only_last_outputs=True)
    assert lcirc3.inputs == {'y##time_0', 'y##time_1'}
    assert lcirc3.outputs == {'z##time_2'}
    assert lcirc3.latches == set()
    circ3 = lcirc3.aig

    circ4 = circ3.relabel('input', {'y##time_0': 'bar', 'y##time_1': 'foo'}) \
                 .relabel('output', {'z##time_2': 'foobar'}) \
                 .aig

    assert circ4.inputs == {'foo', 'bar'}
    assert circ4.outputs == {'foobar'}


@given(aigh.Circuits, st.data())
def test_lazy_flatten(circ, data):
    lcirc = circ.lazy_aig
    assert lcirc.inputs == circ.inputs
    assert lcirc.outputs == circ.outputs
    assert lcirc.latches == circ.latches

    test_input = {f'{i}': data.draw(st.booleans()) for i in circ.inputs}
    assert circ(test_input) == lcirc(test_input)

    circ2 = lcirc.aig
    assert circ(test_input) == circ2(test_input)
    assert circ == circ2


def fresh_io(circ):
    return circ.relabel('input', {i: _fresh() for i in circ.inputs}) \
               .relabel('output', {o: _fresh() for o in circ.outputs})


def assert_lazy_equiv(circ, lcirc, data):
    test_input = {f'{i}': data.draw(st.booleans()) for i in circ.inputs}
    assert circ(test_input) == lcirc(test_input)
    # assert circ == lcirc.aig


@given(aigh.Circuits, aigh.Circuits, st.data())
def test_lazy_seq_flatten(circ1, circ2, data):
    circ1, circ2 = map(fresh_io, (circ1, circ2))

    # 1. Check lazy >> same as eager |.
    assert_lazy_equiv(circ1 | circ2, lazy(circ1) >> circ2, data)

    # 2. Force circuits to share interface.
    circ1 = circ1['o', {fn.first(circ1.outputs): '##test'}]
    circ2 = circ2['i', {fn.first(circ2.inputs): '##test'}]

    # 3. Check lazy >> same as eager >>.
    assert_lazy_equiv(circ1 >> circ2, lazy(circ1) >> circ2, data)


@given(aigh.Circuits, aigh.Circuits, st.data())
def test_lazy_par_compose_flatten(circ1, circ2, data):
    circ1, circ2 = map(fresh_io, (circ1, circ2))

    # 1. Check lazy | same as eager |.
    assert_lazy_equiv(circ1 | circ2, lazy(circ1) | circ2, data)

    # 2. Force circuits to share interface.
    circ1 = circ1['i', {fn.first(circ1.inputs): '##test'}]
    circ2 = circ2['i', {fn.first(circ2.inputs): '##test'}]

    # 3. Check lazy | same as eager |.
    assert_lazy_equiv(circ1 | circ2, lazy(circ1) | circ2, data)


@given(aigh.Circuits, st.data())
def test_lazy_par_feedback_then_cut(circ, data):
    wire = {
        'input': fn.first(circ.inputs),
        'output': fn.first(circ.outputs),
        'keep_output': False,
        'init': True,
        'latch': '##test',
    }
    circ1 = circ.loopback(wire)
    assert '##test' in circ1.latches
    circ1.cutlatches(latches={'##test'})[0]
    
    lcirc1 = lazy(circ).loopback(wire).cutlatches(latches={'##test'})[0]
    assert_lazy_equiv(circ1, lcirc1, data)


@pytest.mark.skip(reason='TODO: will fix later')
@given(aigh.Circuits, st.data(), st.booleans(), st.booleans(), st.booleans())
def test_lazy_unroll_flatten(
        circ, data, init, omit_latches, only_last_outputs
):
    kwargs = {
        'horizon': 3, 'init': init, 'omit_latches': omit_latches,
        'only_last_outputs': only_last_outputs
    }
    circ1, lcirc1 = circ.unroll(**kwargs), lazy(circ).unroll(**kwargs)
    assert_lazy_equiv(circ1, lcirc1, data)
