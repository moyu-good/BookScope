"""Tests for bookscope.viz.relation_graph_renderer."""


from bookscope.nlp.relation_extractor import CharacterRelation, RelationGraph
from bookscope.viz.relation_graph_renderer import render_relation_graph


def _graph(*relations, characters=None) -> RelationGraph:
    """Build a RelationGraph from (source, target, relation) tuples."""
    rels = [CharacterRelation(source=s, target=t, relation=r) for s, t, r in relations]
    chars = characters or sorted({n for s, t, _ in relations for n in (s, t)})
    return RelationGraph(characters=chars, relations=rels)


def test_empty_graph_returns_none():
    graph = RelationGraph(characters=[], relations=[])
    assert render_relation_graph(graph) is None


def test_single_node_no_relations_returns_none():
    graph = RelationGraph(characters=["Alice"], relations=[])
    assert render_relation_graph(graph) is None


def test_two_nodes_no_relations_returns_none():
    graph = RelationGraph(characters=["Alice", "Bob"], relations=[])
    assert render_relation_graph(graph) is None


def test_valid_graph_returns_figure():
    import plotly.graph_objects as go

    graph = _graph(("Alice", "Bob", "rivals"), ("Alice", "Carol", "allies"))
    fig = render_relation_graph(graph)
    assert fig is not None
    assert isinstance(fig, go.Figure)


def test_figure_has_node_and_edge_traces():
    graph = _graph(
        ("Elizabeth", "Darcy", "rivals"),
        ("Darcy", "Bingley", "friends"),
        ("Elizabeth", "Jane", "sisters"),
    )
    fig = render_relation_graph(graph)
    assert fig is not None
    # Should have at least edge traces + 1 node trace
    assert len(fig.data) >= 2
