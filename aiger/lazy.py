"""
Abstractions for lazy compositions/manipulations of And Inverter
Graphs.
"""

from __future__ import annotations

from typing import Union, FrozenSet, Callable, Sequence, Tuple, Mapping

import attr
import funcy as fn
from pyrsistent import pmap
from pyrsistent.typing import PMap

import aiger as A
from aiger.aig import AIG, Node, Shim, Input, AndGate, LatchIn
from aiger.aig import ConstFalse, Inverter, _is_const_true


@attr.s(auto_attribs=True, frozen=True)
class NodeAlgebra:
    node: Node

    def __and__(self, other: NodeAlgebra) -> NodeAlgebra:
        if isinstance(self.node, ConstFalse):
            return self
        elif isinstance(other.node, ConstFalse):
            return other
        elif _is_const_true(self.node):
            return other
        elif _is_const_true(other.node):
            return self

        return NodeAlgebra(AndGate(self.node, other.node))

    def __invert__(self) -> NodeAlgebra:
        if isinstance(self.node, Inverter):
            return NodeAlgebra(self.node.input)
        return NodeAlgebra(Inverter(self.node))


@attr.s(frozen=True, auto_attribs=True)
class LazyAIG:
    iter_nodes: Callable[[], Sequence[Sequence[Node]]]

    inputs: FrozenSet[str] = frozenset()
    latch2init: PMap[str, bool] = pmap()

    # Note: Unlike in aig.AIG, here Nodes **only** serve as keys.
    node_map: PMap[str, Node] = pmap()
    latch_map: PMap[str, Node] = pmap()
    comments: Sequence[str] = ()

    __call__ = AIG.__call__
    relabel = AIG.relabel

    @property
    def __iter_nodes__(self) -> Callable[[], Sequence[Sequence[Node]]]:
        return self.iter_nodes
        
    @property
    def outputs(self) -> FrozenSet[str]:
        return frozenset(self.node_map.keys())

    @property
    def latches(self) -> FrozenSet[str]:
        return frozenset(self.latch_map.keys())

    @property
    def aig(self) -> AIG:
        """Return's flattened AIG represented by this LazyAIG."""

        false = NodeAlgebra(ConstFalse())
        inputs = {i: NodeAlgebra(Input(i)) for i in self.inputs}
        latches = fn.walk_values(
            lambda v: ~false if v else false,
            dict(self.latch2init),
        )

        node_map, latch_map = self(inputs, false=false, latches=latches)

        node_map = {k: v.node for k, v in node_map.items()}
        latch_map = {k: v.node for k, v in latch_map.items()}

        return AIG(
            inputs=self.inputs,
            node_map=node_map,

            # TODO: change when these become PMaps.
            latch_map=frozenset(latch_map.items()),
            latch2init=frozenset(self.latch2init.items()),

            comments=self.comments,
        )

    def __rshift__(self, other: AIG_Like) -> LazyAIG:
        """Cascading composition. Feeds self into other."""
        other = lazy(other)
        interface = self.outputs & other.inputs
        assert not (self.outputs - interface) & other.outputs
        assert not self.latches & other.latches

        passthrough = fn.omit(dict(self.node_map), interface)

        def iter_nodes():
            yield from self.__iter_nodes__()

            def add_shims(node_batch):
                for node in node_batch:
                    if isinstance(node, Input) and (node.name in interface):
                        yield Shim(new=node, old=self.node_map[node.name])
                    else:
                        yield node

            yield from map(add_shims, other.__iter_nodes__())

        return LazyAIG(
            inputs=self.inputs | (other.inputs - interface),
            latch_map=self.latch_map + other.latch_map,
            latch2init=self.latch2init + other.latch2init,
            node_map=other.node_map + passthrough,
            iter_nodes=iter_nodes,
            comments=self.comments + other.comments,
        )

    def __lshift__(self, other: AIG_Like) -> LazyAIG:
        """Cascading composition. Feeds other into self."""
        return lazy(other) >> self

    def __or__(self, other: AIG_Like) -> LazyAIG:
        """Parallel composition between self and other."""
        other = lazy(other)
        assert not self.latches & other.latches
        assert not self.outputs & other.outputs

        def iter_nodes():
            seen = set()  # which inputs have already been emitted.

            def filter_seen(node_batch):
                nonlocal seen
                for node in node_batch:
                    if node in seen:
                        continue
                    elif isinstance(node, Input):
                        seen.add(node)
                    yield node

            batches = fn.chain(self.__iter_nodes__(), other.__iter_nodes__())
            yield from map(filter_seen, batches)

        return LazyAIG(
            inputs=self.inputs | other.inputs,
            latch_map=self.latch_map + other.latch_map,
            latch2init=self.latch2init + other.latch2init,
            node_map=self.node_map + other.node_map,
            iter_nodes=iter_nodes,
            comments=self.comments + other.comments,
        )

    def cutlatches(self, latches=None, renamer=None) -> Tuple[LazyAIG, Labels]:
        """Returns LazyAIG where the latches specified
        in `latches` have been converted into inputs/outputs.

        - If `latches` is `None`, then all latches are cut.
        - `renamer`: is a function from strings to strings which
           determines how to name latches to avoid name collisions.
        """
        raise NotImplementedError

    def loopback(self, *wirings) -> LazyAIG:
        """Returns result of feeding outputs specified in `*wirings` to
        inputs specified in `wirings`.

        Each positional argument (element of wirings) should have the following
        schema:

           {
              'input': str,
              'output': str,
              'latch': str,         # what to name the new latch.
              'init': bool,         # new latch's initial value.
              'keep_output': bool,  # whether output is consumed by feedback.
            }
        """
        raise NotImplementedError

    def unroll(self, horizon, *, init=True, omit_latches=True,
               only_last_outputs=False) -> LazyAIG:
        """
        Returns circuit which computes the same function as
        the sequential circuit after `horizon` many inputs.

        Each input/output has `##time_{time}` appended to it to
        distinguish different time steps.
        """
        raise NotImplementedError

    def __getitem__(self, others):
        """Relabel inputs, outputs, or latches.
        
        `others` is a tuple, (kind, relabels), where 

          1. kind in {'i', 'o', 'l'}
          2. relabels is a mapping from old names to new names.

        Note: The syntax is meant to resemble variable substitution
        notations, i.e., foo[x <- y] or foo[x / y].
        """
        assert isinstance(others, tuple) and len(others) == 2
        kind, relabels = others

        if kind == 'i':
            relabels_ = {v: [k] for k, v in relabels.items()}
            return lazy(A.tee(relabels_)) >> self

        def relabel(k):
            return relabels.get(k, k)

        if kind == 'o':
            node_map = walk_keys(relabel, self.node_map)
            return attr.evolve(self, node_map=node_map)

        # Latches 
        assert kind == 'l'
        latch_map = walk_keys(relabel, self.latch_map)
        latch2init = walk_keys(relabel, self.latch2init)

        def iter_nodes():
            def rename_latches(node_batch):
                for node in node_batch:
                    if isinstance(node, LatchIn) and node.name in relabels:
                        node2 = LatchIn(relabel(node.name))
                        yield node2
                        yield Shim(new=node, old=node2)
                    else:
                        yield node


            return map(rename_latches, self.__iter_nodes__())

        return attr.evolve(
            self, 
            latch_map=latch_map,
            latch2init=latch2init, 
            iter_nodes=iter_nodes
        )


AIG_Like = Union[AIG, LazyAIG]
Labels = Mapping[str, str]


def lazy(circ: Union[AIG, LazyAIG]) -> LazyAIG:
    """Lifts AIG to a LazyAIG."""
    return LazyAIG(
        inputs=circ.inputs,
        latch_map=pmap(circ.latch_map),
        node_map=pmap(circ.node_map),
        latch2init=pmap(circ.latch2init),
        iter_nodes=circ.__iter_nodes__,
        comments=circ.comments,
    )


def walk_keys(func, mapping):
    return fn.walk_keys(func, dict(mapping))


__all__ = ['lazy', 'LazyAIG']
