"""BookScope — Character relation graph renderer.

Receives a RelationGraph and produces a Plotly Figure using networkx spring
layout. Returns None when the graph has no relations (caller skips rendering).

Usage:
    from bookscope.viz.relation_graph_renderer import render_relation_graph
    fig = render_relation_graph(graph)
    if fig:
        st.plotly_chart(fig, use_container_width=True)
"""


import plotly.graph_objects as go

from bookscope.nlp.relation_extractor import RelationGraph


def render_relation_graph(graph: RelationGraph) -> go.Figure | None:
    """Build a Plotly scatter + edge trace figure from a RelationGraph.

    Args:
        graph: RelationGraph with characters and relations.

    Returns:
        Plotly Figure, or None if the graph has fewer than 2 characters or
        no relations.
    """
    if not graph.relations or len(graph.characters) < 2:
        return None

    try:
        import networkx as nx
    except ImportError:
        return None

    G = nx.Graph()
    G.add_nodes_from(graph.characters)
    for rel in graph.relations:
        if rel.source in graph.characters and rel.target in graph.characters:
            G.add_edge(rel.source, rel.target, label=rel.relation)

    if G.number_of_edges() == 0:
        return None

    pos = nx.spring_layout(G, seed=42, k=1.5)

    # Build edge traces
    edge_traces = []
    edge_label_traces = []
    for u, v, data in G.edges(data=True):
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_traces.append(go.Scatter(
            x=[x0, x1, None],
            y=[y0, y1, None],
            mode="lines",
            line={"width": 1.5, "color": "#555"},
            hoverinfo="none",
            showlegend=False,
        ))
        # Midpoint label
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        label = data.get("label", "")
        if label:
            edge_label_traces.append(go.Scatter(
                x=[mx],
                y=[my],
                mode="text",
                text=[label],
                textfont={"size": 9, "color": "#aaa"},
                hoverinfo="none",
                showlegend=False,
            ))

    # Build node trace
    node_x = [pos[n][0] for n in G.nodes()]
    node_y = [pos[n][1] for n in G.nodes()]
    node_text = list(G.nodes())

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        text=node_text,
        textposition="top center",
        textfont={"size": 11, "color": "#e6edf3"},
        marker={
            "size": 14,
            "color": "#7c3aed",
            "line": {"width": 1.5, "color": "#a78bfa"},
        },
        hoverinfo="text",
        showlegend=False,
    )

    fig = go.Figure(
        data=edge_traces + edge_label_traces + [node_trace],
        layout=go.Layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
            yaxis={"showgrid": False, "zeroline": False, "showticklabels": False},
            margin={"l": 10, "r": 10, "t": 10, "b": 10},
            height=260,
            hovermode="closest",
        ),
    )
    return fig
