import re
from collections import defaultdict
from itertools import combinations
from typing import Dict, List, Tuple, TypedDict

from django.db.models import Count

from common.commands.abstract_base_command import AbstractBaseCommand
from core.models import User

from ..forms.get_graph_data_form import GetGraphDataForm
from ..models import Block, Page


class GraphNode(TypedDict):
    uuid: str
    title: str
    slug: str
    page_type: str
    block_count: int
    degree: int


class GraphEdge(TypedDict):
    source: str
    target: str
    weight: int


class GraphData(TypedDict):
    nodes: List[GraphNode]
    edges: List[GraphEdge]


class GetGraphDataCommand(AbstractBaseCommand):
    """Build a node/edge graph of the user's pages and the links between them."""

    def __init__(self, form: GetGraphDataForm) -> None:
        super().__init__()
        self.form = form

    def execute(self) -> GraphData:
        user: User = self.form.cleaned_data["user"]
        include_daily: bool = bool(self.form.cleaned_data.get("include_daily", False))
        include_orphans_raw = self.form.cleaned_data.get("include_orphans")
        include_orphans: bool = (
            True if include_orphans_raw is None else bool(include_orphans_raw)
        )

        pages_qs = Page.objects.filter(user=user).annotate(
            block_count=Count("blocks", distinct=True)
        )
        if not include_daily:
            pages_qs = pages_qs.exclude(page_type="daily")

        pages = list(pages_qs)
        page_by_uuid: Dict[str, Page] = {str(p.uuid): p for p in pages}
        allowed_page_uuids = set(page_by_uuid.keys())

        edge_weights: Dict[Tuple[str, str], int] = defaultdict(int)

        self._collect_tag_edges(user, allowed_page_uuids, edge_weights)
        self._collect_cooccurrence_edges(user, allowed_page_uuids, edge_weights)
        self._collect_wiki_link_edges(user, pages, edge_weights)

        degree: Dict[str, int] = defaultdict(int)
        for (src, tgt), weight in edge_weights.items():
            degree[src] += weight
            degree[tgt] += weight

        edges: List[GraphEdge] = [
            {"source": src, "target": tgt, "weight": weight}
            for (src, tgt), weight in edge_weights.items()
        ]

        nodes: List[GraphNode] = []
        for page in pages:
            page_uuid = str(page.uuid)
            if not include_orphans and degree.get(page_uuid, 0) == 0:
                continue
            nodes.append(
                {
                    "uuid": page_uuid,
                    "title": page.title,
                    "slug": page.slug,
                    "page_type": page.page_type,
                    "block_count": getattr(page, "block_count", 0),
                    "degree": degree.get(page_uuid, 0),
                }
            )

        return {"nodes": nodes, "edges": edges}

    def _collect_tag_edges(
        self,
        user: User,
        allowed_page_uuids: set,
        edge_weights: Dict[Tuple[str, str], int],
    ) -> None:
        """Edges from Block.pages M2M (hashtag-based references)."""
        through = Block.pages.through
        rows = through.objects.filter(block__user=user).values_list(
            "block__page__uuid", "page__uuid"
        )
        for source_uuid, target_uuid in rows:
            source = str(source_uuid)
            target = str(target_uuid)
            if source == target:
                continue
            if source not in allowed_page_uuids or target not in allowed_page_uuids:
                continue
            edge_weights[(source, target)] += 1

    def _collect_cooccurrence_edges(
        self,
        user: User,
        allowed_page_uuids: set,
        edge_weights: Dict[Tuple[str, str], int],
    ) -> None:
        """Edges between every pair of tag pages that co-occur on a block.

        Pairs are normalized (sorted) so the edge is the same regardless of
        which tag was listed first in the block.
        """
        through = Block.pages.through
        rows = through.objects.filter(block__user=user).values_list(
            "block_id", "page__uuid"
        )
        block_tags: Dict[int, List[str]] = defaultdict(list)
        for block_id, page_uuid in rows:
            tag_uuid = str(page_uuid)
            if tag_uuid in allowed_page_uuids:
                block_tags[block_id].append(tag_uuid)

        for tags in block_tags.values():
            if len(tags) < 2:
                continue
            for a, b in combinations(tags, 2):
                if a == b:
                    continue
                pair = (a, b) if a < b else (b, a)
                edge_weights[pair] += 1

    def _collect_wiki_link_edges(
        self,
        user: User,
        pages: List[Page],
        edge_weights: Dict[Tuple[str, str], int],
    ) -> None:
        """Edges from [[Title]] wiki-style links in block content."""
        title_to_uuid: Dict[str, str] = {p.title.lower(): str(p.uuid) for p in pages}
        if not title_to_uuid:
            return

        pattern = re.compile(r"\[\[([^\[\]\n]+?)\]\]")
        blocks = (
            Block.objects.filter(user=user)
            .exclude(content="")
            .values("page__uuid", "content")
        )

        for block in blocks:
            source_uuid = str(block["page__uuid"])
            if source_uuid not in title_to_uuid.values():
                continue
            content = block["content"] or ""
            for match in pattern.finditer(content):
                target_title = match.group(1).strip().lower()
                target_uuid = title_to_uuid.get(target_title)
                if not target_uuid or target_uuid == source_uuid:
                    continue
                edge_weights[(source_uuid, target_uuid)] += 1
